from unittest.mock import AsyncMock, MagicMock, patch

import gspread
import pytest
from gspread.utils import ValueInputOption

from services.modelo_service import TRANSACTION_HEADERS
from services.sheets_service import (
    USUARIOS_HEADERS,
    append_transaction_to_sheet,
    get_sheets_client,
    obtener_transacciones_cliente,
    obtener_usuario,
    update_last_transaction_to_sheet,
    upsert_usuario,
)


def _fila_canonica(
    fecha: str,
    monto_centimos: int,
    categoria: str,
    detalle: str,
    telefono: str,
    *,
    movimiento_id: str = "mov-1",
    tipo: str = "gasto",
    estado: str = "confirmado",
    version: int = 1,
) -> list[object]:
    """Fila canónica de 13 columnas tal como se guarda en la pestaña del cliente."""
    return [
        fecha,
        monto_centimos,
        categoria,
        detalle,
        telefono,
        movimiento_id,
        tipo,
        "CRC",
        "personal",
        estado,
        version,
        fecha,
        "chat",
    ]


@patch("services.sheets_service._sheets_client", None)
@patch("services.sheets_service.gspread.service_account")
def test_get_sheets_client_success(mock_service_account):
    """Prueba que el cliente de gspread se inicialice correctamente usando el archivo de entorno."""
    mock_client_instance = MagicMock()
    mock_service_account.return_value = mock_client_instance

    # El cliente se cachea a nivel de módulo; forzamos None para que este test
    # ejercite la inicialización aunque la suite completa ya haya usado el cache.
    # Ejecutar la función
    client = get_sheets_client()

    # gspread busca automáticamente GOOGLE_APPLICATION_CREDENTIALS si se deja vacío
    mock_service_account.assert_called_once()
    assert client == mock_client_instance


@pytest.mark.anyio
@patch("services.sheets_service.registrar_auditoria", new_callable=AsyncMock)
@patch("services.sheets_service.get_sheets_client")
async def test_append_transaction_gasto_success(mock_get_sheets_client, mock_registrar_auditoria):
    """Prueba la inserción exitosa de un Gasto en el modelo canónico (céntimos + tipo)."""
    # Configurar la cadena de mocks de gspread
    mock_client = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_worksheet = MagicMock()

    mock_get_sheets_client.return_value = mock_client
    mock_client.open_by_key.return_value = mock_spreadsheet
    mock_spreadsheet.worksheet.return_value = mock_worksheet
    mock_worksheet.get_all_values.return_value = [TRANSACTION_HEADERS]

    # Datos de prueba provenientes del parser de IA
    fake_transaction = {
        "monto": 4500,
        "categoria": "Alimentación",
        "tipo_movimiento": "Gasto",
        "detalle": "Almuerzo ejecutivo",
    }

    # Ejecutar la función (Debe ser asíncrona usando run_in_executor por debajo)
    result = await append_transaction_to_sheet(fake_transaction, "50688888888")

    assert isinstance(result, dict)
    assert result["monto_centimos"] == 450000
    assert result["tipo_movimiento"] == "gasto"
    assert result["movimiento_id"]
    mock_client.open_by_key.assert_called_once()
    mock_worksheet.append_row.assert_called_once()
    mock_registrar_auditoria.assert_awaited_once()

    # Validar que los datos enviados a la fila canónica sean correctos
    called_args = mock_worksheet.append_row.call_args[0][0]

    # Estructura: [fecha, monto_centimos, categoría, detalle, teléfono, id, tipo, ...]
    assert called_args[1] == 450000  # céntimos positivos; el tipo define el signo
    assert called_args[2] == "Alimentación"
    assert called_args[3] == "Almuerzo ejecutivo"
    assert called_args[4] == "50688888888"
    assert called_args[6] == "gasto"
    assert called_args[9] == "confirmado"


@pytest.mark.anyio
@patch("services.sheets_service.registrar_auditoria", new_callable=AsyncMock)
@patch("services.sheets_service.get_sheets_client")
async def test_append_transaction_crea_pestana_cliente_si_no_existe(
    mock_get_sheets_client, mock_registrar_auditoria
):
    """
    ADR-0009 (6.5.2): si la pestaña del cliente (título = teléfono) no existe, se crea
    con el encabezado canónico antes de insertar la fila.
    """
    mock_client = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_worksheet = MagicMock()

    mock_get_sheets_client.return_value = mock_client
    mock_client.open_by_key.return_value = mock_spreadsheet
    # La pestaña no existe -> se lanza WorksheetNotFound y se crea
    mock_spreadsheet.worksheet.side_effect = gspread.exceptions.WorksheetNotFound
    mock_spreadsheet.add_worksheet.return_value = mock_worksheet
    mock_worksheet.get_all_values.return_value = [TRANSACTION_HEADERS]

    fake_transaction = {
        "monto": 3000,
        "categoria": "Alimentación",
        "tipo_movimiento": "Gasto",
        "detalle": "Panadería",
    }

    result = await append_transaction_to_sheet(fake_transaction, "50660646370")

    assert isinstance(result, dict)
    # La pestaña se crea con el teléfono como título y el encabezado canónico
    mock_spreadsheet.add_worksheet.assert_called_once_with(
        title="50660646370", rows=100, cols=len(TRANSACTION_HEADERS)
    )
    mock_worksheet.append_row.assert_any_call(
        TRANSACTION_HEADERS,
        value_input_option=ValueInputOption.user_entered,
    )
    # Y la fila se inserta en esa misma pestaña
    inserted = mock_worksheet.append_row.call_args_list[-1].args[0]
    assert inserted[1] == 300000
    assert inserted[4] == "50660646370"
    mock_registrar_auditoria.assert_awaited_once()


