import pytest
from unittest.mock import MagicMock, patch
import gspread
from services.sheets_service import append_transaction_to_sheet, get_sheets_client


@patch("services.sheets_service.gspread.service_account")
def test_get_sheets_client_success(mock_service_account):
    """Prueba que el cliente de gspread se inicialice correctamente usando el archivo de entorno."""
    mock_client_instance = MagicMock()
    mock_service_account.return_value = mock_client_instance

    # Ejecutar la función
    client = get_sheets_client()

    # gspread busca automáticamente GOOGLE_APPLICATION_CREDENTIALS si se deja vacío
    mock_service_account.assert_called_once()
    assert client == mock_client_instance


@pytest.mark.asyncio
@patch("services.sheets_service.get_sheets_client")
async def test_append_transaction_gasto_success(mock_get_sheets_client):
    """Prueba la inserción exitosa de un Gasto transformando el monto a negativo."""
    # Configurar la cadena de mocks de gspread
    mock_client = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_worksheet = MagicMock()

    mock_get_sheets_client.return_value = mock_client
    mock_client.open_by_key.return_value = mock_spreadsheet
    mock_spreadsheet.get_worksheet.return_value = mock_worksheet

    # Datos de prueba provenientes del parser de IA
    fake_transaction = {
        "monto": 4500,
        "categoria": "Alimentación",
        "tipo_movimiento": "Gasto",
        "detalle": "Almuerzo ejecutivo",
    }

    # Ejecutar la función (Debe ser asíncrona usando run_in_executor por debajo)
    result = await append_transaction_to_sheet(fake_transaction)

    assert result is True
    mock_client.open_by_key.assert_called_once()
    mock_worksheet.append_row.assert_called_once()

    # Validar que los datos enviados a la fila de Google Sheets sean correctos
    called_args = mock_worksheet.append_row.call_args[0][0]

    # Estructura esperada: [Fecha/Timestamp, Monto, Categoría, Detalle]
    assert called_args[1] == -4500  # Transformado a negativo por ser un Gasto
    assert called_args[2] == "Alimentación"
    assert called_args[3] == "Almuerzo ejecutivo"


@pytest.mark.asyncio
@patch("services.sheets_service.get_sheets_client")
async def test_append_transaction_api_error(mock_get_sheets_client):
    """Prueba que el servicio maneje limpiamente un error de API (APIError) de gspread."""
    mock_client = MagicMock()
    mock_get_sheets_client.return_value = mock_client

    # Simular que gspread lanza un APIError (ej: permiso denegado o cuota excedida)
    fake_response = MagicMock(status_code=403, text="API Error")
    mock_client.open_by_key.side_effect = gspread.exceptions.APIError(fake_response)

    fake_transaction = {
        "monto": 1000,
        "categoria": "Otros",
        "tipo_movimiento": "Gasto",
        "detalle": "Error de prueba",
    }

    # Ejecutar la función
    result = await append_transaction_to_sheet(fake_transaction)

    # El servicio debe capturar el error y retornar False en lugar de tirar un crash
    assert result is False
