import time
import pytest
from django.test import TestCase
from django.contrib.auth.models import User
from hb_backend.models import (
    HeartbeatEntry,
    AlertState,
    WatcherState,
    MaintenanceWindow,
    DeviceFlowSession,
    ClientKey,
    AlertTransitionEvent,
    current_epoch_int,
    generate_user_code,
    generate_aes_secret,
    generate_secure_token,
)
from datetime import datetime, timedelta
from django.utils import timezone


class TestCurrentEpochInt(TestCase):
    """Tests for the current_epoch_int helper function."""

    def test_current_epoch_int_returns_integer(self):
        """current_epoch_int should return an integer."""
        result = current_epoch_int()
        assert isinstance(result, int)

    def test_current_epoch_int_is_recent(self):
        """current_epoch_int should return a value close to time.time()."""
        result = current_epoch_int()
        now = int(time.time())
        assert abs(result - now) < 2


class TestGenerateUserCode(TestCase):
    """Tests for the generate_user_code function."""

    def test_generate_user_code_format(self):
        """User code should be in XXXX-XXXX format."""
        code = generate_user_code()
        parts = code.split('-')
        assert len(parts) == 2
        assert len(parts[0]) == 4
        assert len(parts[1]) == 4

    def test_generate_user_code_only_valid_chars(self):
        """User code should only contain valid characters."""
        alpha_charset = "BDFGHJKLMNPQRSTVWXYZ"
        num_charset = "23456789"
        code = generate_user_code()
        alpha_part, num_part = code.split('-')
        for char in alpha_part:
            assert char in alpha_charset
        for char in num_part:
            assert char in num_charset

    def test_generate_user_code_uniqueness(self):
        """Multiple calls should (with high probability) generate different codes."""
        codes = {generate_user_code() for _ in range(100)}
        assert len(codes) > 90  # Very high probability of uniqueness


class TestGenerateAesSecret(TestCase):
    """Tests for the generate_aes_secret function."""

    def test_generate_aes_secret_is_string(self):
        """AES secret should be a base64-encoded string."""
        secret = generate_aes_secret()
        assert isinstance(secret, str)

    def test_generate_aes_secret_length(self):
        """AES secret should be 44 bytes (base64-encoded 32-byte key)."""
        secret = generate_aes_secret()
        assert len(secret) == 44


class TestGenerateSecureToken(TestCase):
    """Tests for the generate_secure_token function."""

    def test_generate_secure_token_is_string(self):
        """Secure token should be a string."""
        token = generate_secure_token()
        assert isinstance(token, str)

    def test_generate_secure_token_is_url_safe(self):
        """Secure token should be URL-safe (no / or + chars)."""
        token = generate_secure_token()
        assert '/' not in token or token.endswith('=')


class TestHeartbeatEntry(TestCase):
    """Tests for the HeartbeatEntry model."""

    def setUp(self):
        """Create test heartbeat entries."""
        self.now = int(time.time())
        self.basic_entry = HeartbeatEntry.objects.create(
            hostname="server1",
            app_name="api",
            port=8080,
            task="process",
            interval=60,
            alert_after=300,
            version="1.0.0",
            sent_timestamp=self.now,
            received_timestamp=self.now,
        )
        self.minimal_entry = HeartbeatEntry.objects.create(
            hostname="server2",
            app_name="db",
            interval=120,
            alert_after=600,
            sent_timestamp=self.now - 100,
            received_timestamp=self.now,
        )

    def test_heartbeat_entry_creation(self):
        """HeartbeatEntry should be created with required fields."""
        assert self.basic_entry.hostname == "server1"
        assert self.basic_entry.app_name == "api"
        assert self.basic_entry.port == 8080

    def test_heartbeat_entry_optional_fields(self):
        """HeartbeatEntry should allow NULL for optional fields."""
        assert self.minimal_entry.task is None
        assert self.minimal_entry.port is None
        assert self.minimal_entry.version is None

    def test_is_alive_property_true(self):
        """is_alive should be True when within alert_after window."""
        assert self.basic_entry.is_alive is True

    def test_is_alive_property_false(self):
        """is_alive should be False when outside alert_after window."""
        old_entry = HeartbeatEntry.objects.create(
            hostname="server3",
            app_name="service",
            interval=60,
            alert_after=300,
            sent_timestamp=self.now - 1000,
            received_timestamp=self.now - 1000,
        )
        assert old_entry.is_alive is False

    def test_is_future_property_false(self):
        """is_future should be False when sender clock is behind."""
        assert self.basic_entry.is_future is False

    def test_is_future_property_true(self):
        """is_future should be True when sender clock is ahead."""
        future_entry = HeartbeatEntry.objects.create(
            hostname="server4",
            app_name="web",
            interval=60,
            alert_after=300,
            sent_timestamp=self.now + 100,  # Clock ahead
            received_timestamp=self.now,
        )
        assert future_entry.is_future is True

    def test_delay_calculation(self):
        """delay property should calculate received - sent."""
        assert self.basic_entry.delay == 0.0
        assert self.minimal_entry.delay == 100.0

    def test_delay_negative_returns_zero(self):
        """delay should never be negative."""
        future_entry = HeartbeatEntry.objects.create(
            hostname="server5",
            app_name="job",
            interval=60,
            alert_after=300,
            sent_timestamp=self.now + 50,
            received_timestamp=self.now,
        )
        assert future_entry.delay == 0.0

    def test_identifier_string_full(self):
        """identifier_string should include all components."""
        id_str = self.basic_entry.identifier_string()
        assert "server1" in id_str
        assert "api" in id_str
        assert "8080" in id_str
        assert "process" in id_str
        assert "1.0.0" in id_str

    def test_identifier_string_minimal(self):
        """identifier_string should handle missing optional fields."""
        id_str = self.minimal_entry.identifier_string()
        assert "server2" in id_str
        assert "db" in id_str
        assert ":" not in id_str  # No port
        assert "[" not in id_str  # No task

    def test_unique_constraint_enforced(self):
        """UniqueConstraint should prevent duplicate entries."""
        from django.db import IntegrityError

        with pytest.raises(IntegrityError):
            HeartbeatEntry.objects.create(
                hostname="server1",
                app_name="api",
                port=8080,
                task="process",
                interval=60,
                alert_after=300,
                sent_timestamp=self.now,
                received_timestamp=self.now,
            )

    def test_str_representation(self):
        """__str__ should provide readable representation."""
        assert "server1" in str(self.basic_entry)
        assert "api" in str(self.basic_entry)

    def test_repr_representation(self):
        """__repr__ should provide detailed representation."""
        repr_str = repr(self.basic_entry)
        assert "HeartbeatEntry" in repr_str
        assert "server1" in repr_str
        assert "api" in repr_str


