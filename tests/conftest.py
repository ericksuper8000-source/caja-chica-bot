import pytest
import os


@pytest.fixture(scope="session", autouse=True)
def mock_env_vars():
    # Esto fuerza las variables que definimos en los archivos yml
    os.environ["DATABASE_URL"] = (
        "postgresql://postgres:password@localhost:5432/caja_chica_db"
    )
    os.environ["REDIS_URL"] = "redis://localhost:6379/0"
    os.environ["ENVIRONMENT"] = "test"
