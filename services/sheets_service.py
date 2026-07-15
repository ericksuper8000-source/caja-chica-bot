import asyncio
import logging
from datetime import datetime
from typing import Any, Dict
import gspread
from gspread.utils import ValueInputOption  # Importamos el enumerado para el tipado
from app.config import settings

logger = logging.getLogger(__name__)


def get_sheets_client() -> gspread.Client:
    """
    Inicializa y devuelve el cliente autenticado de gspread.
    """
    try:
        client = gspread.service_account(
            filename=settings.GOOGLE_APPLICATION_CREDENTIALS
        )
        return client
    except Exception as e:
        logger.error(f"Error crítico al autenticar con gspread: {e}")
        raise e


def _sync_append_row(spreadsheet_id: str, row_values: list) -> None:
    """
    Operación puramente síncrona que interactúa con la API de Google Sheets.
    """
    client = get_sheets_client()
    spreadsheet = client.open_by_key(spreadsheet_id)
    worksheet = spreadsheet.get_worksheet(0)
    
    # Se utiliza ValueInputOption.user_entered para cumplir con el tipado de mypy
    worksheet.append_row(row_values, value_input_option=ValueInputOption.user_entered)


async def append_transaction_to_sheet(transaction_data: Dict[str, Any]) -> bool:
    """
    Inserta una nueva fila en Google Sheets de manera asíncrona.
    """
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID

    try:
        fecha_actual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        monto = transaction_data.get("monto", 0)
        tipo = transaction_data.get("tipo_movimiento", "Gasto")

        if tipo.lower() == "gasto" and monto > 0:
            monto = -monto

        row_values = [
            fecha_actual,
            monto,
            transaction_data.get("categoria", "Otros"),
            transaction_data.get("detalle", ""),
        ]

        await asyncio.to_thread(_sync_append_row, spreadsheet_id, row_values)

        logger.info(
            f"Fila insertada con éxito en Sheets de forma asíncrona: {row_values}"
        )
        return True

    except gspread.exceptions.APIError as error:
        logger.error(f"Error de API de gspread al escribir en Google Sheets: {error}")
        return False
    except Exception as e:
        logger.error(f"Error inesperado en el servicio de Sheets: {e}")
        return False