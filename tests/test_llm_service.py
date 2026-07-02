import pytest
from app.services.llm_service import llm_service
from app.config import settings


@pytest.mark.asyncio
async def test_llm_service_initialization():
    """Valida que el servicio lea correctamente la API Key desde settings"""
    # Verificamos que tenga una configuración cargada
    assert llm_service.api_key is not None


def test_config_loaded():
    """Valida que settings esté cargando el entorno actual"""
    # Aceptamos tanto 'local' como 'test' según como esté corriendo el contenedor
    assert settings.ENVIRONMENT in ["test", "local"]
