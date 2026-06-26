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

## Database Setup

For pip-installed users, use `django-admin` with the settings module:

```bash
export DJANGO_SETTINGS_MODULE=hb_backend.settings

# Initialize the database
django-admin migrate

# Create an admin user
django-admin createsuperuser
```

By default, the database is stored at `./hbdb.sqlite3` in the current directory.
You can customize the database path with the `HEARTBEAT_DB_PATH` environment variable:

```bash
export HEARTBEAT_DB_PATH=/var/lib/hb-server/hbdb.sqlite3
django-admin migrate
```

For development from a git checkout:

```bash
cd src && python manage.py migrate
cd src && python manage.py createsuperuser
```

## Related projects

- `hb-client` (`hb_client`): heartbeat client library and CLI
- `hb-watcher` (`hb_watcher`): monitoring daemon

See [MIGRATION.md](MIGRATION.md) for upgrades from older package names.
