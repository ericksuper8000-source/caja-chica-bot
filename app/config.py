from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Configuración estricta para leer el archivo .env automáticamente (Pydantic v2)
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,  # Busca exactamente en mayúsculas
        extra="ignore",  # Ignora variables extras del .env sin romper la app
    )

    # Variables de Entorno Generales
    PROJECT_NAME: str = "Caja Chica AI Bot"
    ENVIRONMENT: str = Field(default="local")

    # Meta/WhatsApp API (Requeridas con validación estricta)
    WHATSAPP_API_TOKEN: str
    WHATSAPP_VERIFY_TOKEN: str
    WHATSAPP_PHONE_NUMBER_ID: str

    # OpenAI API
    OPENAI_API_KEY: str

    # Celery & Redis
    REDIS_URL: str

    # Base de Datos Unificada
    DATABASE_URL: str

    # ==========================================
    # Google Sheets (Fase 3 - Integración Física)
    # ==========================================
    GOOGLE_SHEETS_SPREADSHEET_ID: str
    GOOGLE_APPLICATION_CREDENTIALS: str


# Instanciación limpia. Pydantic v2 cargará automáticamente los valores desde el .env.
# Pasamos valores vacíos por defecto solo si no se encuentran en el entorno (útil para inicializar Mypy)
settings = Settings()