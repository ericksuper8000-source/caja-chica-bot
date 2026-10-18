from unittest.mock import MagicMock, patch

import gspread
import pytest

from services.politica_service import (
    POLITICA_VERSION,
    TEXTO_BAJA_CONFIRMADA,
    TEXTO_POLITICA_PRIVACIDAD,
)
from services.sheets_service import (
    SUSCRIPCION_HEADERS,
    SUSCRIPCIONES_TAB_NAME,
    obtener_suscripcion,
)
from services.suscripcion_service import (
    TEXTO_SUSCRIPCION_NO_ACTIVA,
    TEXTO_SUSCRIPCION_SUSPENDIDA,
    TEXTO_SUSCRIPCION_VENCIDA,
    mensaje_suscripcion_no_activa,
    suscripcion_permite_uso,
)


def _consentimiento_aceptado() -> dict[str, str]:
    return {"estado": "aceptado", "version_politica": POLITICA_VERSION}


# ==========================================
# ESTADOS Y MENSAJES (7.2.1, ADR-0013)
# ==========================================
@pytest.mark.parametrize(
    "estado",
    ["activo", "gratis", "de_prueba", " Activo ", "GRATIS", "De_Prueba"],
)
def test_estados_con_acceso_permiten_uso(estado: str) -> None:
    """Los 3 estados con acceso pasan el gate, escritos como los escriba el fundador."""
    assert suscripcion_permite_uso({"estado": estado}) is True


@pytest.mark.parametrize(
    "estado",
    ["vencido", "suspendido", "cancelado", "VENCIDO", "", "desconocido"],
)
def test_estados_sin_acceso_bloquean(estado: str) -> None:
    """'vencido', 'suspendido' y 'cancelado' (más cualquier basura) no pasan el gate."""
    assert suscripcion_permite_uso({"estado": estado}) is False


def test_sin_registro_bloquea() -> None:
    """Un teléfono sin fila en `Suscripciones` no está al día: no pasa el gate."""
    assert suscripcion_permite_uso(None) is False


def test_mensaje_vencido_explica_como_reactivar() -> None:
    """ADR-0013/7.5: al vencido se le dice que venció y cómo reactivar."""
    mensaje = mensaje_suscripcion_no_activa({"estado": "vencido"})
    assert mensaje == TEXTO_SUSCRIPCION_VENCIDA
    assert "venció" in mensaje
    assert "reactivar" in mensaje


def test_mensaje_suspendido() -> None:
    assert mensaje_suscripcion_no_activa({"estado": "suspendido"}) == TEXTO_SUSCRIPCION_SUSPENDIDA


@pytest.mark.parametrize("suscripcion", [None, {"estado": "cancelado"}, {"estado": "desconocido"}])
def test_mensaje_generico_sin_registro(suscripcion: dict[str, str] | None) -> None:
    assert mensaje_suscripcion_no_activa(suscripcion) == TEXTO_SUSCRIPCION_NO_ACTIVA


# ==========================================
# LECTURA DE LA PESTAÑA `Suscripciones` (SOLO LECTURA)
# ==========================================
@pytest.mark.anyio
@patch("services.sheets_service.get_sheets_client")
async def test_obtener_suscripcion_sin_registro(mock_get_sheets_client) -> None:
    mock_client = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_worksheet = MagicMock()

    mock_get_sheets_client.return_value = mock_client
    mock_client.open_by_key.return_value = mock_spreadsheet
    mock_spreadsheet.worksheet.return_value = mock_worksheet

    # Solo encabezados, sin filas de usuarios
    mock_worksheet.col_values.return_value = ["telefono"]

    result = await obtener_suscripcion("50688888888")
    assert result is None


@pytest.mark.anyio
@patch("services.sheets_service.get_sheets_client")
async def test_obtener_suscripcion_registro_completo(mock_get_sheets_client) -> None:
    mock_client = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_worksheet = MagicMock()

    mock_get_sheets_client.return_value = mock_client
    mock_client.open_by_key.return_value = mock_spreadsheet
    mock_spreadsheet.worksheet.return_value = mock_worksheet

    mock_worksheet.col_values.return_value = ["telefono", "50688888888"]
    mock_worksheet.row_values.return_value = [
        "50688888888",
        "basico",
        "activo",
        "2026-08-20",
        "2026-11-20",
        "2026-10-01",
    ]

    result = await obtener_suscripcion("50688888888")
    assert result == {
        "telefono": "50688888888",
        "plan": "basico",
        "estado": "activo",
        "fecha_inicio": "2026-08-20",
        "fecha_renovacion": "2026-11-20",
        "ultimo_pago": "2026-10-01",
    }


