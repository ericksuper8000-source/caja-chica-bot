from celery import Celery
from celery.schedules import crontab

from app.config import settings

# Inicializamos la aplicación de Celery asignándole un nombre identificable
celery_app = Celery(
    "caja_chica_workers",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

# Configuración de optimización para el manejo de tareas distribuidas
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="America/Costa_Rica",
    enable_utc=True,
    # Asegura que el worker no se quede con tareas atrapadas si se cae un proceso
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
)

# Fase 6.5.5 — Backup diario del sheet (ADR-0014): horario configurable por env
# (BACKUP_CRON_HOUR/MINUTE, UTC). Lo ejecuta el worker; el servicio `beat` del compose
# solo publica el evento periódico.
celery_app.conf.beat_schedule = {
    "backup-diario-sheet": {
        "task": "workers.tasks.crear_backup_task",
        "schedule": crontab(
            minute=settings.BACKUP_CRON_MINUTE,
            hour=settings.BACKUP_CRON_HOUR,
        ),
    },
}

# Definimos los módulos donde Celery buscará las tareas asíncronas automáticamente
celery_app.autodiscover_tasks(["workers"])
