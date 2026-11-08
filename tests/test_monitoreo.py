"""
Tests del monitoreo de salud (Paso 1 de operación).

Cubren la decisión alertar/recuperar, la consulta HTTP y la tarea del worker con
Redis y WhatsApp simulados: una sola alerta por caída y un aviso al recuperarse.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.monitoreo_service import (
    TEXTO_RECUPERACION,
    consultar_salud,
    decidir_accion,
    formatear_mensaje_monitoreo,
)
from workers import tasks


class _FakeRedis:
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


def test_decidir_accion_solo_alerta_en_la_transicion() -> None:
    assert decidir_accion(None, False) == "alertar"
    assert decidir_accion("ok", False) == "alertar"
    assert decidir_accion("caido", False) == "nada"
    assert decidir_accion("caido", True) == "recuperar"
    assert decidir_accion("ok", True) == "nada"
    assert decidir_accion(None, True) == "nada"


def test_formatear_mensaje_de_caida_y_recuperacion() -> None:
    caida = formatear_mensaje_monitoreo("alertar", {"status_code": 503, "detalle": "redis=error"})
    recuperacion = formatear_mensaje_monitoreo("recuperar", {"ok": True})

    assert "ALERTA" in caida
    assert "503" in caida
    assert "redis=error" in caida
    assert recuperacion == TEXTO_RECUPERACION


@pytest.mark.anyio
async def test_consultar_salud_ok() -> None:
    respuesta = MagicMock()
    respuesta.status_code = 200
    respuesta.text = '{"status":"healthy"}'

    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=respuesta)):
        resultado = await consultar_salud("http://app:8000/health")

    assert resultado["ok"] is True
    assert resultado["status_code"] == 200


@pytest.mark.anyio
async def test_consultar_salud_degradada_y_error_de_red() -> None:
    respuesta = MagicMock()
    respuesta.status_code = 503
    respuesta.text = "degraded"

    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=respuesta)):
        degradada = await consultar_salud("http://app:8000/health")

    with patch("httpx.AsyncClient.get", new=AsyncMock(side_effect=RuntimeError("sin red"))):
        error = await consultar_salud("http://app:8000/health")

    assert degradada["ok"] is False
    assert degradada["status_code"] == 503
    assert error["ok"] is False
    assert error["detalle"] == "RuntimeError"


@pytest.mark.anyio
async def test_verificar_salud_alerta_una_vez_y_avisa_recuperacion() -> None:
    redis_falso = _FakeRedis()
    salud = [
        {"ok": False, "status_code": 503, "detalle": "redis=error"},
        {"ok": False, "status_code": 503, "detalle": "redis=error"},
        {"ok": True, "status_code": 200, "detalle": "healthy"},
    ]

    with (
        patch("workers.tasks._dedupe_redis", new=AsyncMock(return_value=redis_falso)),
        patch("workers.tasks.consultar_salud", new=AsyncMock(side_effect=salud)),
        patch("workers.tasks.enviar_mensaje_whatsapp", new=AsyncMock()) as whatsapp,
        patch.object(tasks.settings, "ADMIN_PHONE", "50688888888"),
    ):
        primera = await tasks._verificar_salud()
        segunda = await tasks._verificar_salud()
        tercera = await tasks._verificar_salud()

    assert primera["accion"] == "alertar"
    assert segunda["accion"] == "nada"
    assert tercera["accion"] == "recuperar"
    assert whatsapp.await_count == 2
    assert "ALERTA" in whatsapp.call_args_list[0].kwargs["mensaje"]
    assert whatsapp.call_args_list[1].kwargs["mensaje"] == TEXTO_RECUPERACION
    assert redis_falso.store["monitor:salud:estado"] == "ok"


@pytest.mark.anyio
async def test_verificar_salud_sin_admin_no_envia_pero_guarda_estado() -> None:
    redis_falso = _FakeRedis()

    with (
        patch("workers.tasks._dedupe_redis", new=AsyncMock(return_value=redis_falso)),
        patch(
            "workers.tasks.consultar_salud",
            new=AsyncMock(return_value={"ok": False, "status_code": None, "detalle": "timeout"}),
        ),
        patch("workers.tasks.enviar_mensaje_whatsapp", new=AsyncMock()) as whatsapp,
        patch.object(tasks.settings, "ADMIN_PHONE", ""),
    ):
        resultado = await tasks._verificar_salud()

    assert resultado["accion"] == "alertar"
    whatsapp.assert_not_awaited()
    assert redis_falso.store["monitor:salud:estado"] == "caido"