@pytest.mark.anyio
@patch("services.sheets_service.get_sheets_client")
async def test_obtener_suscripcion_fila_incompleta(mock_get_sheets_client) -> None:
    """Una fila sin estado (columna C vacía) cuenta como sin suscripción: bloquea."""
    mock_client = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_worksheet = MagicMock()

    mock_get_sheets_client.return_value = mock_client
    mock_client.open_by_key.return_value = mock_spreadsheet
    mock_spreadsheet.worksheet.return_value = mock_worksheet

    mock_worksheet.col_values.return_value = ["telefono", "50688888888"]
    mock_worksheet.row_values.return_value = ["50688888888", "basico"]

    result = await obtener_suscripcion("50688888888")
    assert result is None


@pytest.mark.anyio
@patch("services.sheets_service.get_sheets_client")
async def test_obtener_suscripcion_crea_pestana_con_encabezados(mock_get_sheets_client) -> None:
    """La primera lectura crea la pestaña con encabezados (mismo patrón que 6.5.1)."""
    mock_client = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_worksheet = MagicMock()

    mock_get_sheets_client.return_value = mock_client
    mock_client.open_by_key.return_value = mock_spreadsheet

    mock_spreadsheet.worksheet.side_effect = gspread.exceptions.WorksheetNotFound(
        SUSCRIPCIONES_TAB_NAME
    )
    mock_spreadsheet.add_worksheet.return_value = mock_worksheet
    mock_worksheet.col_values.return_value = ["telefono"]

    result = await obtener_suscripcion("50688888888")

    assert result is None
    mock_spreadsheet.add_worksheet.assert_called_once()
    headers_call = mock_worksheet.append_row.call_args_list[0].args[0]
    assert headers_call == SUSCRIPCION_HEADERS


# ==========================================
# GATE COMERCIAL EN EL PIPELINE (7.2.1)
# ==========================================
@pytest.mark.anyio
@pytest.mark.parametrize("estado", ["activo", "gratis", "de_prueba"])
async def test_pipeline_procesa_con_suscripcion_al_dia(estado: str) -> None:
    """Los 3 estados con acceso dejan pasar el flujo normal completo."""
    with (
        patch("workers.tasks.obtener_consentimiento", return_value=_consentimiento_aceptado()),
        patch("workers.tasks.obtener_suscripcion", return_value={"estado": estado}),
        patch("workers.tasks.parse_financial_text", return_value=None) as mock_parse,
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
    ):
        from workers.tasks import _procesar_pipeline

        await _procesar_pipeline(None, "50688888888", texto_entrante="gasté 1500 en un sándwich")

    mock_parse.assert_called_once()
    mock_whatsapp.assert_called_once()


@pytest.mark.anyio
async def test_pipeline_bloquea_vencido_sin_gastar_openai() -> None:
    """Rompe-si (a) del plan: un vencido NO consume OpenAI ni Sheets; se le explica."""
    with (
        patch("workers.tasks.obtener_consentimiento", return_value=_consentimiento_aceptado()),
        patch("workers.tasks.obtener_suscripcion", return_value={"estado": "vencido"}),
        patch("workers.tasks.parse_financial_text") as mock_parse,
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
        patch("workers.tasks.append_transaction_to_sheet") as mock_sheet,
    ):
        from workers.tasks import _procesar_pipeline

        await _procesar_pipeline(None, "50688888888", texto_entrante="gasté 1500 en un sándwich")

    mock_parse.assert_not_called()
    mock_sheet.assert_not_called()
    mock_whatsapp.assert_called_once_with(
        to_phone="50688888888",
        mensaje=TEXTO_SUSCRIPCION_VENCIDA,
    )


@pytest.mark.anyio
async def test_pipeline_bloquea_suspendido() -> None:
    with (
        patch("workers.tasks.obtener_consentimiento", return_value=_consentimiento_aceptado()),
        patch("workers.tasks.obtener_suscripcion", return_value={"estado": "suspendido"}),
        patch("workers.tasks.parse_financial_text") as mock_parse,
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
    ):
        from workers.tasks import _procesar_pipeline

        await _procesar_pipeline(None, "50688888888", texto_entrante="gasté 1500 en un sándwich")

    mock_parse.assert_not_called()
    mock_whatsapp.assert_called_once_with(
        to_phone="50688888888",
        mensaje=TEXTO_SUSCRIPCION_SUSPENDIDA,
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "suscripcion",
    [None, {"estado": "cancelado"}],
    ids=["sin-registro", "cancelado-comercial"],
)
async def test_pipeline_bloquea_sin_suscripcion_registrada(
    suscripcion: dict[str, str] | None,
) -> None:
    with (
        patch("workers.tasks.obtener_consentimiento", return_value=_consentimiento_aceptado()),
        patch("workers.tasks.obtener_suscripcion", return_value=suscripcion),
        patch("workers.tasks.parse_financial_text") as mock_parse,
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
    ):
        from workers.tasks import _procesar_pipeline

        await _procesar_pipeline(None, "50688888888", texto_entrante="gasté 1500 en un sándwich")

    mock_parse.assert_not_called()
    mock_whatsapp.assert_called_once_with(
        to_phone="50688888888",
        mensaje=TEXTO_SUSCRIPCION_NO_ACTIVA,
    )


