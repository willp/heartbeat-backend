#!/bin/bash
python manage.py makemigrations heartbeat_backend && python manage.py migrate
