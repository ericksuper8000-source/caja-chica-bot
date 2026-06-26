from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Variables obligatorias: Le ponemos un default vacío para que Mypy no chille al instanciar,
    # pero Pydantic exigirá que esté en el .env si dejamos el string vacío o validamos después.
    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    fastapi_env: str = Field(default="development", validation_alias="FASTAPI_ENV")

    # Variables con defaults claros
    postgres_user: str = Field(default="postgres", validation_alias="POSTGRES_USER")
    postgres_password: str = Field(
        default="postgres", validation_alias="POSTGRES_PASSWORD"
    )
    postgres_db: str = Field(default="caja_chica", validation_alias="POSTGRES_DB")
    postgres_host: str = Field(default="localhost", validation_alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, validation_alias="POSTGRES_PORT")

    redis_url: str = Field(
        default="redis://localhost:6379/0", validation_alias="REDIS_URL"
    )

    @property
    def database_url(self) -> str:
        """Genera dinámicamente la URL de conexión para SQLAlchemy/Tortoise."""
        return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"


# Instancia global para importar en la app
settings = Settings()
