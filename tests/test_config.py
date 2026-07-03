import os
import importlib
from unittest.mock import patch
import app.config  # Importamos el módulo base
from app.config import Settings


def test_config_valores_por_defecto_en_entorno_vacio() -> None:
    """Valida que Pydantic Settings asigne correctamente los marcadores de posición
    por defecto si las variables críticas no se encuentran en el entorno,
    evitando caídas catastróficas en linters y entornos de CI.
    """
    # Forzamos la recarga del módulo para limpiar cualquier configuración cacheada en memoria
    importlib.reload(app.config)

    # Forzamos un entorno completamente limpio de variables de sistema
    with patch.dict(os.environ, {}, clear=True):
        settings_test = Settings()

        # Validamos que se usen las cadenas vacías de resguardo
        assert settings_test.DATABASE_URL == ""
