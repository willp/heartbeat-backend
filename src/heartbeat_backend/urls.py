"""
URL configuration for heartbeat_backend project.
"""
from django.conf import settings
from django.contrib import admin
from django.urls import path
from django.urls import re_path
from django.views.static import serve
from . import views

urlpatterns = [
    path("admin/", admin.site.urls),
    
    # Original API Endpoints
    path('api/heartbeats/', views.heartbeat_list_json, name='heartbeat_list_json'),    
    path('api/healthcheck/', views.healthcheck, name='healthcheck'),    

    # New Watcher API Endpoints
    path('api/watcher_data/', views.api_watcher_data, name='api_watcher_data'),
    path('api/bulk_transition/', views.api_bulk_transition, name='api_bulk_transition'),

    # HACK for running in container without yet having Caddy
    re_path(r'^static/(?P<path>.*)$', serve, {'document_root': settings.STATIC_ROOT,}),
]