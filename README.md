# hb-server

Heartbeat server backend (`hb_backend`).

## Installation

```bash
pip install hb-server
```

This installs:

- the Python package `hb_backend`
- the CLI command `hbserver`

## Running

```bash
hbserver --port 8333
# or
python3 -m hb_backend.hbserver --port 8333
```

Django admin:

```bash
cd src && python manage.py migrate
cd src && python manage.py createsuperuser
```

## Related projects

- `hb-client` (`hb_client`): heartbeat client library and CLI
- `hb-watcher` (`hb_watcher`): monitoring daemon

See [MIGRATION.md](MIGRATION.md) for upgrades from older package names.
