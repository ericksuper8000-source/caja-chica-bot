import os
import pytest


@pytest.fixture(scope="session", autouse=True)
def mock_env_vars():
    # Esto fuerza las variables que definimos en los archivos yml
    os.environ["DATABASE_URL"] = (
        "postgresql://postgres:password@localhost:5432/caja_chica_db"
    )
    os.environ["REDIS_URL"] = "redis://localhost:6379/0"
    os.environ["ENVIRONMENT"] = "test"
    os.environ["WHATSAPP_VERIFY_TOKEN"] = "mi_token_secreto_tico_123"


# Configuración de pytest-asyncio para evitar warnings
pytest_plugins: list[str] = []
