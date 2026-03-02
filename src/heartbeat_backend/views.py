import time
import threading
import json
from django.http import JsonResponse
from django.core.signing import TimestampSigner, SignatureExpired, BadSignature
from django.views.decorators.http import require_GET
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.middleware.csrf import get_token
from django.http import HttpResponse
from django.contrib.auth import logout
from django.shortcuts import redirect
from .models import HeartbeatEntry, MaintenanceWindow, WatcherState, AlertTransitionEvent
from .models import DeviceFlowSession, ClientKey, current_epoch_int
from .decorators import basic_auth_required
from .decorators import bearer_auth_required
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

# --- DEVICE FLOW & KEY MANAGEMENT ENDPOINTS ---

@csrf_exempt
@require_POST
def api_device_init(request):
    """Step 1: CLI requests a new login session."""
    try:
        data = json.loads(request.body)
    except:
        data = {}
        
    client_name = data.get("client_name", "CLI Client")

    # Create session (expires in 15 mins = 900 secs)
    session = DeviceFlowSession.objects.create(
        client_name=client_name,
        expires_at=current_epoch_int() + 900
    )

    verification_uri = request.build_absolute_uri('/activate/')
    # Force HTTPS if the proxy stripped the headers but we know it's a secure environment
    if verification_uri.startswith("http://") and request.META.get('HTTP_HOST', '').endswith(':8333'):
        verification_uri = verification_uri.replace("http://", "https://")
    return JsonResponse({
        "device_code": session.device_code,
        "user_code": session.user_code,
        "verification_uri": verification_uri,
        "expires_in": 900,
        "interval": 5
    })

@csrf_exempt
@require_POST
def api_device_poll(request):
    """Step 2: CLI polls this endpoint waiting for human approval."""
    try:
        data = json.loads(request.body)
        device_code = data.get("device_code")
    except:
        return JsonResponse({"error": "invalid_request"}, status=400)

    try:
        session = DeviceFlowSession.objects.get(device_code=device_code)
    except DeviceFlowSession.DoesNotExist:
        return JsonResponse({"error": "invalid_grant"}, status=400)

    if session.is_expired():
        session.delete()
        return JsonResponse({"error": "expired_token"}, status=400)

    if not session.is_approved:
        return JsonResponse({"error": "authorization_pending"}, status=400)

    # Step 3: Human approved it! Generate the permanent ClientKey.
    key = ClientKey.objects.create(
        owner=session.assigned_user,
        name=session.client_name
    )

    # Destroy the temporary session
    session.delete()

    return JsonResponse({
        "access_token": key.bearer_token,
        "token_type": "bearer",
        "key_id": key.pk,
        "aes_secret": key.aes_secret,
        "algorithm": "AES-GCM"
    })

def device_switch_user(request):
    """Logs the current user out and redirects to login, then bounces back to /activate/."""
    logout(request)
    # Redirect to the built-in admin login page, passing the ?next= parameter
    return redirect('/admin/login/?next=/activate/')


@csrf_exempt
@login_required
def device_activate(request):
    """The Web UI where the human enters the ABCD-1234 code."""
    error_html = ""
    
    if request.method == "POST":
        user_code = request.POST.get("user_code", "").strip().upper()
        try:
            session = DeviceFlowSession.objects.get(user_code=user_code)
            if session.is_expired():
                error_html = """
                <div style="background-color: #f8d7da; color: #721c24; padding: 15px; border-radius: 5px; margin-bottom: 20px; border: 1px solid #f5c6cb; text-align: center; font-size: 16px;">
                    <div style="font-size: 32px; margin-bottom: 10px;">❌</div>
                    <strong>Code Expired</strong><br><br>
                    That code has expired. Please run: <br><code>hbclient login</code><br> on your terminal again to generate a new code.
                </div>
                """
            else:
                # Approve it and link the user
                session.is_approved = True
                session.assigned_user = request.user
                session.save()
                return HttpResponse("""
                <div style='font-family: sans-serif; max-width: 400px; margin: 50px auto; text-align: center;'>
                    <h2>✅ Device approved!</h2>
                    <p>You can close this window and return to your terminal.</p>
                </div>
                """)
        
        except DeviceFlowSession.DoesNotExist:
            error_html = """
            <div style="background-color: #f8d7da; color: #721c24; padding: 15px; border-radius: 5px; margin-bottom: 20px; border: 1px solid #f5c6cb; text-align: center; font-size: 16px;">
                <div style="font-size: 32px; margin-bottom: 10px;">⚠️</div>
                <strong>Invalid Code</strong><br><br>
                Please check your terminal and try again. Make sure you entered the exact 8-character code.
            </div>
            """

    # --- DYNAMIC SECURITY WARNING ---
    warning_html = ""
    if request.user.is_superuser:
        warning_html = f"""
        <div style="background-color: #fff3cd; color: #856404; padding: 15px; border-radius: 5px; margin-bottom: 20px; border: 1px solid #ffeeba; text-align: left; font-size: 14px; line-height: 1.5;">
            <strong>⚠️ Security Warning</strong><br>
            You are currently logged in as a privileged admin (<b>{request.user.username}</b>).<br><br>
            It is highly recommended to link CLI devices to a dedicated, non-privileged service account rather than your personal admin account.<br><br>
            <a href="/activate/switch-user/" style="color: #0056b3; font-weight: bold; text-decoration: underline;">Log out and switch users</a>
        </div>
        """

    # Render the form (Injecting the error_html right above the input)
    html = f"""
    <div style="font-family: sans-serif; max-width: 400px; margin: 50px auto; text-align: center;">
        <h2>Connect CLI Device</h2>
        {warning_html}
        {error_html}
        <form method="POST">
            <p>Enter the 8-character code from your terminal:</p>
            <input type="text" name="user_code" placeholder="XXXX-XXXX" 
                   style="font-size: 24px; text-transform: uppercase; text-align: center; padding: 10px; width: 100%; letter-spacing: 2px; margin-bottom: 20px; box-sizing: border-box;" required>
            <button type="submit" style="font-size: 18px; padding: 10px 20px; cursor: pointer; background: #007bff; color: white; border: none; border-radius: 5px; width: 100%;">
                Approve Device
            </button>
        </form>
    </div>
    """
    
    # Return 400 so network tools reflect the error, but still render the nice HTML
    status_code = 400 if error_html else 200
    return HttpResponse(html, status=status_code)


@csrf_exempt
@require_POST
@bearer_auth_required
def api_token_rotate(request):
    """CLI background process calls this to get fresh AES keys."""
    key = request.client_key
    key.rotate_keys()
    return JsonResponse({
        "access_token": key.bearer_token,
        "aes_secret": key.aes_secret,
        "key_id": key.id
    })

@csrf_exempt
@require_POST
@bearer_auth_required
def api_token_revoke(request):
    """Graceful teardown from `hbclient logout`."""
    key = request.client_key
    key.is_revoked = True
    key.save()
    return JsonResponse({"status": "revoked"})
