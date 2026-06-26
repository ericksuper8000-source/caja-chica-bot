import pytest
from unittest.mock import MagicMock, patch
from googleapiclient.errors import HttpError
from services.sheets_service import append_transaction_to_sheet, get_sheets_client


@patch("services.sheets_service.build")
@patch("services.sheets_service.Credentials")
def test_get_sheets_client_success(mock_credentials, mock_build):
    """Prueba que el cliente de Google Sheets se inicialice correctamente."""
    # Configurar los mocks
    mock_creds_instance = MagicMock()
    mock_credentials.from_service_account_info.return_value = mock_creds_instance

    mock_service_instance = MagicMock()
    mock_build.return_value = mock_service_instance

    # Ejecutar la función
    client = get_sheets_client()

    # Verificar que se llamaron a los constructores oficiales de Google con los datos parseados
    mock_credentials.from_service_account_info.assert_called_once()
    mock_build.assert_called_once_with("sheets", "v4", credentials=mock_creds_instance)
    assert client == mock_service_instance.spreadsheets()


@pytest.mark.asyncio
@patch("services.sheets_service.get_sheets_client")
async def test_append_transaction_gasto_success(mock_get_sheets_client):
    """Prueba la inserción exitosa de un Gasto (debe transformarse a negativo)."""
    # Simular el comportamiento del cliente de Google
    mock_spreadsheets = MagicMock()
    mock_values = MagicMock()
    mock_append = MagicMock()

    mock_get_sheets_client.return_value = mock_spreadsheets
    mock_spreadsheets.values.return_value = mock_values
    mock_values.append.return_value = mock_append
    mock_append.execute.return_value = {"spreadsheetId": "mock_id", "updatedRows": 1}

    # Datos de prueba provenientes del parser de IA
    fake_transaction = {
        "monto": 4500,
        "categoria": "Alimentación",
        "tipo_movimiento": "Gasto",
        "detalle": "Almuerzo ejecutivo",
    }

    # Ejecutar la función bajo prueba
    result = await append_transaction_to_sheet(fake_transaction)

    # Verificar el resultado y que el monto se transformó a NEGATIVO
    assert result is True
    mock_values.append.assert_called_once()

    # Extraer el cuerpo que se le envió a Google para validar la lógica contable
    called_kwargs = mock_values.append.call_args[1]
    inserted_row = called_kwargs["body"]["values"][0]

    assert inserted_row[1] == -4500  # El monto de 4500 pasó a -4500
    assert inserted_row[2] == "Alimentación"
    assert inserted_row[3] == "Almuerzo ejecutivo"


@pytest.mark.asyncio
@patch("services.sheets_service.get_sheets_client")
async def test_append_transaction_api_error(mock_get_sheets_client):
    """Prueba que el servicio maneje limpiamente un error de API (HttpError) de Google."""
    mock_spreadsheets = MagicMock()
    mock_values = MagicMock()
    mock_append = MagicMock()

    mock_get_sheets_client.return_value = mock_spreadsheets
    mock_spreadsheets.values.return_value = mock_values
    mock_values.append.return_value = mock_append

    # Simular que Google responde con un error HTTP (ej. Token expirado o Permiso denegado)
    fake_response = MagicMock(status=403, reason="Forbidden")
    mock_append.execute.side_effect = HttpError(
        resp=fake_response, content=b"Permission denied"
    )

    fake_transaction = {
        "monto": 1000,
        "categoria": "Otros",
        "tipo_movimiento": "Gasto",
        "detalle": "Error de prueba",
    }

    # Ejecutar la función
    result = await append_transaction_to_sheet(fake_transaction)

    # El servicio no debe caerse con un crash (Internal Server Error), debe retornar False limpiamente
    assert result is False
