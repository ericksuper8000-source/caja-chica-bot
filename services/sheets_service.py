import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import gspread
from gspread.utils import ValueInputOption  # Importamos el enumerado para el tipado

from app.config import settings
from services.politica_service import POLITICA_VERSION

logger = logging.getLogger(__name__)

_sheets_client: Any = None

# Fase 6.5.1 — Consentimiento (ADR-0011, Ley 8968). En MVP la "tabla usuarios"
# se materializa como una pestaña del mismo Google Sheet (ADR-0002/0009).
CONSENT_TAB_NAME = "Consentimiento"
CONSENT_HEADERS = ["telefono", "estado", "fecha", "version_politica"]


def get_sheets_client() -> Any:
    """
    Inicializa y devuelve el cliente autenticado de gspread.
    Reusa el cliente si ya fue creado para evitar múltiples autenticaciones.
    """
    global _sheets_client
    if _sheets_client is not None:
        return _sheets_client
    try:
        _sheets_client = gspread.service_account(filename=settings.GOOGLE_APPLICATION_CREDENTIALS)  # type: ignore[attr-defined]
        return _sheets_client
    except Exception as e:
        logger.error(f"Error crítico al autenticar con gspread: {e}")
        raise e


def _sync_append_row(spreadsheet_id: str, row_values: list[Any]) -> None:
    """
    Operación puramente síncrona que interactúa con la API de Google Sheets.
    """
    client = get_sheets_client()
    spreadsheet = client.open_by_key(spreadsheet_id)
    worksheet = spreadsheet.get_worksheet(0)

    # Se utiliza ValueInputOption.user_entered para cumplir con el tipado de mypy
    worksheet.append_row(row_values, value_input_option=ValueInputOption.user_entered)


def _sync_update_last_row(spreadsheet_id: str, sender_phone: str, row_values: list[Any]) -> None:
    """
    Operación síncrona: localiza la última fila cuyo teléfono coincida con el remitente
    y reescribe sus celdas (monto, categoría, detalle y teléfono) conservando la fecha.
    Lanza LookupError si el usuario no tiene transacciones previas.
    """
    client = get_sheets_client()
    spreadsheet = client.open_by_key(spreadsheet_id)
    worksheet = spreadsheet.get_worksheet(0)

    phone_values = worksheet.col_values(5)
    matches = [i for i, phone in enumerate(phone_values, start=1) if phone == sender_phone]
    if not matches:
        raise LookupError(f"sin transacciones previas para {sender_phone}")

    last_row = matches[-1]
    worksheet.update(
        f"B{last_row}:E{last_row}",
        [row_values],
        value_input_option=ValueInputOption.user_entered,
    )


def _sync_read_last_row(spreadsheet_id: str, sender_phone: str) -> list[Any]:
    """
    Operación síncrona: lee la última fila cuyo teléfono coincida con el remitente
    (columnas A:E) para poder fusionar el delta de una corrección con los valores
    anteriores. Lanza LookupError si el usuario no tiene transacciones previas.
    """
    client = get_sheets_client()
    spreadsheet = client.open_by_key(spreadsheet_id)
    worksheet = spreadsheet.get_worksheet(0)

    phone_values = worksheet.col_values(5)
    matches = [i for i, phone in enumerate(phone_values, start=1) if phone == sender_phone]
    if not matches:
        raise LookupError(f"sin transacciones previas para {sender_phone}")

    last_row = matches[-1]
    return list(worksheet.row_values(last_row))


def _merge_delta_con_ultima_fila(delta: dict[str, Any], fila_anterior: list[Any]) -> list[Any]:
    """
    Fusiona el delta de una corrección con los valores de la última fila del usuario.

    Semántica de delta (plan-correccion-delta.md, hallazgo 13/08/2026): un campo que el
    LLM devuelve como None significa "el usuario no lo mencionó" → se conserva el valor
    anterior. Un campo con valor se aplica. Desde el 20/08/2026 un monto de 0 también se
    trata como "no mencionado" (el 0 es un monto inválido que la IA no debe inventar) y
    conserva el monto anterior. La fila previa viene como
    [fecha, monto, categoria, detalle, telefono] y se devuelve el row a escribir en B:E.
    """
    prev_monto = int(fila_anterior[1]) if len(fila_anterior) > 1 and fila_anterior[1] else 0
    prev_categoria = fila_anterior[2] if len(fila_anterior) > 2 else "Otros"
    prev_detalle = fila_anterior[3] if len(fila_anterior) > 3 else ""

    tipo = delta.get("tipo_movimiento")
    if tipo is None:
        tipo = "Gasto" if prev_monto < 0 else "Ingreso"

    monto = delta.get("monto")
    if not monto:
        monto = abs(prev_monto)

    if tipo.lower() == "gasto" and monto > 0:
        monto = -monto

    categoria = delta.get("categoria") or prev_categoria
    detalle = delta.get("detalle") or prev_detalle

    return [monto, categoria, detalle]


async def append_transaction_to_sheet(transaction_data: dict[str, Any], sender_phone: str) -> bool:
    """
    Inserta una nueva fila en Google Sheets de manera asíncrona.

    La fila guarda también el teléfono del remitente (columna "teléfono"),
    base para localizar la última transacción del usuario en el flujo de
    corrección (5.5.3) y para la identidad por teléfono (6.1).
    """
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID

    try:
        fecha_actual = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        monto = transaction_data.get("monto", 0)
        tipo = transaction_data.get("tipo_movimiento") or "Gasto"

        if tipo.lower() == "gasto" and monto > 0:
            monto = -monto

        row_values = [
            fecha_actual,
            monto,
            transaction_data.get("categoria", "Otros"),
            transaction_data.get("detalle", ""),
            sender_phone,
        ]

        await asyncio.to_thread(_sync_append_row, spreadsheet_id, row_values)

        logger.info(f"Fila insertada con éxito en Sheets de forma asíncrona: {row_values}")
        return True

    except gspread.exceptions.APIError as error:
        logger.error(f"Error de API de gspread al escribir en Google Sheets: {error}")
        return False
    except Exception as e:
        logger.error(f"Error inesperado en el servicio de Sheets: {e}")
        return False


