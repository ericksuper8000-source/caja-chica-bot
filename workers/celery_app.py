import os
from celery import Celery

redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "caja_chica_workers",
    broker=redis_url,
    backend=redis_url,
)

celery_app.conf.update(
    task_track_started=True,
    task_time_limit=300,
)
