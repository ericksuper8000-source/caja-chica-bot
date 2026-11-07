from unittest.mock import MagicMock, patch

import gspread

from services.sheets_service import (
    PREFERENCIAS_HEADERS,
    PRESUPUESTOS_HEADERS,
    _sync_eliminar_presupuesto,
    _sync_guardar_preferencia_resumen,
    _sync_guardar_presupuesto,
    _sync_leer_preferencia_resumen,
    _sync_marcar_alerta_presupuesto,
)


def _worksheet_con(filas: list[list[str]]) -> MagicMock:
    worksheet = MagicMock()
    worksheet.get_all_values.return_value = filas
    return worksheet


def _mock_spreadsheet(worksheet: MagicMock) -> MagicMock:
    spreadsheet = MagicMock()
    spreadsheet.worksheet.return_value = worksheet
    return spreadsheet


def _fila_presupuesto(telefono: str = "50670000000", categoria: str = "transporte") -> list[str]:
    return [telefono, categoria, "50000", "mensual", "", "", "2026-11-01 10:00:00"]


@patch("services.sheets_service.get_sheets_client")
def test_guardar_presupuesto_actualiza_fila_existente(mock_client) -> None:
    worksheet = _worksheet_con([PRESUPUESTOS_HEADERS, _fila_presupuesto()])
    mock_client.return_value.open_by_key.return_value = _mock_spreadsheet(worksheet)

    assert _sync_guardar_presupuesto("id", "50670000000", "transporte", 60000) is True
    worksheet.update_cell.assert_any_call(2, 3, 60000)
    worksheet.append_row.assert_not_called()


@patch("services.sheets_service.get_sheets_client")
def test_guardar_presupuesto_agrega_fila_nueva(mock_client) -> None:
    worksheet = _worksheet_con([PRESUPUESTOS_HEADERS])
    mock_client.return_value.open_by_key.return_value = _mock_spreadsheet(worksheet)

    assert _sync_guardar_presupuesto("id", "50670000000", "transporte", 50000) is True
    fila = worksheet.append_row.call_args.args[0]
    assert fila[:4] == ["50670000000", "transporte", 50000, "mensual"]


@patch("services.sheets_service.get_sheets_client")
def test_eliminar_presupuesto_borra_la_fila(mock_client) -> None:
    worksheet = _worksheet_con(
        [
            PRESUPUESTOS_HEADERS,
            _fila_presupuesto(),
            _fila_presupuesto(telefono="50688888888"),
        ]
    )
    mock_client.return_value.open_by_key.return_value = _mock_spreadsheet(worksheet)

    assert _sync_eliminar_presupuesto("id", "50670000000", "transporte") is True
    worksheet.delete_rows.assert_called_once_with(2)


@patch("services.sheets_service.get_sheets_client")
def test_eliminar_presupuesto_ignora_tildes(mock_client) -> None:
    worksheet = _worksheet_con([PRESUPUESTOS_HEADERS, _fila_presupuesto(categoria="Alimentación")])
    mock_client.return_value.open_by_key.return_value = _mock_spreadsheet(worksheet)

    assert _sync_eliminar_presupuesto("id", "50670000000", "alimentacion") is True
    worksheet.delete_rows.assert_called_once_with(2)


@patch("services.sheets_service.get_sheets_client")
def test_marcar_alerta_usa_la_columna_del_umbral(mock_client) -> None:
    worksheet = _worksheet_con([PRESUPUESTOS_HEADERS, _fila_presupuesto()])
    mock_client.return_value.open_by_key.return_value = _mock_spreadsheet(worksheet)

    assert _sync_marcar_alerta_presupuesto("id", "50670000000", "transporte", 80, "2026-11")
    assert _sync_marcar_alerta_presupuesto("id", "50670000000", "transporte", 100, "2026-11")
    worksheet.update_cell.assert_any_call(2, 5, "2026-11")
    worksheet.update_cell.assert_any_call(2, 6, "2026-11")


@patch("services.sheets_service.get_sheets_client")
def test_marcar_alerta_ignora_tildes_y_mayusculas(mock_client) -> None:
    """Caso real del 07/11: el pipeline pasa 'Alimentación' y la fila dice 'alimentacion'."""
    worksheet = _worksheet_con([PRESUPUESTOS_HEADERS, _fila_presupuesto(categoria="alimentacion")])
    mock_client.return_value.open_by_key.return_value = _mock_spreadsheet(worksheet)

    assert _sync_marcar_alerta_presupuesto("id", "50670000000", "Alimentación", 80, "2026-11")
    worksheet.update_cell.assert_called_once_with(2, 5, "2026-11")


@patch("services.sheets_service.get_sheets_client")
def test_leer_preferencia_resumen(mock_client) -> None:
    worksheet = MagicMock()
    worksheet.col_values.return_value = ["telefono", "50670000000"]
    worksheet.row_values.return_value = ["50670000000", "no", "2026-11-07 10:00:00"]
    mock_client.return_value.open_by_key.return_value = _mock_spreadsheet(worksheet)

    assert _sync_leer_preferencia_resumen("id", "50670000000") == "no"
    assert _sync_leer_preferencia_resumen("id", "50699999999") is None


@patch("services.sheets_service.get_sheets_client")
def test_guardar_preferencia_actualiza_o_crea(mock_client) -> None:
    worksheet = MagicMock()
    worksheet.col_values.return_value = ["telefono", "50670000000"]
    mock_client.return_value.open_by_key.return_value = _mock_spreadsheet(worksheet)

    assert _sync_guardar_preferencia_resumen("id", "50670000000", False) is True
    worksheet.update_cell.assert_any_call(2, 2, "no")

    worksheet.col_values.return_value = ["telefono"]
    assert _sync_guardar_preferencia_resumen("id", "50670000000", True) is True
    fila = worksheet.append_row.call_args.args[0]
    assert fila[:2] == ["50670000000", "si"]
    assert PREFERENCIAS_HEADERS == ["telefono", "resumen_semanal", "actualizado"]


def test_headers_esperados() -> None:
    assert PRESUPUESTOS_HEADERS[0:4] == ["telefono", "categoria", "limite", "periodo"]
    assert isinstance(gspread.exceptions.WorksheetNotFound, type)
