import pytest
import os
import sys
from unittest.mock import patch
from pydantic import ValidationError


def test_config_falla_si_faltan_variables_obligatorias() -> None:
    """Valida que Pydantic Settings lance un ValidationError si las
    credenciales críticas del sistema no se encuentran en el entorno.
    """
    from app.config import Settings

    if "app.config" in sys.modules:
        del sys.modules["app.config"]

    # Forzamos la limpieza absoluta del entorno del sistema
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ValidationError):
            # Forzamos a Pydantic a ignorar el archivo físico del disco local
            Settings(_env_file=None)
