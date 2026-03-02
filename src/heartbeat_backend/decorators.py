import base64
from functools import wraps
from django.http import HttpResponse
from django.contrib.auth import authenticate, login
import time
from django.http import JsonResponse
from .models import ClientKey

def bearer_auth_required(view_func):
    """Decorator to enforce HTTP Bearer Token Authentication for the CLI."""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        
        if auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
            current_time = int(time.time())
            
            # 1. Try the active token
            try:
                client_key = ClientKey.objects.get(bearer_token=token, is_revoked=False)
                request.client_key = client_key
                return view_func(request, *args, **kwargs)
            except ClientKey.DoesNotExist:
                pass
                
            # 2. Try the fail-safe previous token (Network desync protection)
            try:
                client_key = ClientKey.objects.get(
                    previous_bearer_token=token,
                    is_revoked=False,
                    overlap_expires_at__gte=current_time
                )
                request.client_key = client_key
                return view_func(request, *args, **kwargs)
            except ClientKey.DoesNotExist:
                pass

        # Reject if no valid token is found
        return JsonResponse({'error': 'Unauthorized', 'code': 'invalid_token'}, status=401)

    return _wrapped_view


def basic_auth_required(view_func):
    """Decorator to enforce HTTP Basic Authentication."""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        # Check if the Authorization header is present
        if 'HTTP_AUTHORIZATION' in request.META:
            auth_header = request.META['HTTP_AUTHORIZATION'].split()
            
            # Ensure it's exactly two parts: "Basic" and the base64 string
            if len(auth_header) == 2 and auth_header[0].lower() == "basic":
                try:
                    # Decode the base64 string
                    decoded_credentials = base64.b64decode(auth_header[1]).decode('utf-8')
                    username, password = decoded_credentials.split(':', 1)
                    
                    # Verify against Django's User table
                    user = authenticate(request, username=username, password=password)
                    
                    if user is not None and user.is_active:
                        # Log the user in for this request
                        login(request, user)
                        return view_func(request, *args, **kwargs)
                except Exception:
                    # Catch decoding errors or malformed headers and reject
                    pass

        # If we get here, authentication failed or wasn't provided.
        # This specific response triggers the browser's native login popup
        # or tells the CLI client that it needs to provide credentials.
        response = HttpResponse('Unauthorized', status=401)
        response['WWW-Authenticate'] = 'Basic realm="Heartbeat API"'
        return response

    return _wrapped_view