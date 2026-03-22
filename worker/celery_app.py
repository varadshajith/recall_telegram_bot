import os
import sys

# Add project root to Python path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from celery import Celery
from shared.config import settings

celery_app = Celery(
    "recall_worker",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["worker.tasks"]
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,  # 5 minutes
    result_expires=3600,  # 1 hour
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)
