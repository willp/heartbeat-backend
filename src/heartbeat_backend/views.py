import time
import threading
import json
from django.http import JsonResponse
from django.core.signing import TimestampSigner, SignatureExpired, BadSignature
from django.views.decorators.http import require_GET
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from .models import HeartbeatEntry, MaintenanceWindow, WatcherState, AlertTransitionEvent
from .decorators import basic_auth_required
from . import settings

# --- IN-MEMORY CONFIRMATION QUEUE ---
PENDING_CONFIRMATIONS = {'ack': [], 'snooze': []}
QUEUE_LOCK = threading.Lock()

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
    GET: Returns jobs, maintenance windows, and drains the confirmation queue.
    """
    now = timezone.now()
    jobs = list(HeartbeatEntry.objects.values())
    
    signer = TimestampSigner()
    for job in jobs:
        job['ack_token'] = signer.sign(f"ack:{job['id']}")
        job['snooze_token'] = signer.sign(f"snooze:{job['id']}")
    
    windows = list(MaintenanceWindow.objects.filter(
        is_active=True, start_time__lte=now, end_time__gt=now
    ).values())
    
    state = WatcherState.get_state()
    
    # --- DRAIN THE QUEUE ---
    confirmations = []
    if QUEUE_LOCK.acquire(timeout=1.0):
        try:
            if PENDING_CONFIRMATIONS['ack']:
                # Add backticks around the pulled {name}
                names = "\n".join([f"- `{name}`" for name in PENDING_CONFIRMATIONS['ack']])
                confirmations.append(f"✅ Acknowledged:\n{names}")
                PENDING_CONFIRMATIONS['ack'] = [] 
                
            if PENDING_CONFIRMATIONS['snooze']:
                # Add backticks around the pulled {name}
                names = "\n".join([f"- `{name}`" for name in PENDING_CONFIRMATIONS['snooze']])
                confirmations.append(f"💤 Snoozed (1hr):\n{names}")
                PENDING_CONFIRMATIONS['snooze'] = [] 
        finally:
            QUEUE_LOCK.release()
    return JsonResponse({
        "jobs": jobs,
        "maintenance_windows": windows,
        "has_undelivered_alerts": state.has_undelivered_alerts,
        "confirmations": confirmations # <--- Pass to HbWatcher
    })

@csrf_exempt
def api_webhook_bulk_action(request):
    """
    Receives webhook POSTs from the ntfy mobile app.
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
        
    action = request.GET.get('action')
    tokens = request.GET.getlist('t') 
    
    if action not in ['ack', 'snooze'] or not tokens:
        return JsonResponse({"error": "Invalid request"}, status=400)
        
    signer = TimestampSigner()
    processed_names = []
    now = int(time.time())
    
    for token in tokens:
        try:
            original_value = signer.unsign(token, max_age=90000)
            t_action, job_id_str = original_value.split(":")
            if t_action != action: continue
                
            job = HeartbeatEntry.objects.get(pk=int(job_id_str))
            
            if action == "ack" and job.alert_state != 'ACKNOWLEDGED':
                old_state = job.alert_state
                job.alert_state = 'ACKNOWLEDGED'
                job.save()
                AlertTransitionEvent.objects.create(
                    heartbeat_entry=job, timestamp=now,
                    previous_state=old_state, new_state='ACKNOWLEDGED',
                    message="Acknowledged via ntfy mobile app."
                )
                processed_names.append(job.identifier_string())
            elif action == "snooze" and job.alert_state != 'SNOOZED':
                old_state = job.alert_state
                job.alert_state = 'SNOOZED'
                job.snoozed_until = now + 3600 
                job.save()
                AlertTransitionEvent.objects.create(
                    heartbeat_entry=job, timestamp=now,
                    previous_state=old_state, new_state='SNOOZED',
                    message="Snoozed for 1 hour via ntfy mobile app."
                )
                processed_names.append(job.identifier_string())
        except (SignatureExpired, BadSignature, HeartbeatEntry.DoesNotExist, ValueError):
            continue 

    # --- FILL THE QUEUE ---
    if processed_names:
        if QUEUE_LOCK.acquire(timeout=1.0):
            try:
                PENDING_CONFIRMATIONS[action].extend(processed_names)
            finally:
                QUEUE_LOCK.release()

    # Always return 200 OK so the mobile UI clears the notification
    return JsonResponse({"status": "success", "processed_count": len(processed_names)})


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