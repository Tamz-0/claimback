#!/usr/bin/env bash
# Render build script: install, collect static files, migrate, optional demo data.
set -o errexit

pip install --upgrade pip
pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate --no-input

# Categories, campus locations and role groups (safe to run every deploy)
python manage.py seed_demo --reference-only

# Demo users + sample items, only if SEED_DEMO=true (skips if items already exist)
if [ "${SEED_DEMO:-false}" = "true" ]; then
  python manage.py seed_demo
fi

# Create an admin account from DJANGO_SUPERUSER_USERNAME / _EMAIL / _PASSWORD if set
if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ]; then
  python manage.py createsuperuser --no-input || echo "Superuser already exists – skipping."
fi
