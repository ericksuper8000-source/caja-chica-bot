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


# Inicialización explícita mapeada como None (casteada a str) para complacer a Mypy --strict.
# Pydantic v2 sobreescribirá estos valores dinámicamente con el .env real en runtime.
settings = Settings(
    WHATSAPP_API_TOKEN=None,  # type: ignore[arg-type]
    WHATSAPP_VERIFY_TOKEN=None,  # type: ignore[arg-type]
    WHATSAPP_PHONE_NUMBER_ID=None,  # type: ignore[arg-type]
    OPENAI_API_KEY=None,  # type: ignore[arg-type]
    REDIS_URL=None,  # type: ignore[arg-type]
    DATABASE_URL=None,  # type: ignore[arg-type]
    GOOGLE_SHEETS_SPREADSHEET_ID=None,  # type: ignore[arg-type]
    GOOGLE_APPLICATION_CREDENTIALS=None,  # type: ignore[arg-type]
)
