import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List
import gspread  # type: ignore
from app.config import settings

logger = logging.getLogger(__name__)


def get_sheets_client() -> Any:
    """
    Inicializa y devuelve el cliente autenticado de gspread.
    Usamos Any para evitar errores de validación de tipos externos en mypy.
    """
    try:
        # gspread inicializa el cliente leyendo directamente el archivo del entorno
        client: Any = gspread.service_account(
            filename=settings.GOOGLE_APPLICATION_CREDENTIALS
        )
        return client
    except Exception as e:
        logger.error(f"Error crítico al autenticar con gspread: {e}")
        raise e


def _sync_append_row(spreadsheet_id: str, row_values: List[Any]) -> None:
    """
    Operación puramente síncrona que interactúa con la API de Google Sheets.
    """
    client = get_sheets_client()
    # Abre el documento usando el ID único del .env
    spreadsheet = client.open_by_key(spreadsheet_id)
    # Selecciona la primera hoja de trabajo
    worksheet = spreadsheet.get_worksheet(0)
    # Inserta la fila al final de la hoja
    worksheet.append_row(row_values, value_input_option="USER_ENTERED")


async def append_transaction_to_sheet(transaction_data: Dict[str, Any]) -> bool:
    """
    Inserta una nueva fila en Google Sheets de manera asíncrona.
    """
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID

    try:
        # 1. Preparar la estampa de tiempo actual
        fecha_actual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 2. Mapear y procesar la lógica contable
        monto = transaction_data.get("monto", 0)
        tipo = transaction_data.get("tipo_movimiento", "Gasto")

        if isinstance(monto, (int, float)) and tipo.lower() == "gasto" and monto > 0:
            monto = -monto

        row_values: List[Any] = [
            fecha_actual,
            monto,
            transaction_data.get("categoria", "Otros"),
            transaction_data.get("detalle", ""),
        ]

        # 3. Delegación asíncrona
        await asyncio.to_thread(_sync_append_row, spreadsheet_id, row_values)

        logger.info(
            f"Fila insertada con éxito en Sheets de forma asíncrona: {row_values}"
        )
        return True

    except Exception as e:
        logger.error(f"Error inesperado en el servicio de Sheets: {e}")
        return False