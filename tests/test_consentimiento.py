import asyncio
from unittest.mock import MagicMock, patch

import gspread
import pytest

from app.core.utils import extraer_datos_texto
from services.politica_service import (
    TEXTO_POLITICA_PRIVACIDAD,
    detectar_respuesta_consentimiento,
)
from services.sheets_service import (
    CONSENT_HEADERS,
    CONSENT_TAB_NAME,
    obtener_consentimiento,
    registrar_consentimiento,
)
from workers.tasks import _procesar_pipeline, procesar_mensaje_texto_task


# ==========================================
# POLÍTICA Y DETECCIÓN DE RESPUESTA (6.5.1)
# ==========================================
def test_detectar_acepto_explicito() -> None:
    assert detectar_respuesta_consentimiento("ACEPTO") == "aceptar"
    assert detectar_respuesta_consentimiento("acepto la política") == "aceptar"
    assert detectar_respuesta_consentimiento("si, acepto") == "aceptar"
    assert detectar_respuesta_consentimiento("estoy de acuerdo") == "aceptar"


def test_detectar_rechazo_explicito() -> None:
    assert detectar_respuesta_consentimiento("no acepto") == "rechazar"
    assert detectar_respuesta_consentimiento("no aceptar la política") == "rechazar"
    assert detectar_respuesta_consentimiento("rechazo") == "rechazar"


def test_detectar_no_consentimiento() -> None:
    assert detectar_respuesta_consentimiento("gasté 5000 en el almuerzo") is None
    assert detectar_respuesta_consentimiento("") is None
    assert detectar_respuesta_consentimiento("hola") is None


def test_politica_privacidad_cubre_elementos_ley_8968() -> None:
    """La política mínima debe mencionar: qué se guarda, transferencia internacional,
    derechos ARCO y la acción de aceptar/rechazar."""
    assert "Google Sheets" in TEXTO_POLITICA_PRIVACIDAD
    assert "OpenAI" in TEXTO_POLITICA_PRIVACIDAD
    assert "Ley 8968" in TEXTO_POLITICA_PRIVACIDAD
    assert "ACEPTO" in TEXTO_POLITICA_PRIVACIDAD
    assert "NO ACEPTO" in TEXTO_POLITICA_PRIVACIDAD


# ==========================================
# PERSISTENCIA DEL CONSENTIMIENTO EN SHEETS
# ==========================================
@pytest.mark.anyio
@patch("services.sheets_service.get_sheets_client")
async def test_obtener_consentimiento_sin_registro(mock_get_sheets_client) -> None:
    mock_client = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_worksheet = MagicMock()

    mock_get_sheets_client.return_value = mock_client
    mock_client.open_by_key.return_value = mock_spreadsheet
    mock_spreadsheet.worksheet.return_value = mock_worksheet

    # Solo encabezados, sin filas del usuario
    mock_worksheet.col_values.return_value = ["telefono"]

    result = await obtener_consentimiento("50688888888")
    assert result is None


@pytest.mark.anyio
@patch("services.sheets_service.get_sheets_client")
async def test_obtener_consentimiento_aceptado(mock_get_sheets_client) -> None:
    mock_client = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_worksheet = MagicMock()

    mock_get_sheets_client.return_value = mock_client
    mock_client.open_by_key.return_value = mock_spreadsheet
    mock_spreadsheet.worksheet.return_value = mock_worksheet

    mock_worksheet.col_values.return_value = ["telefono", "50688888888"]
    mock_worksheet.row_values.return_value = [
        "50688888888",
        "aceptado",
        "2026-08-20 10:00:00",
        "1.0",
    ]

    result = await obtener_consentimiento("50688888888")
    assert result == {
        "telefono": "50688888888",
        "estado": "aceptado",
        "fecha": "2026-08-20 10:00:00",
        "version_politica": "1.0",
    }


