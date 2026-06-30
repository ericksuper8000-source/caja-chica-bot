from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Configuración estricta para leer el archivo .env automáticamente
    model_config = SettingsConfigDict(
        env_file=".env",
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


# Esta instancia es la que usará tu aplicación.
settings = Settings()