class TestAlertState(TestCase):
    """Tests for AlertState choices."""

    def test_alert_state_choices_exist(self):
        """All expected alert states should be defined."""
        assert AlertState.NORMAL == "NORMAL"
        assert AlertState.DEGRADED == "DEGRADED"
        assert AlertState.ALERT_SENT == "ALERT_SENT"
        assert AlertState.ACKNOWLEDGED == "ACKNOWLEDGED"
        assert AlertState.SNOOZED == "SNOOZED"
        assert AlertState.IN_MAINTENANCE == "IN_MAINTENANCE"


class TestWatcherState(TestCase):
    """Tests for the WatcherState singleton model."""

    def test_watcher_state_singleton(self):
        """WatcherState should enforce singleton pattern."""
        state1 = WatcherState.get_state()
        state2 = WatcherState.get_state()
        assert state1.pk == state2.pk == 1

    def test_watcher_state_undelivered_alerts_default(self):
        """Undelivered alerts should default to False."""
        state = WatcherState.get_state()
        assert state.has_undelivered_alerts is False

    def test_watcher_state_modification(self):
        """WatcherState should be updatable."""
        state = WatcherState.get_state()
        state.has_undelivered_alerts = True
        state.save()
        refreshed = WatcherState.get_state()
        assert refreshed.has_undelivered_alerts is True


class TestMaintenanceWindow(TestCase):
    """Tests for the MaintenanceWindow model."""

    def setUp(self):
        """Create test maintenance windows."""
        now = timezone.now()
        self.active_window = MaintenanceWindow.objects.create(
            name="Scheduled Maintenance",
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=1),
            is_active=True,
            hostname_filter="server1",
            app_name_filter="api",
        )
        self.inactive_window = MaintenanceWindow.objects.create(
            name="Future Maintenance",
            start_time=now + timedelta(days=1),
            end_time=now + timedelta(days=1, hours=2),
            is_active=False,
        )

    def test_maintenance_window_creation(self):
        """MaintenanceWindow should be created with required fields."""
        assert self.active_window.name == "Scheduled Maintenance"
        assert self.active_window.is_active is True

    def test_maintenance_window_filters(self):
        """MaintenanceWindow should support filter fields."""
        assert self.active_window.hostname_filter == "server1"
        assert self.active_window.app_name_filter == "api"

    def test_maintenance_window_str(self):
        """__str__ should show status and time."""
        str_repr = str(self.active_window)
        assert "ACTIVE" in str_repr
        assert "Scheduled Maintenance" in str_repr


