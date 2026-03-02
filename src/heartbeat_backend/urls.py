"""
URL configuration for heartbeat_backend project.
"""
import random
from django.conf import settings
from django.contrib import admin
from django.urls import path
from django.urls import re_path
from django.views.static import serve
from django.http import HttpResponse
from . import views

# --- NEW: Zero-file Emoji Favicon View ---
def favicon_view(request):
    """Serves the ❣ emoji directly from RAM as an SVG.
        All heart unicode emojis:
        ❣ heart exclamation point
        💓 beating
        💔 broken
        💕 two hearts
        💖 sparkling heart
        💗 growing? heart
        💘 cupid heart
        💙 💚 💛 💜 🖤 💟  🤎 🩵 🩶 🩷 colorful hearts
        💝 ribbon heart
        💞 revolving? hearts
        ❤️‍🩹 bandaged heart
        ❤️‍🔥 heart en fuego
        🫀 gross anatomical heart
        --
        bad ones: 🤍
    """
    all_hearts = ['❣','💔','💖','🩵','💝','❤️‍🩹']
    this_heart = random.choice(all_hearts)
    # why does this sometimes pick an invalid non-unicode  character? 
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">{this_heart}</text></svg>'
    # print(f"Favicon returned:  {this_heart}")
    return HttpResponse(svg, content_type="image/svg+xml")

urlpatterns = [
    path("favicon.ico", favicon_view),

    path("admin/", admin.site.urls),
    
    # Original API Endpoints
    path('api/heartbeats/', views.heartbeat_list_json, name='heartbeat_list_json'),    
    path('api/healthcheck/', views.healthcheck, name='healthcheck'),    

    # New Watcher API Endpoints
    path('api/watcher_data/', views.api_watcher_data, name='api_watcher_data'),
    path('api/bulk_transition/', views.api_bulk_transition, name='api_bulk_transition'),
    path('api/webhook/bulk_action/', views.api_webhook_bulk_action, name='api_webhook_bulk_action'),

    # OAuth Device Flow
    path('api/auth/device/init/', views.api_device_init, name='api_device_init'),
    path('api/auth/device/poll/', views.api_device_poll, name='api_device_poll'),
    path('activate/', views.device_activate, name='device_activate'),
    path('activate/switch-user/', views.device_switch_user, name='device_switch_user'), # <--- ADD THIS

    # Key Lifecycle (Bearer Token Protected)
    path('api/auth/token/rotate/', views.api_token_rotate, name='api_token_rotate'),
    path('api/auth/token/revoke/', views.api_token_revoke, name='api_token_revoke'),

    # HACK for running in container without yet having Caddy
    re_path(r'^static/(?P<path>.*)$', serve, {'document_root': settings.STATIC_ROOT,}),
]