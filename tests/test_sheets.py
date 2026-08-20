from unittest.mock import MagicMock, patch

import gspread
import pytest

from services.sheets_service import (
    append_transaction_to_sheet,
    get_sheets_client,
    update_last_transaction_to_sheet,
)


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


@pytest.mark.anyio
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
    result = await append_transaction_to_sheet(fake_transaction, "50688888888")

    assert result is True
    mock_client.open_by_key.assert_called_once()
    mock_worksheet.append_row.assert_called_once()

    # Validar que los datos enviados a la fila de Google Sheets sean correctos
    called_args = mock_worksheet.append_row.call_args[0][0]

    # Estructura esperada: [Fecha/Timestamp, Monto, Categoría, Detalle, Teléfono]
    assert called_args[1] == -4500  # Transformado a negativo por ser un Gasto
    assert called_args[2] == "Alimentación"
    assert called_args[3] == "Almuerzo ejecutivo"
    assert called_args[4] == "50688888888"


@pytest.mark.anyio
@patch("services.sheets_service.get_sheets_client")
async def test_update_last_transaction_success(mock_get_sheets_client):
    """Prueba que la corrección localice la última fila del teléfono y actualice B:E."""
    mock_client = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_worksheet = MagicMock()

    mock_get_sheets_client.return_value = mock_client
    mock_client.open_by_key.return_value = mock_spreadsheet
    mock_spreadsheet.get_worksheet.return_value = mock_worksheet

    # Columna de teléfono: encabezado + filas de otros usuarios + la del usuario (filas 3 y 5)
    mock_worksheet.col_values.return_value = [
        "teléfono",
        "50611111111",
        "50688888888",
        "50611111111",
        "50688888888",
    ]
    # Fila previa leída para el merge del delta: [fecha, monto, categoria, detalle, telefono]
    mock_worksheet.row_values.return_value = [
        "2026-08-13 21:00:00",
        "-2000",
        "Alimentación",
        "Almuerzo",
        "50688888888",
    ]

    fake_transaction = {
        "monto": 6000,
        "categoria": "Transporte",
        "tipo_movimiento": "Gasto",
        "detalle": "Pasajes",
    }

    result = await update_last_transaction_to_sheet(fake_transaction, "50688888888")

    assert result == [-6000, "Transporte", "Pasajes"]
    # Debe actualizar la última coincidencia (fila 5), columnas B:E, sin tocar la fecha
    called_args = mock_worksheet.update.call_args[0]
    assert called_args[0] == "B5:E5"
    assert called_args[1] == [[-6000, "Transporte", "Pasajes", "50688888888"]]


@pytest.mark.anyio
@patch("services.sheets_service.get_sheets_client")
async def test_update_last_transaction_correccion_parcial_preserva(mock_get_sheets_client):
    """
    Trampa H (hallazgo 13/08/2026): corrección de SOLO monto conserva la categoría y
    el detalle de la fila anterior. El LLM devuelve monto y el resto en None.
    """
    mock_client = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_worksheet = MagicMock()

    mock_get_sheets_client.return_value = mock_client
    mock_client.open_by_key.return_value = mock_spreadsheet
    mock_spreadsheet.get_worksheet.return_value = mock_worksheet

    mock_worksheet.col_values.return_value = [
        "teléfono",
        "50611111111",
        "50688888888",
    ]
    # Fila previa: un gasto de almuerzo registrado antes
    mock_worksheet.row_values.return_value = [
        "2026-08-13 21:32:54",
        "-2000",
        "Alimentación",
        "almuerzo",
        "50688888888",
    ]

    # Delta: solo corrige el monto; el resto viene null (no mencionado)
    fake_transaction = {
        "monto": 5000,
        "categoria": None,
        "tipo_movimiento": None,
        "detalle": None,
    }

    result = await update_last_transaction_to_sheet(fake_transaction, "50688888888")

    # El monto se corrige a -5000 (sigue siendo Gasto) y NO se pierden categoría/detalle
    assert result == [-5000, "Alimentación", "almuerzo"]
    called_args = mock_worksheet.update.call_args[0]
    assert called_args[1] == [[-5000, "Alimentación", "almuerzo", "50688888888"]]


@pytest.mark.anyio
@patch("services.sheets_service.get_sheets_client")
async def test_update_last_transaction_correccion_monto_cero_conserva(mock_get_sheets_client):
    """
    Hallazgo 20/08/2026: una corrección cuyo delta trae monto=0 (la IA lo inventó en vez
    de null) debe CONSERVAR el monto anterior, no pisarlo con 0.
    """
    mock_client = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_worksheet = MagicMock()

    mock_get_sheets_client.return_value = mock_client
    mock_client.open_by_key.return_value = mock_spreadsheet
    mock_spreadsheet.get_worksheet.return_value = mock_worksheet

    mock_worksheet.col_values.return_value = ["teléfono", "50611111111", "50688888888"]
    # Fila previa: un gasto de transporte de 6000
    mock_worksheet.row_values.return_value = [
        "2026-08-20 18:00:00",
        "-6000",
        "Transporte",
        "pasajes",
        "50688888888",
    ]

    fake_transaction = {
        "monto": 0,
        "categoria": None,
        "tipo_movimiento": None,
        "detalle": None,
    }

    result = await update_last_transaction_to_sheet(fake_transaction, "50688888888")

    # El monto anterior se conserva (-6000) y no se pisa con 0
    assert result == [-6000, "Transporte", "pasajes"]


@pytest.mark.anyio
@patch("services.sheets_service.get_sheets_client")
async def test_update_last_transaction_sin_previas(mock_get_sheets_client):
    """Prueba que si el usuario no tiene transacciones previas, devuelve None sin actualizar."""
    mock_client = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_worksheet = MagicMock()

    mock_get_sheets_client.return_value = mock_client
    mock_client.open_by_key.return_value = mock_spreadsheet
    mock_spreadsheet.get_worksheet.return_value = mock_worksheet

    # Solo encabezado y filas de otros usuarios
    mock_worksheet.col_values.return_value = ["teléfono", "50611111111", "50622222222"]

    fake_transaction = {
        "monto": 6000,
        "categoria": "Transporte",
        "tipo_movimiento": "Gasto",
        "detalle": "Pasajes",
    }

    result = await update_last_transaction_to_sheet(fake_transaction, "50688888888")

    assert result is None
    mock_worksheet.update.assert_not_called()


@pytest.mark.anyio
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
    result = await append_transaction_to_sheet(fake_transaction, "50688888888")

    # El servicio debe capturar el error y retornar False en lugar de tirar un crash
    assert result is False