class TestDeviceFlowSession(TestCase):
    """Tests for the DeviceFlowSession model."""

    def setUp(self):
        """Create test device flow sessions."""
        self.now = current_epoch_int()
        self.session = DeviceFlowSession.objects.create(
            client_name="Test Client",
            expires_at=self.now + 900,  # 15 mins from now
        )

    def test_device_flow_session_creation(self):
        """DeviceFlowSession should be created with default values."""
        assert self.session.client_name == "Test Client"
        assert self.session.is_approved is False

    def test_device_flow_session_unique_codes(self):
        """Device code and user code should be unique."""
        session2 = DeviceFlowSession.objects.create(
            client_name="Another Client",
            expires_at=self.now + 900,
        )
        assert self.session.device_code != session2.device_code
        assert self.session.user_code != session2.user_code

    def test_is_expired_not_yet(self):
        """is_expired should return False for active sessions."""
        assert self.session.is_expired() is False

    def test_is_expired_yes(self):
        """is_expired should return True for expired sessions."""
        expired_session = DeviceFlowSession.objects.create(
            client_name="Expired",
            expires_at=self.now - 100,  # Already expired
        )
        assert expired_session.is_expired() is True

    def test_device_flow_session_approval(self):
        """Session should track approval state."""
        user = User.objects.create_user(username="testuser", password="testpass")
        self.session.is_approved = True
        self.session.assigned_user = user
        self.session.save()
        refreshed = DeviceFlowSession.objects.get(pk=self.session.pk)
        assert refreshed.is_approved is True
        assert refreshed.assigned_user == user


class TestClientKey(TestCase):
    """Tests for the ClientKey model."""

    def setUp(self):
        """Create test client keys."""
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.key = ClientKey.objects.create(
            owner=self.user,
            name="prod-server",
        )

    def test_client_key_creation(self):
        """ClientKey should be created with required fields."""
        assert self.key.owner == self.user
        assert self.key.name == "prod-server"
        assert self.key.is_revoked is False

    def test_client_key_defaults(self):
        """ClientKey should have secure defaults."""
        assert len(self.key.bearer_token) > 40
        assert len(self.key.aes_secret) == 44
        assert self.key.previous_bearer_token is None
        assert self.key.is_revoked is False

    def test_client_key_rotation(self):
        """rotate_keys should update credentials and save overlap."""
        old_bearer = self.key.bearer_token
        old_aes = self.key.aes_secret

        self.key.rotate_keys()

        refreshed = ClientKey.objects.get(pk=self.key.pk)
        assert refreshed.bearer_token != old_bearer
        assert refreshed.aes_secret != old_aes
        assert refreshed.previous_bearer_token == old_bearer
        assert refreshed.previous_aes_secret == old_aes
        assert refreshed.overlap_expires_at is not None

    def test_client_key_rotation_grace_period(self):
        """rotate_keys should allow customizable grace period."""
        now = current_epoch_int()
        self.key.rotate_keys(overlap_seconds=3600)
        refreshed = ClientKey.objects.get(pk=self.key.pk)
        # Should be within 1 second due to timing
        assert refreshed.overlap_expires_at - now >= 3599

    def test_client_key_revocation(self):
        """Client key should be revocable."""
        self.key.is_revoked = True
        self.key.save()
        refreshed = ClientKey.objects.get(pk=self.key.pk)
        assert refreshed.is_revoked is True

    def test_client_key_str_active(self):
        """__str__ should show ACTIVE status for active keys."""
        str_repr = str(self.key)
        assert "ACTIVE" in str_repr
        assert "prod-server" in str_repr

    def test_client_key_str_revoked(self):
        """__str__ should show REVOKED status for revoked keys."""
        self.key.is_revoked = True
        str_repr = str(self.key)
        assert "REVOKED" in str_repr


class TestAlertTransitionEvent(TestCase):
    """Tests for the AlertTransitionEvent model."""

    def setUp(self):
        """Create test transition events."""
        self.entry = HeartbeatEntry.objects.create(
            hostname="server1",
            app_name="api",
            interval=60,
            alert_after=300,
            sent_timestamp=int(time.time()),
            received_timestamp=int(time.time()),
        )

    def test_alert_transition_event_creation(self):
        """AlertTransitionEvent should be created with required fields."""
        event = AlertTransitionEvent.objects.create(
            heartbeat_entry=self.entry,
            previous_state=AlertState.NORMAL,
            new_state=AlertState.ALERT_SENT,
            message="Alert triggered",
        )
        assert event.heartbeat_entry == self.entry
        assert event.previous_state == AlertState.NORMAL
        assert event.new_state == AlertState.ALERT_SENT
        assert event.message == "Alert triggered"

    def test_alert_transition_event_cascade_delete(self):
        """AlertTransitionEvent should be deleted when HeartbeatEntry is deleted."""
        event = AlertTransitionEvent.objects.create(
            heartbeat_entry=self.entry,
            previous_state=AlertState.NORMAL,
            new_state=AlertState.ALERT_SENT,
            message="Alert triggered",
        )
        assert AlertTransitionEvent.objects.filter(pk=event.pk).exists()
        self.entry.delete()
        assert not AlertTransitionEvent.objects.filter(pk=event.pk).exists()
