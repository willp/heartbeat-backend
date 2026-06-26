import time
import secrets
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

def current_epoch_int():
    """Returns the server's current time as an integer epoch."""
    return int(time.time())


# --- NEW ALERTING MODELS ---

class AlertState(models.TextChoices):
    NORMAL = 'NORMAL', _('Normal')
    DEGRADED = 'DEGRADED', _('Degraded (Unencrypted)')
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

    # --- NEW SECURITY FLAGS ---
    is_encrypted = models.BooleanField(default=False, help_text="High-water mark: Has this client ever sent an encrypted packet?")
    enforce_encryption = models.BooleanField(default=False, help_text="Strict Mode: Drop unencrypted packets from this client.")

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


# --- NEW AUTH & CRYPTOGRAPHY MODELS ---
def default_key_expiry():
    """90-day lifespan for client keys."""
    return current_epoch_int() + (90 * 86400)

def generate_secure_token(length=43):
    """Generates a URL-safe base64 token."""
    return secrets.token_urlsafe(length)

def generate_aes_secret():
    """Generates a 32-byte (256-bit) high-entropy key, base64 encoded for DB storage."""
    import base64
    raw_key = secrets.token_bytes(32)
    return base64.b64encode(raw_key).decode('utf-8')

def generate_user_code():
    """Generates a short, human-readable code like ABCD-1234."""
    alpha_charset = "BDFGHJKLMNPQRSTVWXYZ" # Excludes ambiguous I, O. Also A+E+U+C for some badwords
    num_charset = "23456789" # Excludes ambiguous 0, 1
    alpha_code = "".join(secrets.choice(alpha_charset) for _ in range(4))
    num_code = "".join(secrets.choice(num_charset) for _ in range(4))
    return f"{alpha_code}-{num_code}"

class DeviceFlowSession(models.Model):
    """Transient state for the CLI OAuth Device Flow."""
    device_code = models.CharField(max_length=128, unique=True, default=generate_secure_token)
    user_code = models.CharField(max_length=9, unique=True, default=generate_user_code)

    client_name = models.CharField(max_length=255, default="CLI Client")

    # Lifecycle
    created_at = models.BigIntegerField(default=current_epoch_int)
    expires_at = models.BigIntegerField()
    
    # State flags
    is_approved = models.BooleanField(default=False)
    assigned_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        null=True, blank=True, 
        on_delete=models.CASCADE
    )

    def is_expired(self):
        return current_epoch_int() > self.expires_at

    def __str__(self):
        status = "APPROVED" if self.is_approved else "PENDING"
        return f"[{status}] {self.user_code}"


class ClientKey(models.Model):
    """
    Stores the cryptographic material and identity tokens for a CLI client.
    The primary key 'id' acts as the 32-bit unsigned Key ID in the UDP payload.
    """
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='client_keys')
    name = models.CharField(max_length=255, help_text="e.g., prod-db-server")
    
    # --- ACTIVE CREDENTIALS ---
    bearer_token = models.CharField(max_length=128, unique=True, db_index=True, default=generate_secure_token)
    aes_secret = models.CharField(max_length=64, default=generate_aes_secret)
    
    # --- PREVIOUS CREDENTIALS (For Fail-Safe Overlap) ---
    previous_bearer_token = models.CharField(max_length=128, null=True, blank=True, db_index=True)
    previous_aes_secret = models.CharField(max_length=64, null=True, blank=True)
    overlap_expires_at = models.BigIntegerField(null=True, blank=True)
    
    # --- METADATA ---
    created_at = models.BigIntegerField(default=current_epoch_int)
    expires_at = models.BigIntegerField(default=default_key_expiry)
    last_rotated_at = models.BigIntegerField(default=current_epoch_int)
    last_used_at = models.BigIntegerField(default=current_epoch_int)
    is_revoked = models.BooleanField(default=False)

    def rotate_keys(self, overlap_seconds=172800): # 48 hours default grace period
        """Generates new credentials while temporarily caching the old ones."""
        self.previous_bearer_token = self.bearer_token
        self.previous_aes_secret = self.aes_secret
        self.overlap_expires_at = current_epoch_int() + overlap_seconds
        
        self.bearer_token = generate_secure_token()
        self.aes_secret = generate_aes_secret()
        self.last_rotated_at = current_epoch_int()
        self.expires_at = default_key_expiry()
        self.save()

    def __str__(self):
        status = "REVOKED" if self.is_revoked else "ACTIVE"
        return f"[{status}] Key ID {self.pk} | {self.name}"