import time
from django.contrib import admin
from django.db.models import F
from .models import HeartbeatEntry, MaintenanceWindow, WatcherState, AlertTransitionEvent

from django.utils import timezone
from datetime import datetime
from django.utils.timesince import timesince
from django.utils.html import format_html
from django.template.defaultfilters import linebreaksbr

class AlertTransitionEventInline(admin.TabularInline):
    model = AlertTransitionEvent
    extra = 0
    ordering = ('-timestamp',)
    fields = ('timestamp_display', 'previous_state', 'new_state', 'message')
    readonly_fields = ('timestamp_display', 'previous_state', 'new_state', 'message')
    
    def timestamp_display(self, obj):
        local_tz = timezone.get_current_timezone()
        dt = datetime.fromtimestamp(obj.timestamp, tz=local_tz)
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    timestamp_display.short_description = 'Time'

    def has_add_permission(self, request, obj=None):
        return False
        
    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        """Limit results to only the last 3 days of events."""
        qs = super().get_queryset(request)
        
        # Calculate the epoch for 3 days ago
        # 3 days * 24 hours * 60 mins * 60 secs
        three_days_ago = int(time.time()) - (3 * 24 * 60 * 60)
        
        # Apply the filter. Since this returns a standard QuerySet 
        # (not a slice), Django can safely append its own ID filters.
        return qs.filter(timestamp__gte=three_days_ago)
    

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
    save_on_top = True
    # Front-and-center dashboard columns
    list_display = (
        'alive_status', 
        'alert_state', # <--- NEW
        'hostname', 
        'app_name', 
        'port', 
        'task', 
        'version',
        'interval_human', 
        'alert_after_human', 
        'last_received_human',       
        # 'delay', 
        # 'sender_ip',
        'final_report'
    )

    inlines = [AlertTransitionEventInline]

    fieldsets = (
        # Group 1: The "What" and "Where"
        (
            "Core Identity",
            {
                "fields": ("hostname", "app_name", "port", "task", "version"),
                "description": "Primary identifiers for this heartbeat source.",
            },
        ),
        # Group 2: The "When" (Live Dashboard Data)
        (
            "Status & Timing",
            {
                "fields": (
                    "alert_state",
                    "snoozed_until",
                    "interval",
                    "alert_after",
                    "received_timestamp",
                ),
            },
        ),
        # Group 3: Reporting (The "Why")
        (
            "Report Content",
            {
                "fields": ("final_report",),
            },
        ),
        # Group 4: Technical/Network Info (Hidden by default)
        (
            "Network Metadata",
            {
                "classes": ("collapse",),  # <--- This makes the section collapsible
                "fields": ("sender_ip", "sent_timestamp"),
                "description": "Internal network metadata and original client-side timestamps.",
            },
        ),
    )

    # Right-hand sidebar filters (Custom filter + low cardinality fields)
    list_filter = (IsAliveFilter, 'alert_state', 'app_name', 'sender_ip', 'hostname', 'task', 'version')

    # Top search bar
    search_fields = ('hostname', 'app_name', 'task', 'final_report')
    search_help_text = "Search by Hostname, Application Name, Task name, or the content of the Final Report."

    # Prevent manual editing of snapshots
    readonly_fields = (
        'hostname', 'app_name', 'port', 'task', 
        'sender_ip',
        # 'interval',
        # 'alert_after',
        'version', 'final_report',
        # 'sent_timestamp', 'received_timestamp'
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

        return format_html("{}<br>({} ago)", time_str, t_since)

    class Media:
        css = {
            'all': ('css/force_sidebar_right.css',)
        }

# --- NEW ALERTING MODELS ---

@admin.register(MaintenanceWindow)
class MaintenanceWindowAdmin(admin.ModelAdmin):
    save_on_top = True
    list_display = ('name', 'is_active', 'start_time', 'end_time', 'hostname_filter', 'app_name_filter')
    list_filter = ('is_active',)
    search_fields = ('name', 'hostname_filter', 'app_name_filter', 'task_filter', 'version_filter')
    
    fieldsets = (
        ('Window Details', {
            'fields': ('name', 'is_active', 'start_time', 'end_time')
        }),
        ('Target Filters (Blank matches everything, /regex/ supported)', {
            'fields': ('hostname_filter', 'app_name_filter', 'port_filter', 'task_filter', 'version_filter')
        }),
    )

@admin.register(WatcherState)
class WatcherStateAdmin(admin.ModelAdmin):
    save_on_top = True
    list_display = ('has_undelivered_alerts', 'last_updated_display')

    def last_updated_display(self, obj):
        local_tz = timezone.get_current_timezone()
        dt = datetime.fromtimestamp(obj.last_updated, tz=local_tz)
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    last_updated_display.short_description = 'Last Updated'

    # --- Enforce Singleton Behavior in the UI ---
    def has_add_permission(self, request):
        if self.model.objects.exists():
            return False
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False



@admin.register(AlertTransitionEvent)
class AlertTransitionEventAdmin(admin.ModelAdmin):
    save_on_top = True
    list_display = ('get_identifier', 'timestamp_display', 'previous_state', 'new_state', 'message')
    list_filter = ('new_state', 'previous_state')
    search_fields = ('heartbeat_entry__hostname', 'heartbeat_entry__app_name', 'message')

    def timestamp_display(self, obj):
        local_tz = timezone.get_current_timezone()
        dt = datetime.fromtimestamp(obj.timestamp, tz=local_tz)
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    timestamp_display.short_description = 'Time'

    def get_identifier(self, obj):
        return obj.heartbeat_entry.identifier_string()
    get_identifier.short_description = 'Target'

    # --- Enforce Read-Only Audit Log Behavior ---
    def has_add_permission(self, request):
        return False
        
    def has_change_permission(self, request, obj=None):
        return False
        
    def has_delete_permission(self, request, obj=None):
        return False
