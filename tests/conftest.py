import os
from unittest.mock import patch

import pytest


@pytest.fixture(scope="session", autouse=True)
def mock_env_vars():
    # Esto fuerza las variables que definimos en los archivos yml
    os.environ["DATABASE_URL"] = "postgresql://postgres:password@localhost:5432/caja_chica_db"
    os.environ["REDIS_URL"] = "redis://localhost:6379/0"
    os.environ["ENVIRONMENT"] = "test"
    os.environ["WHATSAPP_VERIFY_TOKEN"] = "test_verify_token_local"


class FakeRedisMemoria:
    """
    Redis en memoria para los tests. Existe por la misma razón que el mock de `settings`
    en la trampa J: los tests NO pueden depender de un servicio real ni escribir en el
    Redis del desarrollador. Con Redis real, el orden de los tests decidía el resultado
    (estado compartido) y la suite pasaba en local pero podía fallar en CI, que no tiene
    Redis. Lecciones de 8.6.3 aplicadas a 8.6.2.
    """

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)

    async def aclose(self) -> None:
        return None


@pytest.fixture(autouse=True)
def redis_aislado():
    """
    Ningún test habla con el Redis real (dedupe 8.6.2). Se parchea `redis.asyncio.from_url`
    —el punto de entrada que usan todos los importadores— para que el aislamiento sobreviva
    aunque un test reimporte `workers.tasks` (como hace `test_download_audio_task_exito`).
    Sin esto, el estado compartido de un Redis local decidía el resultado de la suite.
    """
    falso = FakeRedisMemoria()
    with patch("redis.asyncio.from_url", return_value=falso):
        yield falso


# Configuración de pytest-asyncio para evitar warnings
pytest_plugins: list[str] = []
