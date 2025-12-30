#!/usr/bin/env bash
set -euo pipefail

exec gunicorn --workers=2 --threads=4 --timeout=30 \
  --bind 0.0.0.0:8000 app:app
