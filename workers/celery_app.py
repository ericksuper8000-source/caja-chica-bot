from celery import Celery  # type: ignore
from app.config import settings

# Inicializamos la aplicación de Celery asignándole un nombre identificable
celery_app: Celery = Celery(
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
    worker_prefetch_multiplier=1,
)

# Definimos los módulos donde Celery buscará las tareas asíncronas automáticamente
celery_app.autodiscover_tasks(["workers"])