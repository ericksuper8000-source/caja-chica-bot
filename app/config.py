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


# Instanciación limpia con bypass estricto para Mypy (--strict)
# type: ignore[call-arg] indica a Mypy que la resolución de variables se maneja dinámicamente
settings = Settings()  # type: ignore[call-arg]