async def update_last_transaction_to_sheet(
    transaction_data: dict[str, Any], sender_phone: str
) -> list[Any] | None:
    """
    Actualiza la última transacción del remitente con los datos corregidos
    (flujo de corrección 5.5.3, ADR-0010) usando semántica de DELTA: los campos
    que el LLM devuelve como None se conservan de la fila anterior (corrección
    parcial no destruye datos). Devuelve la fila final aplicada [monto, categoria,
    detalle]; None si el usuario no tiene transacciones previas o hubo error de API.
    """
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID

    try:
        fila_anterior = await asyncio.to_thread(_sync_read_last_row, spreadsheet_id, sender_phone)
        row_values = _merge_delta_con_ultima_fila(transaction_data, fila_anterior)
        row_to_write = [*row_values, sender_phone]

        await asyncio.to_thread(_sync_update_last_row, spreadsheet_id, sender_phone, row_to_write)

        logger.info(f"Transacción corregida en Sheets para {sender_phone}: {row_to_write}")
        return row_values

    except LookupError as error:
        logger.info(f"No hay transacción previa del usuario {sender_phone}: {error}")
        return None
    except gspread.exceptions.APIError as error:
        logger.error(f"Error de API de gspread al corregir en Google Sheets: {error}")
        return None
    except Exception as e:
        logger.error(f"Error inesperado en el servicio de Sheets (corregir): {e}")
        return None


# ==========================================
# FASE 6.5.1 — CONSENTIMIENTO (ADR-0011, Ley 8968)
# ==========================================
def _sync_get_consent_worksheet(spreadsheet_id: str) -> Any:
    """Devuelve la pestaña de consentimientos, creándola con encabezados si no existe."""
    client = get_sheets_client()
    spreadsheet = client.open_by_key(spreadsheet_id)
    try:
        worksheet = spreadsheet.worksheet(CONSENT_TAB_NAME)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=CONSENT_TAB_NAME, rows=100, cols=10)
        worksheet.append_row(
            CONSENT_HEADERS,
            value_input_option=ValueInputOption.user_entered,
        )
    return worksheet


def _sync_read_consent(spreadsheet_id: str, sender_phone: str) -> dict[str, Any] | None:
    """
    Operación síncrona: lee el registro de consentimiento del teléfono (columna A)
    y retorna {'telefono', 'estado', 'fecha', 'version_politica'} o None si no existe.
    """
    worksheet = _sync_get_consent_worksheet(spreadsheet_id)
    phones = worksheet.col_values(1)
    matches = [i for i, phone in enumerate(phones, start=1) if phone == sender_phone]
    if not matches:
        return None

    last_row = matches[-1]
    values = worksheet.row_values(last_row)
    if len(values) < 2 or not values[1]:
        return None
    return {
        "telefono": values[0],
        "estado": values[1],
        "fecha": values[2] if len(values) > 2 else "",
        "version_politica": values[3] if len(values) > 3 else "",
    }


def _sync_write_consent(spreadsheet_id: str, sender_phone: str, estado: str) -> None:
    """Operación síncrona: registra (o actualiza) el estado de consentimiento del teléfono."""
    worksheet = _sync_get_consent_worksheet(spreadsheet_id)

    phones = worksheet.col_values(1)
    matches = [i for i, phone in enumerate(phones, start=1) if phone == sender_phone]
    fecha_actual = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")

    if matches:
        last_row = matches[-1]
        worksheet.update(
            f"B{last_row}:D{last_row}",
            [[estado, fecha_actual, POLITICA_VERSION]],
            value_input_option=ValueInputOption.user_entered,
        )
    else:
        worksheet.append_row(
            [sender_phone, estado, fecha_actual, POLITICA_VERSION],
            value_input_option=ValueInputOption.user_entered,
        )


async def obtener_consentimiento(sender_phone: str) -> dict[str, Any] | None:
    """
    Consulta el estado de consentimiento del usuario en Google Sheets.
    Retorna el registro completo o None si el usuario nunca respondió la política.
    """
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID
    try:
        return await asyncio.to_thread(_sync_read_consent, spreadsheet_id, sender_phone)
    except gspread.exceptions.APIError as error:
        logger.error(f"Error de API de gspread al leer consentimiento: {error}")
        return None
    except Exception as e:
        logger.error(f"Error inesperado al leer consentimiento: {e}")
        return None


async def registrar_consentimiento(sender_phone: str, estado: str) -> bool:
    """
    Registra la respuesta del usuario a la política (estado: 'aceptado' o 'rechazado').
    Retorna True si se persistió correctamente.
    """
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID
    try:
        await asyncio.to_thread(_sync_write_consent, spreadsheet_id, sender_phone, estado)
        logger.info(f"Consentimiento {estado} registrado para {sender_phone}.")
        return True
    except gspread.exceptions.APIError as error:
        logger.error(f"Error de API de gspread al registrar consentimiento: {error}")
        return False
    except Exception as e:
        logger.error(f"Error inesperado al registrar consentimiento: {e}")
        return False