@pytest.mark.anyio
@patch("services.sheets_service.registrar_auditoria", new_callable=AsyncMock)
@patch("services.sheets_service.get_sheets_client")
async def test_append_transaction_escribe_en_pestana_del_cliente(
    mock_get_sheets_client, mock_registrar_auditoria
):
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
    mock_worksheet.get_all_values.return_value = [TRANSACTION_HEADERS]

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
@patch("services.sheets_service._sync_registrar_auditoria")
@patch("services.sheets_service.get_sheets_client")
async def test_update_last_transaction_usa_pestana_del_cliente(
    mock_get_sheets_client, mock_auditoria
):
    """
    ADR-0009 (6.5.2): la corrección lee y actualiza SOLO la pestaña del remitente.
    """
    mock_client = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_worksheet = MagicMock()

    mock_get_sheets_client.return_value = mock_client
    mock_client.open_by_key.return_value = mock_spreadsheet
    mock_spreadsheet.worksheet.return_value = mock_worksheet

    mock_worksheet.get_all_values.return_value = [
        TRANSACTION_HEADERS,
        _fila_canonica(
            "2026-08-20 19:00:00",
            200000,
            "Alimentación",
            "almuerzo",
            "50660646370",
            movimiento_id="mov-1",
        ),
    ]

    fake_transaction = {
        "monto": 2500,
        "categoria": None,
        "tipo_movimiento": None,
        "detalle": None,
    }

    result = await update_last_transaction_to_sheet(fake_transaction, "50660646370")

    assert result is not None
    assert result["monto"] == -2500
    assert result["categoria"] == "Alimentación"
    assert result["despues"]["estado"] == "corregido"
    assert result["despues"]["version"] == 2
    # Se resuelve la pestaña del cliente en la lectura y en la actualización
    assert mock_spreadsheet.worksheet.call_count == 2
    mock_spreadsheet.worksheet.assert_called_with("50660646370")
    mock_auditoria.assert_called_once()


@pytest.mark.anyio
@patch("services.sheets_service.registrar_auditoria", new_callable=AsyncMock)
@patch("services.sheets_service.get_sheets_client")
async def test_append_transaction_cada_cliente_tiene_su_pestana(
    mock_get_sheets_client, mock_registrar_auditoria
):
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
    mock_worksheet_a.get_all_values.return_value = [TRANSACTION_HEADERS]
    mock_worksheet_b.get_all_values.return_value = [TRANSACTION_HEADERS]

    base = {"categoria": "Ventas", "tipo_movimiento": "Ingreso", "detalle": "venta"}

    await append_transaction_to_sheet({**base, "monto": 1000}, "50611111111")
    await append_transaction_to_sheet({**base, "monto": 2000}, "50622222222")

    assert mock_spreadsheet.worksheet.call_args_list[0].args[0] == "50611111111"
    assert mock_spreadsheet.worksheet.call_args_list[1].args[0] == "50622222222"
    mock_worksheet_a.append_row.assert_called_once()
    mock_worksheet_b.append_row.assert_called_once()


@pytest.mark.anyio
@patch("services.sheets_service.get_sheets_client")
async def test_obtener_transacciones_cliente_retorna_filas(mock_get_sheets_client):
    """6.5.3/A02: 'exporta mis datos' lee la pestaña y normaliza al contrato canónico."""
    mock_client = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_worksheet = MagicMock()

    mock_get_sheets_client.return_value = mock_client
    mock_client.open_by_key.return_value = mock_spreadsheet
    mock_spreadsheet.worksheet.return_value = mock_worksheet

    mock_worksheet.get_all_values.return_value = [
        ["fecha", "monto", "categoria", "detalle", "telefono"],
        ["2026-08-20 19:29:13", "-3000", "Alimentación", "Tres perros calientes", "50660646370"],
    ]

    rows = await obtener_transacciones_cliente("50660646370")

    assert len(rows) == 1
    assert len(rows[0]) == len(TRANSACTION_HEADERS)
    assert rows[0][1] == 300000  # 3000 colones → 300000 céntimos
    assert rows[0][6] == "gasto"
    assert rows[0][9] == "confirmado"
    mock_spreadsheet.worksheet.assert_called_once_with("50660646370")


