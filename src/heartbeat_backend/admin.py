import time
from django.contrib import admin
from django.db.models import F
from .models import HeartbeatEntry

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
        'interval', 
        'alert_after', 
        'delay', 
        'final_report'
    )
    
    # Right-hand sidebar filters (Custom filter + low cardinality fields)
    list_filter = (IsAliveFilter, 'app_name', 'hostname', 'task', 'version')
    
    # Top search bar
    search_fields = ('hostname', 'app_name', 'task', 'final_report')
    
    # Prevent manual editing of snapshots
    readonly_fields = (
        'hostname', 'app_name', 'port', 'task', 
        'interval', 'alert_after', 'version', 'final_report',
        'sent_timestamp', 'received_timestamp'
    )

    def has_add_permission(self, request):
        # Disable the "Add" button
        return False

    @admin.display(boolean=True, description='Alive?')
    def alive_status(self, obj):
        return obj.is_alive

    class Media:
        css = {
            'all': ('css/force_sidebar_right.css',)
        }