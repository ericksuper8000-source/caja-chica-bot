import os
from typing import ClassVar

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Ya no forzamos una lógica compleja aquí.
    # Dejamos env_file en None por defecto para máxima seguridad en tests.
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=os.getenv("ENV_FILE", None),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Variables de Entorno Generales
    PROJECT_NAME: str = "Caja Chica AI Bot"
    ENVIRONMENT: str = Field(default="local")

    # Meta/WhatsApp API
    WHATSAPP_API_TOKEN: str = Field(default="")
    WHATSAPP_VERIFY_TOKEN: str = Field(default="")
    WHATSAPP_APP_SECRET: str = Field(default="")
    WHATSAPP_PHONE_NUMBER_ID: str = Field(default="")

    # OpenAI API
    OPENAI_API_KEY: str = Field(default="")

    # Celery & Redis
    REDIS_URL: str = Field(default="redis://localhost:6379/0")

    # Base de Datos Unificada
    DATABASE_URL: str = Field(default="postgresql://user:pass@localhost/db")

    # Google Sheets
    GOOGLE_SHEETS_SPREADSHEET_ID: str = Field(default="")
    GOOGLE_APPLICATION_CREDENTIALS: str = Field(default="")

    # Fase 6.5.5 — Backups del sheet (ADR-0014): copia local diaria del spreadsheet
    # completo (una CSV por pestaña + manifest, empaquetado en .zip). Retención en días:
    # se purgan los backups más viejos que ese límite. BACKUP_DIR es la ruta DENTRO del
    # contenedor; docker-compose la monta como volumen con nombre (backups_data) para que
    # sobreviva a recreaciones.
    BACKUP_DIR: str = Field(default="/backups")
    BACKUP_RETENTION_DAYS: int = Field(default=90)
    # Horario UTC del backup diario (Celery beat); hora por defecto 23:00 UTC.
    BACKUP_CRON_HOUR: int = Field(default=23)
    BACKUP_CRON_MINUTE: int = Field(default=0)

    # Operación (Paso 1): alertas de salud por WhatsApp.
    # ADMIN_PHONE recibe la alerta si /health deja de responder (formato 506...).
    ADMIN_PHONE: str = Field(default="")
    HEALTHCHECK_URL: str = Field(default="http://app:8000/health")
    # Seguridad #10: máximo de mensajes por teléfono por minuto (0 desactiva el control).
    RATE_LIMIT_MENSAJES_POR_MINUTO: int = Field(default=20)

    # Paso 4 Sprint — resumen semanal automático (Celery beat, hora de Costa Rica).
    # Por defecto: lunes 08:00 CR (fuera del horario de silencio 22:00–07:00).
    RESUMEN_SEMANAL_CRON_DAY_OF_WEEK: int = Field(default=1)
    RESUMEN_SEMANAL_CRON_HOUR: int = Field(default=8)
    RESUMEN_SEMANAL_CRON_MINUTE: int = Field(default=0)


# Instanciación
settings = Settings()
