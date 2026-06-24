from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Administrador centralizado de variables de entorno del proyecto.

    Utiliza Pydantic para validar la presencia y el tipo correcto de cada
    credencial obligatoria cargada desde el archivo local .env.
    """

    # Configuración del servidor FastAPI
    PROJECT_NAME: str = "Caja Chica AI Bot"
    ENVIRONMENT: str = "development"

    # Credenciales de WhatsApp Cloud API (Meta)
    WHATSAPP_VERIFY_TOKEN: str
    WHATSAPP_API_TOKEN: str
    WHATSAPP_PHONE_NUMBER_ID: str

    # Credenciales de Inteligencia Artificial
    OPENAI_API_KEY: str

    # Configuración de Infraestructura de Datos y Mensajería
    DATABASE_URL: str
    REDIS_URL: str = "redis://redis:6379/0"

    # Configuración interna de Pydantic Settings para apuntar al archivo .env
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


# Instancia global para ser importada en toda la aplicación
settings = Settings()  # type: ignore[call-arg]