@pytest.mark.anyio
@patch("services.sheets_service.get_sheets_client")
async def test_obtener_transacciones_cliente_solo_encabezados(mock_get_sheets_client):
    """6.5.3: pestaña solo con encabezados devuelve lista vacía (sin movimientos)."""
    mock_client = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_worksheet = MagicMock()

    mock_get_sheets_client.return_value = mock_client
    mock_client.open_by_key.return_value = mock_spreadsheet
    mock_spreadsheet.worksheet.return_value = mock_worksheet

    mock_worksheet.get_all_values.return_value = [TRANSACTION_HEADERS]

    rows = await obtener_transacciones_cliente("50660646370")

    assert rows == []


@pytest.mark.anyio
@patch("services.sheets_service._sync_registrar_auditoria")
@patch("services.sheets_service.get_sheets_client")
async def test_update_last_transaction_success(mock_get_sheets_client, mock_auditoria):
    """La corrección reescribe la última fila activa completa (A:M) y sube la versión."""
    mock_client = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_worksheet = MagicMock()

    mock_get_sheets_client.return_value = mock_client
    mock_client.open_by_key.return_value = mock_spreadsheet
    mock_spreadsheet.worksheet.return_value = mock_worksheet

    mock_worksheet.get_all_values.return_value = [
        TRANSACTION_HEADERS,
        _fila_canonica(
            "2026-08-13 21:00:00",
            200000,
            "Alimentación",
            "Almuerzo",
            "50611111111",
            movimiento_id="mov-otro",
        ),
        _fila_canonica(
            "2026-08-13 21:00:00",
            200000,
            "Alimentación",
            "Almuerzo",
            "50688888888",
            movimiento_id="mov-1",
        ),
    ]

    fake_transaction = {
        "monto": 6000,
        "categoria": "Transporte",
        "tipo_movimiento": "Gasto",
        "detalle": "Pasajes",
    }

    result = await update_last_transaction_to_sheet(fake_transaction, "50688888888")

    assert result is not None
    assert result["monto"] == -6000
    assert result["categoria"] == "Transporte"
    assert result["despues"]["movimiento_id"] == "mov-1"
    assert result["despues"]["version"] == 2
    # Debe actualizar la fila 3 completa, sin tocar la fecha de movimiento
    called_args = mock_worksheet.update.call_args[0]
    assert called_args[0] == "A3:M3"
    fila = called_args[1][0]
    assert fila[0] == "2026-08-13 21:00:00"
    assert fila[1] == 600000
    assert fila[2] == "Transporte"
    assert fila[6] == "gasto"
    assert fila[9] == "corregido"
    assert fila[10] == 2


