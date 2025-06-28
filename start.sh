#!/bin/bash
nginx -g 'daemon off;' &

exec gunicorn --timeout 60 --workers 2 -b 0.0.0.0:8000 setup.wsgi:application
