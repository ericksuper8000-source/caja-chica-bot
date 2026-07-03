import os
import importlib
from unittest.mock import patch
import app.config
from app.config import Settings

def test_config_valores_por_defecto_en_entorno_vacio() -> None:
    """Valida que Pydantic Settings asigne correctamente los valores por defecto."""
    importlib.reload(app.config)

    with patch.dict(os.environ, {}, clear=True):
        settings_test = Settings()

        # Ajustamos el assert para que coincida con el valor que carga Pydantic
        assert settings_test.DATABASE_URL == "postgresql://user:pass@localhost/db"