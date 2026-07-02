import asyncio
import logging
from datetime import datetime
from typing import Any, Dict
import gspread
from app.config import settings

logger = logging.getLogger(__name__)


def get_sheets_client() -> gspread.Client:
    """
    Inicializa y devuelve el cliente autenticado de gspread.
    gspread detecta automáticamente la variable de entorno
    GOOGLE_APPLICATION_CREDENTIALS mapeada en el contenedor.
    """
    try:
        # gspread inicializa el cliente leyendo directamente el archivo del entorno
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
    Se aísla en una función interna para ser ejecutada dentro de un hilo secundario.
    """
    client = get_sheets_client()
    # Abre el documento usando el ID único del .env
    spreadsheet = client.open_by_key(spreadsheet_id)
    # Selecciona la primera hoja de trabajo (Hoja 1 / Sheet1)
    worksheet = spreadsheet.get_worksheet(0)
    # Inserta la fila al final de la hoja utilizando el formato por defecto de entrada del usuario
    worksheet.append_row(row_values, value_input_option="USER_ENTERED")


async def append_transaction_to_sheet(transaction_data: Dict[str, Any]) -> bool:
    """
    Inserta una nueva fila en la hoja de cálculo de Google Sheets de manera asíncrona,
    delegando la llamada bloqueante de gspread a un hilo secundario para evitar el starvation de Celery.
    """
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID

    try:
        # 1. Preparar la estampa de tiempo actual (Fecha y hora)
        fecha_actual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 2. Mapear y procesar la lógica contable (Gastos pasan a negativo)
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

        # 3. Delegación asíncrona a un hilo secundario no bloqueante
        # asyncio.to_thread ejecuta la función síncrona en el ThreadPoolExecutor por defecto
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
