#!/bin/sh
set -e

if [ -n "$POSTGRES_HOST" ]; then
    echo "Waiting for database..."
    until python -c "
import os, psycopg2
try:
    psycopg2.connect(
        host=os.environ['POSTGRES_HOST'],
        port=os.environ.get('POSTGRES_PORT', '5432'),
        dbname=os.environ['POSTGRES_DB'],
        user=os.environ['POSTGRES_USER'],
        password=os.environ['POSTGRES_PASSWORD'],
    )
    print('Database ready.')
    exit(0)
except Exception as e:
    print(f'Not ready: {e}')
    exit(1)
"; do
        sleep 2
    done
fi

echo "Running migrations..."
python manage.py migrate --noinput

# Only collect static for the web process
case "$*" in
  *daphne*)
    echo "Collecting static files..."
    python manage.py collectstatic --noinput --clear
    ;;
esac

exec "$@"
