from django.apps import AppConfig


class HeartbeatBackendConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hb_backend"
    label = "heartbeat_backend"
