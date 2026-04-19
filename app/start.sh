#!/usr/bin/env bash
set -euo pipefail

exec gunicorn -c gunicorn.conf.py server:app
