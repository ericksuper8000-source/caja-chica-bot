from unittest.mock import MagicMock, patch

import gspread
import pytest
from gspread.utils import ValueInputOption

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
    mock_spreadsheet.worksheet.return_value = mock_worksheet

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
async def test_append_transaction_crea_pestana_cliente_si_no_existe(mock_get_sheets_client):
    """
    ADR-0009 (6.5.2): si la pestaña del cliente (título = teléfono) no existe, se crea
    con los encabezados de transacción antes de insertar la fila.
    """
    mock_client = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_worksheet = MagicMock()

    mock_get_sheets_client.return_value = mock_client
    mock_client.open_by_key.return_value = mock_spreadsheet
    # La pestaña no existe -> se lanza WorksheetNotFound y se crea
    mock_spreadsheet.worksheet.side_effect = gspread.exceptions.WorksheetNotFound
    mock_spreadsheet.add_worksheet.return_value = mock_worksheet

    fake_transaction = {
        "monto": 3000,
        "categoria": "Alimentación",
        "tipo_movimiento": "Gasto",
        "detalle": "Panadería",
    }

    result = await append_transaction_to_sheet(fake_transaction, "50660646370")

    assert result is True
    # La pestaña se crea con el teléfono como título y los encabezados de transacción
    mock_spreadsheet.add_worksheet.assert_called_once_with(title="50660646370", rows=100, cols=10)
    mock_worksheet.append_row.assert_any_call(
        ["fecha", "monto", "categoria", "detalle", "telefono"],
        value_input_option=ValueInputOption.user_entered,
    )
    # Y la fila se inserta en esa misma pestaña
    inserted = mock_worksheet.append_row.call_args_list[-1].args[0]
    assert inserted[1] == -3000
    assert inserted[4] == "50660646370"


@pytest.mark.anyio
@patch("services.sheets_service.get_sheets_client")
async def test_append_transaction_escribe_en_pestana_del_cliente(mock_get_sheets_client):
    """
    ADR-0009 (6.5.2): la fila se inserta en la pestaña del remitente (título = teléfono),
    no en una hoja global.
    """
    mock_client = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_worksheet = MagicMock()

    mock_get_sheets_client.return_value = mock_client
    mock_client.open_by_key.return_value = mock_spreadsheet
    mock_spreadsheet.worksheet.return_value = mock_worksheet

    fake_transaction = {
        "monto": 500,
        "categoria": "Compras",
        "tipo_movimiento": "Gasto",
        "detalle": "Dos tejas de pan",
    }

    await append_transaction_to_sheet(fake_transaction, "50660646370")

    # Resolución de pestaña por teléfono
    mock_spreadsheet.worksheet.assert_called_once_with("50660646370")
    mock_worksheet.append_row.assert_called_once()


@pytest.mark.anyio
@patch("services.sheets_service.get_sheets_client")
async def test_update_last_transaction_usa_pestana_del_cliente(mock_get_sheets_client):
    """
    ADR-0009 (6.5.2): la corrección lee y actualiza SOLO la pestaña del remitente.
    """
    mock_client = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_worksheet = MagicMock()

    mock_get_sheets_client.return_value = mock_client
    mock_client.open_by_key.return_value = mock_spreadsheet
    mock_spreadsheet.worksheet.return_value = mock_worksheet

    mock_worksheet.col_values.return_value = ["teléfono", "50660646370"]
    mock_worksheet.row_values.return_value = [
        "2026-08-20 19:00:00",
        "-2000",
        "Alimentación",
        "almuerzo",
        "50660646370",
    ]

    fake_transaction = {
        "monto": 2500,
        "categoria": None,
        "tipo_movimiento": None,
        "detalle": None,
    }

    result = await update_last_transaction_to_sheet(fake_transaction, "50660646370")

    assert result == [-2500, "Alimentación", "almuerzo"]
    # Se resuelve la pestaña del cliente en la lectura y en la actualización
    assert mock_spreadsheet.worksheet.call_count == 2
    mock_spreadsheet.worksheet.assert_called_with("50660646370")


@pytest.mark.anyio
@patch("services.sheets_service.get_sheets_client")
async def test_append_transaction_cada_cliente_tiene_su_pestana(mock_get_sheets_client):
    """
    ADR-0009 (6.5.2): dos clientes distintos resuelven pestañas distintas (aislamiento).
    """
    mock_client = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_worksheet_a = MagicMock()
    mock_worksheet_b = MagicMock()

    mock_get_sheets_client.return_value = mock_client
    mock_client.open_by_key.return_value = mock_spreadsheet
    mock_spreadsheet.worksheet.side_effect = [mock_worksheet_a, mock_worksheet_b]

    base = {"categoria": "Ventas", "tipo_movimiento": "Ingreso", "detalle": "venta"}

    await append_transaction_to_sheet({**base, "monto": 1000}, "50611111111")
    await append_transaction_to_sheet({**base, "monto": 2000}, "50622222222")

    assert mock_spreadsheet.worksheet.call_args_list[0].args[0] == "50611111111"
    assert mock_spreadsheet.worksheet.call_args_list[1].args[0] == "50622222222"
    mock_worksheet_a.append_row.assert_called_once()
    mock_worksheet_b.append_row.assert_called_once()


@pytest.mark.anyio
@patch("services.sheets_service.get_sheets_client")
async def test_update_last_transaction_success(mock_get_sheets_client):
    """Prueba que la corrección localice la última fila del teléfono y actualice B:E."""
    mock_client = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_worksheet = MagicMock()

    mock_get_sheets_client.return_value = mock_client
    mock_client.open_by_key.return_value = mock_spreadsheet
    mock_spreadsheet.worksheet.return_value = mock_worksheet

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
    mock_spreadsheet.worksheet.return_value = mock_worksheet

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
    mock_spreadsheet.worksheet.return_value = mock_worksheet

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
    mock_spreadsheet.worksheet.return_value = mock_worksheet

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
