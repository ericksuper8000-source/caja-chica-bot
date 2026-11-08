"""
Tests del límite de mensajes por teléfono (Seguridad #10 / P2-1).

El límite se aplica en el pipeline con Redis: 20 mensajes/minuto por teléfono por
defecto. Si Redis falla, se permite el mensaje (no se bloquea al cliente legítimo).
"""

from unittest.mock import AsyncMock, patch

import pytest

from services.rate_limit_service import clave_rate_limit, permitir_mensaje
from workers.tasks import TEXTO_RATE_LIMIT, procesar_mensaje_texto_task

TELEFONO = "50688888888"


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def incr(self, key: str) -> int:
        valor = int(self.store.get(key, "0")) + 1
        self.store[key] = str(valor)
        return valor

    async def expire(self, key: str, seconds: int) -> bool:
        return key in self.store


@pytest.mark.anyio
async def test_limite_permite_hasta_el_limite_y_bloquea_despues() -> None:
    fake = _FakeRedis()

    assert await permitir_mensaje(fake, TELEFONO, limite=2) is True
    assert await permitir_mensaje(fake, TELEFONO, limite=2) is True
    assert await permitir_mensaje(fake, TELEFONO, limite=2) is False
    assert fake.store[clave_rate_limit(TELEFONO)] == "3"


@pytest.mark.anyio
async def test_limite_cero_desactiva_el_control() -> None:
    fake = _FakeRedis()

    assert await permitir_mensaje(fake, TELEFONO, limite=0) is True
    assert fake.store == {}


@pytest.mark.anyio
async def test_error_de_redis_permite_el_mensaje() -> None:
    class _RedisRoto:
        async def incr(self, key: str) -> int:
            raise RuntimeError("sin redis")

    assert await permitir_mensaje(_RedisRoto(), TELEFONO, limite=2) is True


def test_pipeline_corta_y_avisa_si_se_supera_el_limite() -> None:
    with (
        patch("workers.tasks._rate_limit_ok", new=AsyncMock(return_value=False)),
        patch("workers.tasks.enviar_mensaje_whatsapp", new=AsyncMock()) as whatsapp,
    ):
        procesar_mensaje_texto_task(TELEFONO, "hola")

    whatsapp.assert_awaited_once_with(
        to_phone=TELEFONO,
        mensaje=TEXTO_RATE_LIMIT,
    )
