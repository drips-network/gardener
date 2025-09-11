"""
Celery client for API service
"""

from celery import Celery

from gardener.common.utils import get_logger
from services.shared.config import settings

logger = get_logger(__name__)


def create_celery_client():
    """
    Create a Celery client for sending tasks

    This is used by the API service to queue tasks for the worker

    It's configured to only send tasks, not consume them
    """
    celery_client = Celery(
        "gardener-api-client",
        broker=settings.redis.REDIS_URL,
        backend=settings.redis.REDIS_URL,
        include=["services.worker.app.tasks"],
    )

    # Configure client-only settings
    celery_client.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
        task_time_limit=settings.worker.MAX_ANALYSIS_DURATION,
        task_soft_time_limit=settings.worker.MAX_ANALYSIS_DURATION,
        worker_disable_rate_limits=True,
        # Client-only: don't consume tasks
        worker_hijack_root_logger=False,
        task_routes={
            "analyze_repo_task": {"queue": "celery"},
        },
    )

    logger.info(f"Celery client configured with broker: {settings.redis.REDIS_URL}")
    return celery_client


# Global client instance
celery_client = create_celery_client()
