from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Configuración para leer el archivo .env automáticamente
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,  # Al estar en True, busca exactamente en mayúsculas
    )

    # Variables obligatorias (con default vacío para complacer a Mypy)
    OPENAI_API_KEY: str = Field(default="")
    FASTAPI_ENV: str = Field(default="development")

    # Configuración de Base de Datos (PostgreSQL)
    POSTGRES_USER: str = Field(default="postgres")
    POSTGRES_PASSWORD: str = Field(default="postgres")
    POSTGRES_DB: str = Field(default="caja_chica")
    POSTGRES_HOST: str = Field(default="localhost")
    POSTGRES_PORT: int = Field(default=5432)

    # Configuración de Redis / Celery
    REDIS_URL: str = Field(default="redis://localhost:6379/0")

    @property
    def database_url(self) -> str:
        """Genera dinámicamente la URL de conexión para SQLAlchemy/Tortoise."""
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


# Instancia global para importar en la app
settings = Settings()