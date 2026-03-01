#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

echo "=== Running Django Migrations ==="
# HEARTBEAT_DB_PATH=/data/hbdb.sqlite3
python manage.py migrate

echo "=== Starting Heartbeat Server ==="
# exec replaces the shell process with your python process,
# allowing systemd/podman to properly send SIGTERM signals to it.
exec "$@"
