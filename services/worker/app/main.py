"""
Celery application configuration
"""

from celery import Celery

from gardener.common.utils import get_logger
from services.shared.config import settings

# Initialize logger
logger = get_logger("worker", verbose=settings.DEBUG)

# Create Celery app
app = Celery("gardener-worker")

# Configure Celery
app.conf.update(
    broker_url=settings.redis.REDIS_URL,
    result_backend=settings.redis.REDIS_URL,
    # Retry broker connection on startup to retain Celery 5.x behavior
    broker_connection_retry_on_startup=True,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Task execution settings
    task_soft_time_limit=settings.worker.MAX_ANALYSIS_DURATION,
    task_time_limit=settings.worker.MAX_ANALYSIS_DURATION + 300,  # Hard limit 5 min after soft
    task_acks_late=True,  # Tasks acknowledged after completion
    worker_prefetch_multiplier=1,  # One task at a time per worker
    # Result backend settings
    result_expires=86400,  # Results expire after 24 hours
    # Worker settings
    worker_max_tasks_per_child=10,  # Restart worker after 10 tasks (memory cleanup)
    worker_disable_rate_limits=True,
    # Beat schedule (for Phase 2 - scheduled tasks)
    beat_schedule={},
)

# Auto-discover tasks
app.autodiscover_tasks(["services.worker.app"])

# Import tasks to ensure they're registered
from services.worker.app import tasks  # noqa

# Log configuration
logger.info(f"Celery worker configured with broker: {settings.redis.REDIS_URL}")
logger.info(
    f"Task time limits - soft: {settings.worker.MAX_ANALYSIS_DURATION}s, "
    f"hard: {settings.worker.MAX_ANALYSIS_DURATION + 300}s"
)
