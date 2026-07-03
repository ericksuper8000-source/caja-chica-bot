import os
import sys
from unittest.mock import patch
from app.config import Settings


def test_config_valores_por_defecto_en_entorno_vacio() -> None:
    """Valida que Pydantic Settings asigne correctamente los marcadores de posición
    por defecto si las variables críticas no se encuentran en el entorno,
    evitando caídas catastróficas en linters y entornos de CI.
    """
    if "app.config" in sys.modules:
        del sys.modules["app.config"]

    # Forzamos un entorno completamente limpio de variables de sistema
    with patch.dict(os.environ, {}, clear=True):
        settings_test = Settings()

        # Validamos que se usen las cadenas vacías de resguardo
        assert settings_test.WHATSAPP_API_TOKEN == ""
        assert settings_test.WHATSAPP_VERIFY_TOKEN == ""
        assert settings_test.OPENAI_API_KEY == ""
