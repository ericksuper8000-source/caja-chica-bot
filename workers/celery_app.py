import os
from celery import Celery

# Obtenemos la URL de Redis desde el entorno o usamos la local por defecto
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "caja_chica_workers",
    broker=REDIS_URL,
    backend=REDIS_URL
)

# Configuración básica de Celery
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="America/Costa_Rica",
    enable_utc=True,
)

@celery_app.task(name="ping_task")
def ping_task():
    return "pong"