@pytest.mark.anyio
@patch("services.sheets_service.get_sheets_client")
async def test_registrar_consentimiento_crea_pestana(mock_get_sheets_client) -> None:
    mock_client = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_worksheet = MagicMock()

    mock_get_sheets_client.return_value = mock_client
    mock_client.open_by_key.return_value = mock_spreadsheet

    # La pestaña NO existe → se crea
    mock_spreadsheet.worksheet.side_effect = gspread.exceptions.WorksheetNotFound(CONSENT_TAB_NAME)
    mock_spreadsheet.add_worksheet.return_value = mock_worksheet
    mock_worksheet.col_values.return_value = ["telefono"]

    result = await registrar_consentimiento("50688888888", "aceptado")

    assert result is True
    mock_spreadsheet.add_worksheet.assert_called_once()
    # append_row se llama dos veces: una con los encabezados (al crear la pestaña)
    # y otra con el registro del usuario (el segundo valor de ValueInputOption)
    assert mock_worksheet.append_row.call_count == 2
    headers_call = mock_worksheet.append_row.call_args_list[0].args[0]
    record_call = mock_worksheet.append_row.call_args_list[1].args[0]
    assert headers_call == ["telefono", "estado", "fecha", "version_politica"]
    assert record_call[0] == "50688888888"
    assert record_call[1] == "aceptado"
    assert record_call[3] == "1.0"


@pytest.mark.anyio
@patch("services.sheets_service.get_sheets_client")
async def test_registrar_consentimiento_pestana_existente(mock_get_sheets_client) -> None:
    mock_client = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_worksheet = MagicMock()

    mock_get_sheets_client.return_value = mock_client
    mock_client.open_by_key.return_value = mock_spreadsheet
    mock_spreadsheet.worksheet.return_value = mock_worksheet

    # El usuario ya tiene una fila (rechazado antes) → se actualiza, no se duplica
    mock_worksheet.col_values.return_value = ["telefono", "50688888888"]

    result = await registrar_consentimiento("50688888888", "aceptado")

    assert result is True
    mock_worksheet.update.assert_called_once()
    args = mock_worksheet.update.call_args
    assert args.args[0] == "B2:D2"
    assert args.args[1][0][0] == "aceptado"
    assert args.args[1][0][2] == "1.0"


def test_consent_headers_definidos() -> None:
    assert CONSENT_HEADERS == ["telefono", "estado", "fecha", "version_politica"]


# ==========================================
# CANAL DE TEXTO (UTILS)
# ==========================================
def test_extraer_datos_texto_exitoso() -> None:
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "type": "text",
                                    "text": {"body": "ACEPTO"},
                                    "from": "50612345678",
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    resultado = extraer_datos_texto(payload)
    assert resultado == {"texto": "ACEPTO", "from_phone": "50612345678"}


def test_extraer_datos_texto_no_es_texto() -> None:
    payload = {
        "entry": [{"changes": [{"value": {"messages": [{"type": "audio", "audio": {"id": "9"}}]}}]}]
    }
    assert extraer_datos_texto(payload) is None


def test_extraer_datos_texto_payload_incompleto() -> None:
    assert extraer_datos_texto({}) is None


# ==========================================
# GATE DE CONSENTIMIENTO EN EL PIPELINE (TASKS)
# ==========================================
@pytest.mark.anyio
async def test_pipeline_sin_consentimiento_envia_politica() -> None:
    """Sin consentimiento y sin respuesta de aceptación → NO procesa, envía la política."""
    with (
        patch("workers.tasks.obtener_consentimiento", return_value=None),
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
        patch("workers.tasks.parse_financial_text") as mock_parser,
        patch("workers.tasks.append_transaction_to_sheet") as mock_sheet,
        patch("workers.tasks.registrar_consentimiento") as mock_registrar,
    ):
        result = await _procesar_pipeline(
            "/tmp/audio.ogg", "50688888888", texto_entrante="gasté 5000 en el almuerzo"
        )

    assert result == "/tmp/audio.ogg"
    mock_whatsapp.assert_called_once_with(to_phone="50688888888", mensaje=TEXTO_POLITICA_PRIVACIDAD)
    mock_parser.assert_not_called()
    mock_sheet.assert_not_called()
    mock_registrar.assert_not_called()


