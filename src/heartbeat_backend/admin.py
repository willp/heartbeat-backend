import time
from django.contrib import admin
from django.db.models import F
from .models import HeartbeatEntry

from django.utils import timezone
from datetime import datetime
from django.utils.timesince import timesince

def seconds_to_human(seconds):
    """Converts integer seconds into a friendly string like '5m' or '2h 30m'."""
    if seconds is None:
        return ""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        m, s = divmod(seconds, 60)
        return f"{m}m {s}s" if s else f"{m}m"
    elif seconds < 86400:
        h, m = divmod(seconds, 3600)
        m = m // 60
        return f"{h}h {m}m" if m else f"{h}h"
    else:
        d, h = divmod(seconds, 86400)
        h = h // 3600
        return f"{d}d {h}h" if h else f"{d}d"

class IsAliveFilter(admin.SimpleListFilter):
    title = 'Alive Status'
    parameter_name = 'is_alive'

    def lookups(self, request, model_admin):
        # The options that show up in the right-hand sidebar
        return (
            ('yes', 'Yes (Alive)'),
            ('no', 'No (Dead)'),
        )

    def queryset(self, request, queryset):
        current_time = int(time.time())
        
        # Translate the Python logic into a DB-level query:
        # received + alert_after >= current_time (Alive)
        # received + alert_after < current_time (Dead)
        if self.value() == 'yes':
            return queryset.annotate(
                expires_at=F('received_timestamp') + F('alert_after')
            ).filter(expires_at__gte=current_time)
        
        if self.value() == 'no':
            return queryset.annotate(
                expires_at=F('received_timestamp') + F('alert_after')
            ).filter(expires_at__lt=current_time)
        
        return queryset

@admin.register(HeartbeatEntry)
class HeartbeatEntryAdmin(admin.ModelAdmin):
    # Front-and-center dashboard columns
    list_display = (
        'alive_status', 
        'hostname', 
        'app_name', 
        'port', 
        'task', 
        'version',
        'interval_human', 
        'alert_after_human', 
        'last_received_human',        
        'delay', 
        'sender_ip',
        'final_report'
    )
    
    # Right-hand sidebar filters (Custom filter + low cardinality fields)
    list_filter = (IsAliveFilter, 'app_name', 'sender_ip', 'hostname', 'task', 'version')
    
    # Top search bar
    search_fields = ('hostname', 'app_name', 'task', 'final_report')
    
    # Prevent manual editing of snapshots
    readonly_fields = (
        'hostname', 'app_name', 'port', 'task', 
        'sender_ip',
        'interval', 'alert_after', 'version', 'final_report',
        'sent_timestamp', 'received_timestamp'
    )

    def has_add_permission(self, request):
        # Disable the "Add" button
        return False

    @admin.display(boolean=True, description='Alive?')
    def alive_status(self, obj):
        return obj.is_alive

    @admin.display(description='Interval', ordering='interval')
    def interval_human(self, obj):
        return seconds_to_human(obj.interval)

    @admin.display(description='Alert After', ordering='alert_after')
    def alert_after_human(self, obj):
        return seconds_to_human(obj.alert_after)

    @admin.display(description='Last Received', ordering='received_timestamp')
    def last_received_human(self, obj):
        delta_t = time.time() - obj.received_timestamp
        # Grab the timezone you just configured in settings.py
        local_tz = timezone.get_current_timezone()
        
        # Convert the integer epoch using your local timezone
        dt = datetime.fromtimestamp(obj.received_timestamp, tz=local_tz)
        
        # Format it nicely
        time_str = dt.strftime('%b %d, %H:%M:%S')
        if delta_t < 60:
            t_since = f"{int(delta_t)} sec"
        else:
            t_since = timesince(dt)
            t_since = t_since.replace("minute", "min").replace("hour", "hr")

        return f"{time_str} ({t_since} ago)"

    class Media:
        css = {
            'all': ('css/force_sidebar_right.css',)
        }
