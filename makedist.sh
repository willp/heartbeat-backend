#!/bin/bash
set -e
if [ -d tests ]; then
    echo "Running tests..."
    export DJANGO_SETTINGS_MODULE=hb_backend.settings
    python3 src/manage.py test tests -v 2 || { echo "Tests failed!"; exit 1; }
fi
echo "Building distribution..."
python3 -m build
