import os
from unittest.mock import patch
from app.config import Settings


def test_config_valores_por_defecto_en_entorno_vacio() -> None:
    """Valida los valores por defecto ignorando cualquier archivo .env real."""

    # Limpiamos las variables de entorno actuales y forzamos a ignorar el .env
    with patch.dict(os.environ, {}, clear=True):
        # Al pasar _env_file=None, Pydantic no intenta cargar el archivo .env
        settings_test = Settings(_env_file=None)

        assert settings_test.WHATSAPP_API_TOKEN == ""
        assert settings_test.WHATSAPP_VERIFY_TOKEN == ""
        assert settings_test.OPENAI_API_KEY == ""
