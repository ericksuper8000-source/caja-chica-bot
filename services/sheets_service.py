import logging
from datetime import datetime
from typing import Any, Dict
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from app.config import settings

logger = logging.getLogger(__name__)


def get_sheets_client():
    """
    Inicializa y devuelve el cliente autenticado de la API de Google Sheets
    utilizando las credenciales de la Cuenta de Servicio del .env.
    """
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    try:
        # Cargamos las credenciales desde el diccionario que parseó Pydantic
        creds = Credentials.from_service_account_info(
            settings.google_sheets_credentials_dict, scopes=scopes
        )
        # Construimos el servicio cliente oficial de Google
        service = build("sheets", "v4", credentials=creds)
        return service.spreadsheets()
    except Exception as e:
        logger.error(f"Error crítico al autenticar con Google Sheets: {e}")
        raise e


async def append_transaction_to_sheet(transaction_data: Dict[str, Any]) -> bool:
    """
    Inserta una nueva fila en la hoja de cálculo de Google Sheets con los datos
    de la transacción financiera provistos por el parser de OpenAI.

    Formatos esperados en transaction_data:
    {
        "monto": 5000,
        "categoria": "Transporte",
        "tipo_movimiento": "Gasto",
        "detalle": "Pasajes de autobús"
    }
    """
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID
    # El rango define el nombre de la hoja (Hoja 1 o Sheet1) y las columnas a usar
    range_name = "Hoja 1!A:D"
    value_input_option = "USER_ENTERED"

    try:
        sheets_client = get_sheets_client()

        # 1. Preparar la estampa de tiempo actual (Fecha y hora)
        fecha_actual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 2. Mapear los datos de la IA en el orden exacto de las columnas de la hoja
        # Columnas: Fecha | Monto (con signo según tipo) | Categoría | Detalle
        monto = transaction_data.get("monto", 0)
        tipo = transaction_data.get("tipo_movimiento", "Gasto")

        # Si es un gasto, lo guardamos como negativo para facilitar fórmulas matemáticas en Sheets
        if tipo.lower() == "gasto" and monto > 0:
            monto = -monto

        row_values = [
            fecha_actual,
            monto,
            transaction_data.get("categoria", "Otros"),
            transaction_data.get("detalle", ""),
        ]

        body = {"values": [row_values]}

        # 3. Ejecutar la llamada asíncrona simulada hacia los servidores de Google
        # (La librería oficial de Google es síncrona, pero la envolvemos limpiamente)
        request = sheets_client.values().append(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption=value_input_option,
            insertDataOption="INSERT_ROWS",
            body=body,
        )

        response = request.execute()
        logger.info(f"Fila insertada con éxito en Sheets. Response: {response}")
        return True

    except HttpError as error:
        logger.error(
            f"Error de API al escribir en Google Sheets (HttpError): {error.content}"
        )
        return False
    except Exception as e:
        logger.error(f"Error inesperado en el servicio de Sheets: {e}")
        return False
