from unittest.mock import AsyncMock, patch

import pytest

from services.politica_service import POLITICA_VERSION
from services.preferencias_service import TEXTO_ACTIVAR_CONFIRMADO, TEXTO_STOP_CONFIRMADO
from workers.tasks import _enviar_resumenes_semanales, _procesar_pipeline

CONSENTIMIENTO_OK = {"estado": "aceptado", "version_politica": POLITICA_VERSION}


@pytest.mark.anyio
async def test_pipeline_stop_desactiva_automaticos() -> None:
    with (
        patch("workers.tasks.obtener_consentimiento", return_value=CONSENTIMIENTO_OK),
        patch("workers.tasks.guardar_preferencia_automaticos") as mock_guardar,
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
        patch("workers.tasks.parse_financial_text") as mock_parser,
    ):
        result = await _procesar_pipeline(None, "50670000000", texto_entrante="STOP")

    assert result == ""
    mock_guardar.assert_awaited_once_with("50670000000", False)
    mock_whatsapp.assert_awaited_once_with(to_phone="50670000000", mensaje=TEXTO_STOP_CONFIRMADO)
    mock_parser.assert_not_called()


@pytest.mark.anyio
async def test_pipeline_activar_vuelve_a_habilitar() -> None:
    with (
        patch("workers.tasks.obtener_consentimiento", return_value=CONSENTIMIENTO_OK),
        patch("workers.tasks.guardar_preferencia_automaticos") as mock_guardar,
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
        patch("workers.tasks.parse_financial_text") as mock_parser,
    ):
        result = await _procesar_pipeline(None, "50670000000", texto_entrante="activar mensajes")

    assert result == ""
    mock_guardar.assert_awaited_once_with("50670000000", True)
    mock_whatsapp.assert_awaited_once_with(to_phone="50670000000", mensaje=TEXTO_ACTIVAR_CONFIRMADO)
    mock_parser.assert_not_called()


@pytest.mark.anyio
async def test_pipeline_envia_alerta_de_presupuesto_tras_gasto() -> None:
    transaccion = {
        "accion": "registrar",
        "monto": 10000,
        "categoria": "Transporte",
        "tipo_movimiento": "Gasto",
        "detalle": "taxi",
    }
    with (
        patch("workers.tasks.obtener_consentimiento", return_value=CONSENTIMIENTO_OK),
        patch("workers.tasks.parse_financial_text", return_value=transaccion),
        patch(
            "workers.tasks.append_transaction_to_sheet",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "workers.tasks.obtener_transacciones_cliente",
            new=AsyncMock(return_value=[]),
        ),
        patch("workers.tasks.calcular_gastado_mes", return_value=45000),
        patch(
            "workers.tasks.verificar_y_alertar_presupuesto",
            new=AsyncMock(return_value="ALERTA 80%"),
        ) as mock_alerta,
        patch("workers.tasks._es_duplicado", new=AsyncMock(return_value=False)),
        patch("workers.tasks._marcar_ultimo_registro", new=AsyncMock()),
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
    ):
        result = await _procesar_pipeline(None, "50670000000", texto_entrante="gasté 10000 en taxi")

    assert result == ""
    mock_alerta.assert_awaited_once_with("50670000000", "Transporte", 10000, 45000)
    assert mock_whatsapp.call_args_list[-1].kwargs["mensaje"] == "ALERTA 80%"


@pytest.mark.anyio
async def test_pipeline_no_evalua_alerta_para_ingresos() -> None:
    transaccion = {
        "accion": "registrar",
        "monto": 10000,
        "categoria": "Ventas",
        "tipo_movimiento": "Ingreso",
        "detalle": "venta",
    }
    with (
        patch("workers.tasks.obtener_consentimiento", return_value=CONSENTIMIENTO_OK),
        patch("workers.tasks.parse_financial_text", return_value=transaccion),
        patch(
            "workers.tasks.append_transaction_to_sheet",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "workers.tasks.verificar_y_alertar_presupuesto",
            new=AsyncMock(return_value="NO DEBE USARSE"),
        ) as mock_alerta,
        patch("workers.tasks._es_duplicado", new=AsyncMock(return_value=False)),
        patch("workers.tasks._marcar_ultimo_registro", new=AsyncMock()),
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
    ):
        result = await _procesar_pipeline(
            None, "50670000000", texto_entrante="vendí 10000 en camisetas"
        )

    assert result == ""
    mock_alerta.assert_not_awaited()
    assert all(
        llamada.kwargs["mensaje"] != "NO DEBE USARSE" for llamada in mock_whatsapp.call_args_list
    )


@pytest.mark.anyio
async def test_resumen_semanal_respeta_horario_de_silencio() -> None:
    with (
        patch("workers.tasks.en_horario_silencio", return_value=True),
        patch(
            "workers.tasks.obtener_telefonos_con_acceso",
            new=AsyncMock(return_value=["50670000000"]),
        ) as mock_telefonos,
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
    ):
        resultado = await _enviar_resumenes_semanales()

    assert resultado == {"enviados": 0, "omitidos": 0, "errores": 0}
    mock_telefonos.assert_not_awaited()
    mock_whatsapp.assert_not_called()


@pytest.mark.anyio
async def test_resumen_semanal_envia_solo_a_habilitados_con_movimientos() -> None:
    filas = [["2026-11-06 10:00:00", "-1000", "Transporte", "bus", "50670000000"]]
    with (
        patch("workers.tasks.en_horario_silencio", return_value=False),
        patch(
            "workers.tasks.obtener_telefonos_con_acceso",
            new=AsyncMock(return_value=["111", "222", "333"]),
        ),
        patch(
            "workers.tasks.resumen_semanal_habilitado",
            new=AsyncMock(side_effect=[True, False, True]),
        ),
        patch(
            "workers.tasks.obtener_transacciones_cliente",
            new=AsyncMock(side_effect=[filas, [], []]),
        ),
        patch("workers.tasks.calcular_resumen"),
        patch("workers.tasks.formatear_texto", return_value="texto semanal"),
        patch("workers.tasks.dividir_mensaje_largo", return_value=["texto semanal"]),
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
    ):
        resultado = await _enviar_resumenes_semanales()

    assert resultado == {"enviados": 1, "omitidos": 2, "errores": 0}
    mock_whatsapp.assert_awaited_once_with(to_phone="111", mensaje="texto semanal")


@pytest.mark.anyio
async def test_resumen_semanal_un_error_no_frena_al_resto() -> None:
    filas = [["2026-11-06 10:00:00", "-1000", "Transporte", "bus", "222"]]
    with (
        patch("workers.tasks.en_horario_silencio", return_value=False),
        patch(
            "workers.tasks.obtener_telefonos_con_acceso",
            new=AsyncMock(return_value=["111", "222"]),
        ),
        patch(
            "workers.tasks.resumen_semanal_habilitado",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "workers.tasks.obtener_transacciones_cliente",
            new=AsyncMock(side_effect=[Exception("sheet caído"), filas]),
        ),
        patch("workers.tasks.calcular_resumen"),
        patch("workers.tasks.formatear_texto", return_value="texto semanal"),
        patch("workers.tasks.dividir_mensaje_largo", return_value=["texto semanal"]),
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
    ):
        resultado = await _enviar_resumenes_semanales()

    assert resultado == {"enviados": 1, "omitidos": 0, "errores": 1}
    mock_whatsapp.assert_awaited_once_with(to_phone="222", mensaje="texto semanal")
