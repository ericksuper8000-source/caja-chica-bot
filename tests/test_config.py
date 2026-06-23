import sys
from unittest.mock import patch
import pytest
from pydantic import ValidationError


def test_config_falla_si_faltan_variables_obligatorias() -> None:
    """Valida que Pydantic Settings lance un ValidationError si las

    credenciales críticas del sistema no se encuentran en el entorno.
    """
    # 1. Nos aseguramos de limpiar el caché del módulo por si ya se importó antes
    if "app.config" in sys.modules:
        del sys.modules["app.config"]

    # 2. Vaciamos el entorno del sistema completamente usando un patch controlado
    with patch.dict("os.environ", {}, clear=True):
        # 3. Ahora sí, le decimos a pytest que espere el fallo de validación de Pydantic
        with pytest.raises(ValidationError) as exc_info:
            from app.config import Settings

        # 4. Verificamos que contenga los errores de los campos críticos requeridos
        errors = str(exc_info.value)
        assert "WHATSAPP_VERIFY_TOKEN" in errors
        assert "WHATSAPP_API_TOKEN" in errors
        assert "WHATSAPP_PHONE_NUMBER_ID" in errors
        assert "DATABASE_URL" in errors