@pytest.mark.anyio
async def test_pipeline_acepta_consentimiento() -> None:
    """'ACEPTO' sin consentimiento previo → registra 'aceptado' y NO procesa transacción."""
    with (
        patch("workers.tasks.obtener_consentimiento", return_value=None),
        patch("workers.tasks.registrar_consentimiento") as mock_registrar,
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
        patch("workers.tasks.parse_financial_text") as mock_parser,
        patch("workers.tasks.append_transaction_to_sheet") as mock_sheet,
    ):
        result = await _procesar_pipeline(None, "50688888888", texto_entrante="ACEPTO la política")

    assert result == ""
    mock_registrar.assert_called_once_with("50688888888", "aceptado")
    mock_whatsapp.assert_called_once()
    mock_parser.assert_not_called()
    mock_sheet.assert_not_called()


@pytest.mark.anyio
async def test_pipeline_rechaza_consentimiento() -> None:
    """'NO ACEPTO' → registra 'rechazado' y NO procesa transacción."""
    with (
        patch("workers.tasks.obtener_consentimiento", return_value=None),
        patch("workers.tasks.registrar_consentimiento") as mock_registrar,
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
        patch("workers.tasks.parse_financial_text") as mock_parser,
        patch("workers.tasks.append_transaction_to_sheet") as mock_sheet,
    ):
        result = await _procesar_pipeline(
            None, "50688888888", texto_entrante="no acepto la política"
        )

    assert result == ""
    mock_registrar.assert_called_once_with("50688888888", "rechazado")
    mock_whatsapp.assert_called_once()
    mock_parser.assert_not_called()
    mock_sheet.assert_not_called()


@pytest.mark.anyio
async def test_pipeline_con_consentimiento_procesa_normal() -> None:
    """Con consentimiento aceptado → el flujo financiero normal sigue igual."""
    with (
        patch(
            "workers.tasks.obtener_consentimiento",
            return_value={"estado": "aceptado", "version_politica": "1.0"},
        ),
        patch(
            "workers.tasks.parse_financial_text",
            return_value={
                "accion": "registrar",
                "monto": 5000,
                "categoria": "Alimentación",
                "tipo_movimiento": "Gasto",
                "detalle": "Almuerzo",
            },
        ),
        patch("workers.tasks.append_transaction_to_sheet") as mock_sheet,
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
    ):
        result = await _procesar_pipeline(
            "/tmp/audio.ogg", "50688888888", texto_entrante="gasté 5000 en el almuerzo"
        )

    assert result == "/tmp/audio.ogg"
    mock_sheet.assert_called_once()
    mock_whatsapp.assert_called_once()


def test_procesar_mensaje_texto_task_despacha_pipeline() -> None:
    """La tarea de Celery de texto delega en el pipeline con el texto directo."""
    with (
        patch("workers.tasks.obtener_consentimiento", return_value=None),
        patch("workers.tasks.registrar_consentimiento") as mock_registrar,
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
    ):
        resultado = procesar_mensaje_texto_task("50688888888", "ACEPTO")

    assert resultado == ""
    mock_registrar.assert_called_once_with("50688888888", "aceptado")
    mock_whatsapp.assert_called_once()


@pytest.mark.anyio
async def test_pipeline_sin_consentimiento_audio_no_parsea() -> None:
    """Caso audio: sin consentimiento, nota de voz financiera → política, sin parser."""
    with (
        patch("workers.tasks.obtener_consentimiento", return_value=None),
        patch("workers.tasks.transcribir_audio_whisper", return_value="gasté 2000 en el bus"),
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
        patch("workers.tasks.parse_financial_text") as mock_parser,
        patch("workers.tasks.append_transaction_to_sheet") as mock_sheet,
    ):
        result = await _procesar_pipeline("/tmp/audio.ogg", "50688888888")

    assert result == "/tmp/audio.ogg"
    mock_whatsapp.assert_called_once_with(to_phone="50688888888", mensaje=TEXTO_POLITICA_PRIVACIDAD)
    mock_parser.assert_not_called()
    mock_sheet.assert_not_called()


def test_async_loop_unicoy() -> None:
    """El pipeline es invocado por un único asyncio.run() en cada tarea (ADR-0005)."""
    assert asyncio.iscoroutinefunction(_procesar_pipeline) is True
