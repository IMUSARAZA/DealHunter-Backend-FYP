#!/bin/bash

# Activate virtual environment
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Check if Redis is running
if ! redis-cli ping > /dev/null 2>&1; then
    echo "Redis is not running. Starting Redis..."
    redis-server --daemonize yes
fi

# Start Celery worker
echo "Starting Celery worker..."
celery -A deal_hunter worker --loglevel=info --detach

# Start Celery beat
echo "Starting Celery beat..."
celery -A deal_hunter beat --loglevel=info --detach

# Start Django development server
echo "Starting Django development server..."
python manage.py runserver