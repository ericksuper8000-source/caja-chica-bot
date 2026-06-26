from typing import Any
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Configuración para leer el archivo .env automáticamente
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,  # Busca exactamente en mayúsculas
        extra="ignore",  # Ignora variables extras del .env sin romper la app
    )

    # Variables estrictamente obligatorias
    OPENAI_API_KEY: str
    FASTAPI_ENV: str = Field(default="development")

    # Configuración de Base de Datos (PostgreSQL)
    POSTGRES_USER: str = Field(default="postgres")
    POSTGRES_PASSWORD: str = Field(default="postgres")
    POSTGRES_DB: str = Field(default="caja_chica")
    POSTGRES_HOST: str = Field(default="localhost")
    POSTGRES_PORT: int = Field(default=5432)

    # Configuración de Redis / Celery
    REDIS_URL: str = Field(default="redis://localhost:6379/0")

    # Variables requeridas por los módulos de WhatsApp y Google Sheets
    WHATSAPP_API_TOKEN: str = Field(default="mock_token")
    WHATSAPP_VERIFY_TOKEN: str = Field(default="mock_verify")
    WHATSAPP_PHONE_NUMBER_ID: str = Field(default="mock_id")
    GOOGLE_SHEETS_SPREADSHEET_ID: str = Field(default="mock_spreadsheet_id")
    google_sheets_credentials_dict: dict[str, Any] = Field(default_factory=dict)

    @property
    def database_url(self) -> str:
        """Genera dinámicamente la URL de conexión para SQLAlchemy/Tortoise."""
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


# Instanciación compatible con Mypy
settings = Settings(OPENAI_API_KEY="")
