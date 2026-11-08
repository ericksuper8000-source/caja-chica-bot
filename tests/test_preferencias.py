from datetime import datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

from services.preferencias_service import (
    TEXTO_ACTIVAR_CONFIRMADO,
    TEXTO_STOP_CONFIRMADO,
    ZONA_CR,
    detectar_activar_preferencias,
    detectar_stop_preferencias,
    en_horario_silencio,
    guardar_preferencia_automaticos,
    resumen_semanal_habilitado,
)


@pytest.mark.parametrize(
    "texto",
    ["STOP", "stop", "Stop.", "stop mensajes", "no me mandes mensajes", "no me escribas más"],
)
def test_detectar_stop_variantes(texto: str) -> None:
    assert detectar_stop_preferencias(texto) is True


@pytest.mark.parametrize(
    "texto",
    ["activar", "ACTIVAR MENSAJES", "activá mensajes", "quiero mis mensajes", "reanudar mensajes"],
)
def test_detectar_activar_variantes(texto: str) -> None:
    assert detectar_activar_preferencias(texto) is True


@pytest.mark.parametrize(
    "texto",
    ["gasté 5000 en transporte", "presupuesto stop 1000", "hola", ""],
)
def test_no_confunde_comandos_con_transacciones(texto: str) -> None:
    assert detectar_stop_preferencias(texto) is False
    assert detectar_activar_preferencias(texto) is False


def test_horario_silencio_bordes() -> None:
    assert en_horario_silencio(datetime(2026, 11, 7, 21, 59, tzinfo=ZONA_CR)) is False
    assert en_horario_silencio(datetime(2026, 11, 7, 22, 0, tzinfo=ZONA_CR)) is True
    assert en_horario_silencio(datetime(2026, 11, 7, 23, 30, tzinfo=ZONA_CR)) is True
    assert en_horario_silencio(datetime(2026, 11, 8, 6, 59, tzinfo=ZONA_CR)) is True
    assert en_horario_silencio(datetime(2026, 11, 8, 7, 0, tzinfo=ZONA_CR)) is False
    assert en_horario_silencio(datetime(2026, 11, 8, 18, 0, tzinfo=ZoneInfo("UTC"))) is False


@pytest.mark.anyio
async def test_resumen_habilitado_delega_en_sheets() -> None:
    with patch(
        "services.preferencias_service.leer_preferencia_resumen",
        new=AsyncMock(side_effect=[True, False]),
    ) as mock_leer:
        assert await resumen_semanal_habilitado("50670000000") is True
        assert await resumen_semanal_habilitado("50670000000") is False

    assert mock_leer.await_count == 2


@pytest.mark.anyio
async def test_guardar_preferencia_delega_en_sheets() -> None:
    with patch(
        "services.preferencias_service.guardar_preferencia_resumen",
        new=AsyncMock(return_value=True),
    ) as mock_guardar:
        assert await guardar_preferencia_automaticos("50670000000", False) is True

    mock_guardar.assert_awaited_once_with("50670000000", False)


def test_textos_de_confirmacion_no_prometen_borrado() -> None:
    assert "datos" in TEXTO_STOP_CONFIRMADO
    assert "stop" in TEXTO_ACTIVAR_CONFIRMADO.lower()
