import os
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

from celery import Celery
from app.config import settings

celery_app = Celery(
    "etair",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=50,
    task_routes={
        "app.workers.tasks.process_file_task": {"queue": "file_processing"},
        "app.workers.tasks.compute_similarity_task": {"queue": "file_processing"},
    },
    beat_schedule={
        "nightly-similarity-update": {
            "task": "app.workers.tasks.compute_similarity_task",
            "schedule": 3600 * 6,  # every 6 hours
        }
    },
)