@pytest.mark.anyio
async def test_pipeline_vencido_no_confirma_duplicado_pendiente() -> None:
    """El gate comercial va ANTES del dedupe: 'sí' no registra ni lee el pendiente."""
    with (
        patch("workers.tasks.obtener_consentimiento", return_value=_consentimiento_aceptado()),
        patch("workers.tasks.obtener_suscripcion", return_value={"estado": "vencido"}),
        patch("workers.tasks._leer_pendiente") as mock_leer,
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
        patch("workers.tasks.append_transaction_to_sheet") as mock_sheet,
    ):
        from workers.tasks import _procesar_pipeline

        await _procesar_pipeline(None, "50688888888", texto_entrante="sí")

    mock_leer.assert_not_called()
    mock_sheet.assert_not_called()
    mock_whatsapp.assert_called_once_with(
        to_phone="50688888888",
        mensaje=TEXTO_SUSCRIPCION_VENCIDA,
    )


# ==========================================
# ARCO TIENE PRIORIDAD SOBRE EL GATE COMERCIAL
# ==========================================
@pytest.mark.anyio
async def test_vencido_no_bloquea_exportar_datos() -> None:
    """Derecho legal (Ley 8968): exportar funciona aunque la suscripción esté vencida."""
    with (
        patch("workers.tasks.obtener_consentimiento", return_value=_consentimiento_aceptado()),
        patch("workers.tasks.obtener_suscripcion", return_value={"estado": "vencido"}),
        patch(
            "workers.tasks.obtener_transacciones_cliente",
            return_value=[
                [
                    "2026-10-01 10:00:00",
                    -1500,
                    "Comida",
                    "almuerzo",
                    "50688888888",
                ]
            ],
        ) as mock_export,
        patch("workers.tasks.parse_financial_text") as mock_parse,
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
    ):
        from workers.tasks import _procesar_pipeline

        await _procesar_pipeline(None, "50688888888", texto_entrante="exporta mis datos")

    mock_export.assert_called_once()
    mock_parse.assert_not_called()
    mensaje = mock_whatsapp.call_args.kwargs["mensaje"]
    assert "Estos son tus movimientos registrados:" in mensaje


@pytest.mark.anyio
async def test_vencido_no_bloquea_darse_de_baja() -> None:
    """Derecho legal (Ley 8968): darse de baja funciona aunque esté vencida."""
    with (
        patch("workers.tasks.obtener_consentimiento", return_value=_consentimiento_aceptado()),
        patch("workers.tasks.obtener_suscripcion", return_value={"estado": "vencido"}),
        patch("workers.tasks.registrar_consentimiento", return_value=True) as mock_baja,
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
    ):
        from workers.tasks import _procesar_pipeline

        await _procesar_pipeline(None, "50688888888", texto_entrante="darme de baja")

    mock_baja.assert_called_once_with("50688888888", "cancelado")
    mock_whatsapp.assert_called_once_with(
        to_phone="50688888888",
        mensaje=TEXTO_BAJA_CONFIRMADA,
    )


@pytest.mark.anyio
async def test_sin_consentimiento_manda_politica_y_no_consulta_suscripcion() -> None:
    """Rompe-si (b): el orden legal-comercial es fijo — sin consentimiento no se llega
    al gate comercial, y se envía la política (no el aviso de suscripción)."""
    with (
        patch("workers.tasks.obtener_consentimiento", return_value=None),
        patch("workers.tasks.obtener_suscripcion") as mock_suscripcion,
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
    ):
        from workers.tasks import _procesar_pipeline

        await _procesar_pipeline(None, "50688888888", texto_entrante="gasté 1500 en un sándwich")

    mock_suscripcion.assert_not_called()
    mock_whatsapp.assert_called_once_with(
        to_phone="50688888888",
        mensaje=TEXTO_POLITICA_PRIVACIDAD,
    )
