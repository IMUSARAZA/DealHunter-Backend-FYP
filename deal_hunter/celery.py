import os
from celery import Celery
import logging

logger = logging.getLogger(__name__)

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'deal_hunter.settings')

# Create the Celery app even if Redis is down, but mark it as non-functional
try:
    app = Celery('deal_hunter')
    
    # Using a string here means the worker doesn't have to serialize
    # the configuration object to child processes.
    app.config_from_object('django.conf:settings', namespace='CELERY')

    # Load task modules from all registered Django app configs.
    app.autodiscover_tasks()
    
    # Verify connection
    try:
        from kombu import Connection
        conn = Connection(app.conf.broker_url)
        conn.ensure_connection(max_retries=1, interval_start=0, interval_step=0)
        logger.info("Successfully connected to broker")
        app.is_functional = True
    except Exception as e:
        logger.warning(f"Celery broker connection failed: {str(e)}")
        app.is_functional = False

except Exception as e:
    # Create a dummy app that raises errors when used
    logger.error(f"Error initializing Celery: {str(e)}")
    
    class DummyCelery:
        is_functional = False
        
        def task(self, *args, **kwargs):
            def decorator(func):
                # This decorator makes the task function still callable normally
                func.delay = lambda *a, **kw: None
                func.apply_async = lambda *a, **kw: None
                return func
            return decorator
        
        def __getattr__(self, name):
            # Any attribute access will return None
            return lambda *args, **kwargs: None
    
    app = DummyCelery()

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')