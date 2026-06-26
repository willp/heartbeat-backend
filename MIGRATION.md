# Migration: hb-server naming

## PyPI and CLI

| Before | After |
|--------|-------|
| `heartbeat-backend` / `nhbserver` (PyPI) | `hb-server` |
| `python3 -m heartbeat_backend.hbserver` / `nhbserver` | `hbserver` |

## Python imports

```python
from hb_backend.models import HeartbeatEntry
```

## Django

- `DJANGO_SETTINGS_MODULE`: `hb_backend.settings`
- `INSTALLED_APPS`: `hb_backend.apps.HeartbeatBackendConfig`
- App label in migrations/DB: still `heartbeat_backend` (no database migration required)

## Cross-project names

| Role | pip install | CLI | Python import |
|------|-------------|-----|---------------|
| Client | `hb-client` | `hbclient` | `hb_client` |
| Server | `hb-server` | `hbserver` | `hb_backend` |
| Watcher | `hb-watcher` | `hbwatcher` | `hb_watcher` |