@pytest.mark.anyio
@patch("services.sheets_service._sync_registrar_auditoria")
@patch("services.sheets_service.get_sheets_client")
async def test_update_last_transaction_correccion_parcial_preserva(
    mock_get_sheets_client, mock_auditoria
):
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

    # Fila previa: un gasto de almuerzo registrado antes
    mock_worksheet.get_all_values.return_value = [
        TRANSACTION_HEADERS,
        _fila_canonica(
            "2026-08-13 21:32:54",
            200000,
            "Alimentación",
            "almuerzo",
            "50688888888",
            movimiento_id="mov-1",
        ),
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
    assert result is not None
    assert result["monto"] == -5000
    assert result["categoria"] == "Alimentación"
    assert result["detalle"] == "almuerzo"
    called_args = mock_worksheet.update.call_args[0]
    fila = called_args[1][0]
    assert fila[1] == 500000
    assert fila[2] == "Alimentación"
    assert fila[3] == "almuerzo"
    assert fila[6] == "gasto"


@pytest.mark.anyio
@patch("services.sheets_service._sync_registrar_auditoria")
@patch("services.sheets_service.get_sheets_client")
async def test_update_last_transaction_correccion_monto_cero_conserva(
    mock_get_sheets_client, mock_auditoria
):
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

    # Fila previa: un gasto de transporte de 6000
    mock_worksheet.get_all_values.return_value = [
        TRANSACTION_HEADERS,
        _fila_canonica(
            "2026-08-20 18:00:00",
            600000,
            "Transporte",
            "pasajes",
            "50688888888",
            movimiento_id="mov-1",
        ),
    ]

    fake_transaction = {
        "monto": 0,
        "categoria": None,
        "tipo_movimiento": None,
        "detalle": None,
    }

    result = await update_last_transaction_to_sheet(fake_transaction, "50688888888")

    # El monto anterior se conserva (-6000) y no se pisa con 0
    assert result is not None
    assert result["monto"] == -6000
    assert result["despues"]["monto_centimos"] == 600000


@pytest.mark.anyio
@patch("services.sheets_service._sync_registrar_auditoria")
@patch("services.sheets_service.get_sheets_client")
async def test_update_last_transaction_sin_previas(mock_get_sheets_client, mock_auditoria):
    """Prueba que si el usuario no tiene transacciones previas, devuelve None sin actualizar."""
    mock_client = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_worksheet = MagicMock()

    mock_get_sheets_client.return_value = mock_client
    mock_client.open_by_key.return_value = mock_spreadsheet
    mock_spreadsheet.worksheet.return_value = mock_worksheet

    # Solo encabezado canónico, sin movimientos
    mock_worksheet.get_all_values.return_value = [TRANSACTION_HEADERS]

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

    # El servicio debe capturar el error y retornar None en lugar de tirar un crash
    assert result is None


@pytest.mark.anyio
@patch("services.sheets_service.get_sheets_client")
async def test_upsert_usuario_crea_fila(mock_get_sheets_client):
    mock_client = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_worksheet = MagicMock()
    mock_get_sheets_client.return_value = mock_client
    mock_client.open_by_key.return_value = mock_spreadsheet
    mock_spreadsheet.worksheet.return_value = mock_worksheet
    mock_worksheet.col_values.return_value = ["telefono"]

    result = await upsert_usuario(
        {
            "telefono": "50688888888",
            "tipo_uso": "negocio",
            "espacio": "Mi Tienda",
            "pais": "Costa Rica",
            "moneda": "CRC",
            "zona": "America/Costa_Rica",
            "categorias": "Ventas, Otros",
        }
    )

    assert result is True
    fila = mock_worksheet.append_row.call_args.args[0]
    assert fila[0] == "50688888888"
    assert fila[1] == ""
    assert fila[2] == "negocio"
    assert fila[3] == "Mi Tienda"
    assert fila[4] == "Costa Rica"
    assert fila[5] == "CRC"
    assert fila[6] == "America/Costa_Rica"
    assert fila[7] == "Ventas, Otros"
    assert fila[8]
    mock_worksheet.update.assert_not_called()


@pytest.mark.anyio
@patch("services.sheets_service.get_sheets_client")
async def test_upsert_usuario_actualiza_fila_existente(mock_get_sheets_client):
    mock_client = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_worksheet = MagicMock()
    mock_get_sheets_client.return_value = mock_client
    mock_client.open_by_key.return_value = mock_spreadsheet
    mock_spreadsheet.worksheet.return_value = mock_worksheet
    mock_worksheet.col_values.return_value = ["telefono", "50688888888"]

    result = await upsert_usuario({"telefono": "50688888888", "espacio": "Nuevo Nombre"})

    assert result is True
    rango, filas = mock_worksheet.update.call_args.args
    assert rango == "A2:I2"
    assert filas[0][0] == "50688888888"
    assert filas[0][3] == "Nuevo Nombre"
    mock_worksheet.append_row.assert_not_called()


@pytest.mark.anyio
async def test_upsert_usuario_sin_telefono():
    assert await upsert_usuario({"tipo_uso": "personal"}) is False


@pytest.mark.anyio
@patch("services.sheets_service.get_sheets_client")
async def test_obtener_usuario_existente(mock_get_sheets_client):
    mock_client = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_worksheet = MagicMock()
    mock_get_sheets_client.return_value = mock_client
    mock_client.open_by_key.return_value = mock_spreadsheet
    mock_spreadsheet.worksheet.return_value = mock_worksheet
    mock_worksheet.col_values.return_value = ["telefono", "50688888888"]
    mock_worksheet.row_values.return_value = [
        "50688888888",
        "",
        "negocio",
        "Mi Tienda",
        "Costa Rica",
        "CRC",
        "America/Costa_Rica",
        "Ventas, Otros",
        "2026-11-01 10:00:00",
    ]

    usuario = await obtener_usuario("50688888888")

    assert usuario is not None
    assert usuario["telefono"] == "50688888888"
    assert usuario["espacio"] == "Mi Tienda"
    assert usuario["categorias"] == "Ventas, Otros"
    assert list(usuario.keys()) == USUARIOS_HEADERS


@pytest.mark.anyio
@patch("services.sheets_service.get_sheets_client")
async def test_obtener_usuario_inexistente(mock_get_sheets_client):
    mock_client = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_worksheet = MagicMock()
    mock_get_sheets_client.return_value = mock_client
    mock_client.open_by_key.return_value = mock_spreadsheet
    mock_spreadsheet.worksheet.return_value = mock_worksheet
    mock_worksheet.col_values.return_value = ["telefono"]

    assert await obtener_usuario("50699999999") is None
