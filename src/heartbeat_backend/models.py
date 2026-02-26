import time
from django.db import models

def current_epoch_int():
    """Returns the server's current time as an integer epoch."""
    return int(time.time())


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

    @property
    def is_alive(self):
        # True if the time elapsed since receipt is greater than the alert_after window
        current_time = int(time.time())
        return (current_time - self.received_timestamp) <= self.alert_after

    class Meta:
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