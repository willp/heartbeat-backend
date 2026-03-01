import time
from django.db import models
from django.utils.translation import gettext_lazy as _

def current_epoch_int():
    """Returns the server's current time as an integer epoch."""
    return int(time.time())

# --- NEW ALERTING MODELS ---

class AlertState(models.TextChoices):
    NORMAL = 'NORMAL', _('Normal')
    ALERT_SENT = 'ALERT_SENT', _('Alert Sent')
    ACKNOWLEDGED = 'ACKNOWLEDGED', _('Acknowledged')
    SNOOZED = 'SNOOZED', _('Snoozed')
    IN_MAINTENANCE = 'IN_MAINTENANCE', _('In Maintenance')

class WatcherState(models.Model):
    """Singleton table to track if HbWatcher failed to deliver a push notification."""
    has_undelivered_alerts = models.BooleanField(default=False)
    last_updated = models.BigIntegerField(default=current_epoch_int)

    def save(self, *args, **kwargs):
        self.pk = 1 # Force singleton
        super().save(*args, **kwargs)

    @classmethod
    def get_state(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

class MaintenanceWindow(models.Model):
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    
    # Filters (Supports substring or /regex/)
    hostname_filter = models.CharField(max_length=255, blank=True, null=True)
    app_name_filter = models.CharField(max_length=255, blank=True, null=True)
    port_filter = models.CharField(max_length=255, blank=True, null=True)
    task_filter = models.CharField(max_length=255, blank=True, null=True)
    version_filter = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        status = "ACTIVE" if self.is_active else "INACTIVE"
        return f"[{status}] {self.name} ({self.start_time.strftime('%Y-%m-%d %H:%M')} to {self.end_time.strftime('%H:%M')})"


# --- EXISTING (BUT ENHANCED) HEARTBEAT ENTRY ---

class HeartbeatEntry(models.Model):
    # Mandatory identifiers
    hostname = models.CharField(max_length=255)
    app_name = models.CharField(max_length=255)
    
    # Optional identifiers (part of the unique constraint)
    port = models.IntegerField(null=True, blank=True, default=None)
    task = models.CharField(max_length=255, null=True, blank=True, default=None)

    # Core metadata
    interval = models.IntegerField()
    alert_after = models.IntegerField()
    version = models.CharField(max_length=255, null=True, blank=True, default=None)
    
    # The final report logic from the client caps out at slightly over 1000 chars
    final_report = models.CharField(max_length=1024, null=True, blank=True, default=None)

    # Timestamps (using BigIntegerField to future-proof past the 2038 epoch issue)
    sent_timestamp = models.BigIntegerField()
    received_timestamp = models.BigIntegerField(default=current_epoch_int)
    sender_ip = models.GenericIPAddressField(null=True, blank=True)

    # --- NEW ALERTING FIELDS ---
    alert_state = models.CharField(max_length=20, choices=AlertState.choices, default=AlertState.NORMAL)
    flatlined_at = models.BigIntegerField(null=True, blank=True, default=None)
    snoozed_until = models.BigIntegerField(null=True, blank=True, default=None)

    @property
    def is_alive(self):
        # True if the time elapsed since receipt is LESS than the alert_after window
        current_time = int(time.time())
        return (current_time - self.received_timestamp) <= self.alert_after

    class Meta:
        verbose_name = "Heartbeat Entry"
        verbose_name_plural = "Heartbeat Entries"

        # Enforce the snapshot behavior: only one record exists for this combination
        constraints = [
            models.UniqueConstraint(
                fields=['hostname', 'app_name', 'port', 'task'],
                name='unique_heartbeat_source'
            )
        ]

    @property
    def is_future(self):
        # True if the sender's clock is ahead of the server's clock
        return self.sent_timestamp > self.received_timestamp

    @property
    def delay(self):
        # Calculate delta, returning exactly 0.0 if negative
        delta = float(self.received_timestamp - self.sent_timestamp)
        return max(0.0, delta)

    def identifier_string(self):
        """Standardized string logic combining up to 5 fields for alert messages."""
        port_str = f":{self.port}" if self.port else ""
        task_str = f" [{self.task}]" if self.task else ""
        ver_str = f" (v{self.version})" if self.version else ""
        return f"{self.hostname} | {self.app_name}{port_str}{task_str}{ver_str}"

    def __str__(self):
        # Django Admin relies primarily on __str__ for list display
        port_str = f":{self.port}" if self.port else ""
        task_str = f" [{self.task}]" if self.task else ""
        return f"{self.hostname} | {self.app_name}{port_str}{task_str}"

    def __repr__(self):
        # Friendly representation for terminal debugging and shell usage
        port_str = f", port={self.port}" if self.port else ""
        task_str = f", task='{self.task}'" if self.task else ""
        return (
            f"<HeartbeatEntry(host='{self.hostname}', app='{self.app_name}'"
            f"{port_str}{task_str}, delay={self.delay}s)>"
        )


class AlertTransitionEvent(models.Model):
    heartbeat_entry = models.ForeignKey(HeartbeatEntry, on_delete=models.CASCADE, related_name='transitions')
    timestamp = models.BigIntegerField(default=current_epoch_int)
    previous_state = models.CharField(max_length=20, choices=AlertState.choices)
    new_state = models.CharField(max_length=20, choices=AlertState.choices)
    message = models.TextField()