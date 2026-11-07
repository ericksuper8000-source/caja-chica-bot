from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from services.presupuesto_service import (
    calcular_gastado_mes,
    detectar_presupuesto,
    eliminar_presupuesto,
    establecer_presupuesto,
    obtener_presupuestos,
    verificar_y_alertar_presupuesto,
)


def _fila(
    telefono: str = "50670000000",
    categoria: str = "transporte",
    limite: str = "50000",
    alerta_80: str = "",
    alerta_100: str = "",
) -> dict[str, str]:
    return {
        "telefono": telefono,
        "categoria": categoria,
        "limite": limite,
        "periodo": "mensual",
        "alerta_80": alerta_80,
        "alerta_100": alerta_100,
    }


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("presupuesto transporte 20000", ("transporte", 20000)),
        ("Presupuesto de transporte 20.000", ("transporte", 20000)),
        ("presupuesto para transporte 20 mil", ("transporte", 20000)),
        ("presupuesto transporte 20000 colones", ("transporte", 20000)),
        ("presupuesto comida 30,000", ("alimentacion", 30000)),
        ("presupuesto luz 15000", ("servicios", 15000)),
        ("presupuesto transporte veinte mil", ("transporte", 20000)),
        ("presupuesto de transporte veinte mil colones", ("transporte", 20000)),
        ("presupuesto para el transporte quince mil", ("transporte", 15000)),
        (
            "presupuesto alimentación veinticinco mil quinientos",
            ("alimentacion", 25500),
        ),
        ("presupuesto servicios cien mil", ("servicios", 100000)),
        ("presupuesto transporte doscientos mil", ("transporte", 200000)),
        ("presupuesto transporte un millón", ("transporte", 1000000)),
    ],
)
def test_detectar_presupuesto_tolera_formatos(texto: str, esperado: tuple[str, int]) -> None:
    assert detectar_presupuesto(texto) == esperado


@pytest.mark.parametrize(
    "texto",
    [
        "presupuesto transporte",
        "presupuesto transporte 0",
        "presupuesto de",
        "gasté 2000 en transporte",
        "hola",
    ],
)
def test_detectar_presupuesto_rechaza_invalidos(texto: str) -> None:
    assert detectar_presupuesto(texto) is None


@pytest.mark.anyio
async def test_obtener_presupuestos_filtra_y_normaliza() -> None:
    filas = [
        _fila(categoria="Transporte", limite="50000"),
        _fila(categoria="Alimentación", limite="30000"),
        _fila(telefono="50688888888", categoria="Transporte", limite="999"),
    ]
    with patch(
        "services.presupuesto_service.obtener_presupuestos_sheet",
        new=AsyncMock(return_value=filas),
    ):
        resultado = await obtener_presupuestos("50670000000")

    assert resultado == {"transporte": 50000, "alimentacion": 30000}


@pytest.mark.anyio
async def test_establecer_presupuesto_guarda_en_pestana() -> None:
    with patch(
        "services.presupuesto_service.guardar_presupuesto_sheet",
        new=AsyncMock(return_value=True),
    ) as mock_guardar:
        assert await establecer_presupuesto("50670000000", "transporte", 50000) is True
        assert await establecer_presupuesto("50670000000", "transporte", 0) is False

    mock_guardar.assert_awaited_once_with("50670000000", "transporte", 50000)


@pytest.mark.anyio
async def test_eliminar_presupuesto_delega_en_la_pestana() -> None:
    with patch(
        "services.presupuesto_service.eliminar_presupuesto_sheet",
        new=AsyncMock(side_effect=[True, False]),
    ) as mock_eliminar:
        assert await eliminar_presupuesto("50670000000", "transporte") is True
        assert await eliminar_presupuesto("50670000000", "transporte") is False

    assert mock_eliminar.await_count == 2


