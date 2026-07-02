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

    # Meta/WhatsApp API (Campos con defaults vacíos para entornos de CI/CD y Mypy)
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

    # ==========================================
    # Google Sheets (Fase 3 - Integración Física)
    # ==========================================
    GOOGLE_SHEETS_SPREADSHEET_ID: str = Field(default="")
    GOOGLE_APPLICATION_CREDENTIALS: str = Field(default="")


# Instanciación limpia y directa. Mypy --strict no chillará porque todos los campos
# tienen ahora un valor por defecto asignado mediante Field(), permitiendo que Pydantic
# los sobreescriba fluidamente en producción a partir del entorno real.
settings = Settings()
