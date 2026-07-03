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


# Instanciación
settings = Settings()