def test_calcular_gastado_mes_suma_solo_gastos_del_mes() -> None:
    ahora = datetime(2026, 11, 15, 12, 0, 0)
    filas = [
        ["2026-11-01 10:00:00", "-1000", "Transporte", "bus", "t"],
        ["2026-11-14 10:00:00", "-500", "transporte", "taxi", "t"],
        ["2026-11-10 10:00:00", "2000", "Transporte", "ingreso", "t"],
        ["2026-10-31 10:00:00", "-999", "Transporte", "mes anterior", "t"],
        ["2026-11-05 10:00:00", "-700", "Alimentación", "comida", "t"],
    ]

    assert calcular_gastado_mes(filas, "Transporte", ahora) == 1500


@pytest.mark.anyio
async def test_alerta_80_una_vez_por_periodo() -> None:
    with (
        patch(
            "services.presupuesto_service.obtener_presupuestos_sheet",
            new=AsyncMock(return_value=[_fila()]),
        ),
        patch(
            "services.presupuesto_service.marcar_alerta_presupuesto_sheet",
            new=AsyncMock(return_value=True),
        ) as mock_marcar,
        patch("services.presupuesto_service._periodo_actual", return_value="2026-11"),
    ):
        alerta = await verificar_y_alertar_presupuesto("50670000000", "Transporte", 1000, 40000)

    assert alerta is not None
    assert "Vas por" in alerta
    mock_marcar.assert_awaited_once_with("50670000000", "Transporte", 80, "2026-11")


@pytest.mark.anyio
async def test_alerta_80_no_repite_si_ya_marcada() -> None:
    with (
        patch(
            "services.presupuesto_service.obtener_presupuestos_sheet",
            new=AsyncMock(return_value=[_fila(alerta_80="2026-11")]),
        ),
        patch(
            "services.presupuesto_service.marcar_alerta_presupuesto_sheet",
            new=AsyncMock(return_value=True),
        ) as mock_marcar,
        patch("services.presupuesto_service._periodo_actual", return_value="2026-11"),
    ):
        alerta = await verificar_y_alertar_presupuesto("50670000000", "Transporte", 1000, 40000)

    assert alerta is None
    mock_marcar.assert_not_called()


@pytest.mark.anyio
async def test_alerta_100_marca_ambos_umbrales() -> None:
    with (
        patch(
            "services.presupuesto_service.obtener_presupuestos_sheet",
            new=AsyncMock(return_value=[_fila()]),
        ),
        patch(
            "services.presupuesto_service.marcar_alerta_presupuesto_sheet",
            new=AsyncMock(return_value=True),
        ) as mock_marcar,
        patch("services.presupuesto_service._periodo_actual", return_value="2026-11"),
    ):
        alerta = await verificar_y_alertar_presupuesto("50670000000", "Transporte", 1000, 50000)

    assert alerta is not None
    assert "Te pasaste" in alerta
    assert mock_marcar.await_count == 2
    mock_marcar.assert_any_await("50670000000", "Transporte", 100, "2026-11")
    mock_marcar.assert_any_await("50670000000", "Transporte", 80, "2026-11")


@pytest.mark.anyio
async def test_sin_presupuesto_no_alerta() -> None:
    with patch(
        "services.presupuesto_service.obtener_presupuestos_sheet",
        new=AsyncMock(return_value=[]),
    ):
        assert (
            await verificar_y_alertar_presupuesto("50670000000", "Transporte", 1000, 999999) is None
        )


@pytest.mark.anyio
async def test_por_debajo_del_80_no_alerta() -> None:
    with (
        patch(
            "services.presupuesto_service.obtener_presupuestos_sheet",
            new=AsyncMock(return_value=[_fila()]),
        ),
        patch(
            "services.presupuesto_service.marcar_alerta_presupuesto_sheet",
            new=AsyncMock(return_value=True),
        ) as mock_marcar,
        patch("services.presupuesto_service._periodo_actual", return_value="2026-11"),
    ):
        alerta = await verificar_y_alertar_presupuesto("50670000000", "Transporte", 1000, 39999)

    assert alerta is None
    mock_marcar.assert_not_called()
