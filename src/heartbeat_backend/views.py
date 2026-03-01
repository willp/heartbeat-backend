import time
import json
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from .models import HeartbeatEntry, MaintenanceWindow, WatcherState, AlertTransitionEvent
from .decorators import basic_auth_required
from . import settings

@require_GET
@basic_auth_required
def heartbeat_list_json(request):
    """
    Returns all heartbeat records directly from the database as JSON.
    Preserves NULL values as null. Only accepts GET requests.
    """
    data = list(HeartbeatEntry.objects.values())
    return JsonResponse(data, safe=False, json_dumps_params={'indent': 4})

@require_GET
def healthcheck(request):
    return JsonResponse({'operational': True, 'timestamp': int(time.time()), 'uptime': int(time.time() - settings.START_TS)})

# --- NEW WATCHER API ENDPOINTS ---

@require_GET
@basic_auth_required
def api_watcher_data(request):
    """
    GET: Returns all jobs, active maintenance windows, and the failed-delivery flag.
    Used by the external HbWatcher script to evaluate alerting states.
    """
    now = timezone.now()
    jobs = list(HeartbeatEntry.objects.values())
    
    # Only return windows that are currently active and haven't expired
    windows = list(MaintenanceWindow.objects.filter(
        is_active=True,
        start_time__lte=now,
        end_time__gt=now
    ).values())
    
    state = WatcherState.get_state()
    
    return JsonResponse({
        "jobs": jobs,
        "maintenance_windows": windows,
        "has_undelivered_alerts": state.has_undelivered_alerts
    })

@csrf_exempt
@basic_auth_required
def api_bulk_transition(request):
    """
    POST: Accepts bulk DB updates from HbWatcher after it calculates states.
    """
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            updates = data.get("updates", [])
            
            # Update the delivery failure flag based on what HbWatcher reports
            state = WatcherState.get_state()
            state.has_undelivered_alerts = data.get("failed_delivery", False)
            state.save()

            for update in updates:
                try:
                    job = HeartbeatEntry.objects.get(id=update["id"])
                    job.alert_state = update["alert_state"]
                    job.flatlined_at = update["flatlined_at"]
                    if "snoozed_until" in update:
                        job.snoozed_until = update["snoozed_until"]
                    job.save()

                    # Log the transition history
                    AlertTransitionEvent.objects.create(
                        heartbeat_entry=job,
                        previous_state=update["previous_state"],
                        new_state=update["alert_state"],
                        message=update["message"]
                    )
                except HeartbeatEntry.DoesNotExist:
                    continue

            return JsonResponse({"status": "ok"})
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON payload"}, status=400)
            
    return JsonResponse({"error": "POST required"}, status=405)