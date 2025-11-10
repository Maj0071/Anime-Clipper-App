from celery import Celery
import os

# Redis URL for broker and result backend
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

# Create Celery app
celery_app = Celery(
    "anime_clipper",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        'app.workers.analyzer',
        'app.workers.renderer'
    ]
)

# Celery configuration
celery_app.conf.update(
    # Task settings
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    
    # Task routing
    task_routes={
        'app.workers.analyzer.*': {'queue': 'analysis'},
        'app.workers.renderer.*': {'queue': 'rendering'}
    },
    
    # Task execution settings
    task_track_started=True,
    task_time_limit=3900,  # 65 minutes hard limit
    task_soft_time_limit=3600,  # 60 minutes soft limit
    worker_prefetch_multiplier=1,  # Don't prefetch tasks
    worker_max_tasks_per_child=50,  # Restart worker after N tasks
    
    # Result backend settings
    result_expires=86400,  # Results expire after 24 hours
    result_backend_transport_options={
        'master_name': 'mymaster'
    },
    
    # Broker settings
    broker_connection_retry_on_startup=True,
    broker_connection_retry=True,
    broker_connection_max_retries=10,
    
    # Performance settings
    worker_disable_rate_limits=True,
    task_compression='gzip',
    result_compression='gzip',
    
    # Monitoring
    worker_send_task_events=True,
    task_send_sent_event=True,
)

# Task priority levels
celery_app.conf.task_default_priority = 5
celery_app.conf.broker_transport_options = {
    'priority_steps': list(range(10)),
    'sep': ':',
    'queue_order_strategy': 'priority'
}

if __name__ == '__main__':
    celery_app.start()