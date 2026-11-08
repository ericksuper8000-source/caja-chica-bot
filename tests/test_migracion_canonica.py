"""
Tests de integración de la migración canónica y de las operaciones A08 sobre una
pestaña simulada. No tocan Google Sheets real: usan un cliente falso con la misma
superficie que usa `sheets_service` (worksheet/get_all_values/update/append_row).

Cubren la evidencia de la Tarea 1: filas y totales antes/después de migrar, IDs
estables, auditoría de la migración, anulación/reactivación/deshacer e historial
filtrado por actor.
"""

import re
from typing import Any

import gspread
import pytest

from services.modelo_service import TRANSACTION_HEADERS
from services.sheets_service import (
    AUDITORIA_HEADERS,
    AUDITORIA_TAB_NAME,
    MovimientoAnuladoError,
    anular_movimiento,
    append_transaction_to_sheet,
    migrar_pestana_cliente,
    obtener_historial,
    obtener_movimientos_cliente,
    obtener_transacciones_cliente,
    reactivar_movimiento,
    restaurar_movimiento,
    revertir_movimiento,
    update_last_transaction_to_sheet,
)

TELEFONO = "50688888888"
OTRO_TELEFONO = "50677777777"


class FakeWorksheet:
    """Pestaña en memoria con la superficie mínima que usa el servicio."""

    def __init__(self, title: str, filas: list[list[Any]] | None = None) -> None:
        self.title = title
        self.rows: list[list[Any]] = [list(fila) for fila in (filas or [])]
        self.updates: list[tuple[str, list[list[Any]]]] = []
        self.clears: list[str] = []

    def get_all_values(self) -> list[list[str]]:
        """Emula gspread: valores texto y celdas vacías del final recortadas."""
        resultado: list[list[str]] = []
        for fila in self.rows:
            valores = ["" if valor is None else str(valor) for valor in fila]
            while valores and valores[-1] == "":
                valores.pop()
            resultado.append(valores)
        while resultado and not any(resultado[-1]):
            resultado.pop()
        return resultado

    def update(
        self,
        rango: str,
        valores: list[list[Any]],
        value_input_option: Any = None,
    ) -> None:
        coincidencia = re.fullmatch(r"A(\d+):M(\d+)", rango)
        assert coincidencia, f"rango inesperado: {rango}"
        inicio, fin = int(coincidencia.group(1)), int(coincidencia.group(2))
        assert len(valores) == fin - inicio + 1, f"filas no coinciden con {rango}"
        self.updates.append((rango, [list(fila) for fila in valores]))
        while len(self.rows) < fin:
            self.rows.append([])
        for desplazamiento, fila in enumerate(valores):
            self.rows[inicio - 1 + desplazamiento] = list(fila)

    def append_row(self, valores: list[Any], value_input_option: Any = None) -> None:
        self.rows.append(list(valores))

    def batch_clear(self, rangos: list[str]) -> None:
        self.clears.extend(rangos)
        for rango in rangos:
            coincidencia = re.fullmatch(r"A(\d+):M(\d+)", rango)
            assert coincidencia, f"rango inesperado: {rango}"
            inicio, fin = int(coincidencia.group(1)), int(coincidencia.group(2))
            del self.rows[inicio - 1 : fin]


class FakeSpreadsheet:
    def __init__(self) -> None:
        self.tabs: dict[str, FakeWorksheet] = {}

    def worksheet(self, title: str) -> FakeWorksheet:
        if title not in self.tabs:
            raise gspread.exceptions.WorksheetNotFound(title)
        return self.tabs[title]

    def add_worksheet(self, title: str, rows: int = 100, cols: int = 10) -> FakeWorksheet:
        worksheet = FakeWorksheet(title)
        self.tabs[title] = worksheet
        return worksheet


class FakeClient:
    def __init__(self, spreadsheet: FakeSpreadsheet) -> None:
        self.spreadsheet = spreadsheet

    def open_by_key(self, key: str) -> FakeSpreadsheet:
        return self.spreadsheet


@pytest.fixture
def sheets(monkeypatch: pytest.MonkeyPatch) -> FakeSpreadsheet:
    """Cliente falso de Sheets; gana sobre el bloqueo global de `conftest.py`."""
    spreadsheet = FakeSpreadsheet()
    client = FakeClient(spreadsheet)
    monkeypatch.setattr("services.sheets_service.get_sheets_client", lambda: client)
    return spreadsheet


def _fila_canonica(
    fecha: str,
    monto_centimos: int,
    categoria: str,
    detalle: str,
    *,
    movimiento_id: str,
    tipo: str = "gasto",
    estado: str = "confirmado",
    version: int = 1,
    telefono: str = TELEFONO,
) -> list[Any]:
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


def _tab_legacy() -> FakeWorksheet:
    return FakeWorksheet(
        TELEFONO,
        [
            ["fecha", "monto", "categoria", "detalle", "telefono"],
            ["2026-08-20 19:29:13", "-3000", "Alimentación", "Tres perros", TELEFONO],
            ["2026-08-20 19:30:00", "2500", "Ventas", "camisetas", TELEFONO],
        ],
    )


def _tab_canonica() -> FakeWorksheet:
    return FakeWorksheet(
        TELEFONO,
        [
            TRANSACTION_HEADERS,
            _fila_canonica(
                "2026-08-20 19:29:13",
                300000,
                "Alimentación",
                "Tres perros",
                movimiento_id="mov-1",
            ),
            _fila_canonica(
                "2026-08-20 19:30:00",
                250000,
                "Ventas",
                "camisetas",
                movimiento_id="mov-2",
                tipo="ingreso",
            ),
        ],
    )


async def test_append_en_pestana_legacy_migra_y_audita(sheets: FakeSpreadsheet) -> None:
    worksheet = _tab_legacy()
    sheets.tabs[TELEFONO] = worksheet

    resultado = await append_transaction_to_sheet(
        {
            "monto": 4500,
            "categoria": "Transporte",
            "tipo_movimiento": "Gasto",
            "detalle": "taxi",
        },
        TELEFONO,
    )

    assert resultado is not None
    assert resultado["monto_centimos"] == 450000

    filas = worksheet.get_all_values()
    assert filas[0] == TRANSACTION_HEADERS
    assert len(filas) == 4

    # Fila 1: gasto histórico migrado a céntimos positivos, con ID y estado.
    assert filas[1][1] == "300000"
    assert filas[1][5]
    assert filas[1][6] == "gasto"
    assert filas[1][9] == "confirmado"
    # Fila 2: ingreso histórico.
    assert filas[2][1] == "250000"
    assert filas[2][6] == "ingreso"
    # Fila 3: movimiento nuevo appendido.
    assert filas[3][1] == "450000"
    assert filas[3][4] == TELEFONO
    assert filas[3][6] == "gasto"
    assert filas[3][12] == "chat"

    auditoria = sheets.tabs[AUDITORIA_TAB_NAME]
    registros = auditoria.get_all_values()
    assert registros[0] == AUDITORIA_HEADERS
    assert len(registros) == 3

    migracion = registros[1]
    assert migracion[1] == "pestana"
    assert migracion[2] == TELEFONO
    assert migracion[3] == "crear"
    assert migracion[6] == "sistema"
    assert migracion[7] == "migracion_esquema_canonico"
    assert '"filas_antes": 2' in migracion[5]
    assert '"filas_despues": 2' in migracion[5]
    assert '"cuadra": true' in migracion[5]

    creacion = registros[2]
    assert creacion[1] == "movimiento"
    assert creacion[2] == resultado["movimiento_id"]
    assert creacion[3] == "crear"
    assert creacion[6] == TELEFONO


async def test_migracion_explicita_reporta_conciliacion_y_es_idempotente(
    sheets: FakeSpreadsheet,
) -> None:
    worksheet = _tab_legacy()
    sheets.tabs[TELEFONO] = worksheet

    reporte = await migrar_pestana_cliente(TELEFONO)

    assert reporte is not None
    assert reporte["migrada"] is True
    assert reporte["filas_antes"] == 2
    assert reporte["filas_despues"] == 2
    assert reporte["gastos_antes_centimos"] == 300000
    assert reporte["gastos_despues_centimos"] == 300000
    assert reporte["ingresos_antes_centimos"] == 250000
    assert reporte["ingresos_despues_centimos"] == 250000
    assert reporte["cuadra"] is True
    assert len(worksheet.get_all_values()) == 3

    segundo = await migrar_pestana_cliente(TELEFONO)

    assert segundo is not None
    assert segundo["migrada"] is False
    assert segundo["filas_antes"] == 2
    assert segundo["cuadra"] is True


async def test_correccion_en_pestana_legacy_migra_y_actualiza_ultima_fila(
    sheets: FakeSpreadsheet,
) -> None:
    worksheet = _tab_legacy()
    sheets.tabs[TELEFONO] = worksheet

    resultado = await update_last_transaction_to_sheet(
        {"monto": 6000, "categoria": None, "tipo_movimiento": None, "detalle": None},
        TELEFONO,
    )

    assert resultado is not None
    assert resultado["monto"] == 6000  # era un ingreso de Ventas; solo cambia el monto
    assert resultado["categoria"] == "Ventas"
    assert resultado["detalle"] == "camisetas"
    assert resultado["despues"]["estado"] == "corregido"
    assert resultado["despues"]["version"] == 2

    filas = worksheet.get_all_values()
    assert filas[0] == TRANSACTION_HEADERS
    # La última fila activa (histórica ingreso) pasa a 6000 conservando el tipo ingreso.
    assert filas[2][1] == "600000"
    assert filas[2][6] == "ingreso"
    assert filas[2][9] == "corregido"

    acciones = [fila[3] for fila in sheets.tabs[AUDITORIA_TAB_NAME].get_all_values()[1:]]
    assert acciones == ["crear", "corregir"]


async def test_anular_excluye_de_lecturas_y_registra_auditoria(
    sheets: FakeSpreadsheet,
) -> None:
    sheets.tabs[TELEFONO] = _tab_canonica()

    resultado = await anular_movimiento(TELEFONO, "mov-1", motivo="no era suyo")

    assert resultado is not None
    assert resultado["antes"]["estado"] == "confirmado"
    assert resultado["despues"]["estado"] == "anulado"
    assert resultado["despues"]["version"] == 2

    activas = await obtener_transacciones_cliente(TELEFONO)
    assert len(activas) == 1
    assert activas[0][5] == "mov-2"

    todas = await obtener_transacciones_cliente(TELEFONO, incluir_inactivos=True)
    assert len(todas) == 2
    assert {fila[5] for fila in todas} == {"mov-1", "mov-2"}

    historial = await obtener_historial(TELEFONO)
    assert len(historial) == 1
    assert historial[0]["accion"] == "anular"
    assert historial[0]["entidad_id"] == "mov-1"
    assert historial[0]["motivo"] == "no era suyo"
    assert historial[0]["antes"]["estado"] == "confirmado"
    assert historial[0]["despues"]["estado"] == "anulado"


async def test_reactivar_y_deshacer_restauran_estado(sheets: FakeSpreadsheet) -> None:
    sheets.tabs[TELEFONO] = _tab_canonica()
    await anular_movimiento(TELEFONO, "mov-2", motivo="error")

    deshecho = await restaurar_movimiento(TELEFONO, "mov-2")

    assert deshecho is not None
    assert deshecho["despues"]["estado"] == "confirmado"
    assert deshecho["despues"]["version"] == 3

    sin_cambio = await reactivar_movimiento(TELEFONO, "mov-2")

    assert sin_cambio is not None
    assert sin_cambio["sin_cambio"] is True

    acciones = [fila[3] for fila in sheets.tabs[AUDITORIA_TAB_NAME].get_all_values()[1:]]
    assert acciones == ["anular", "deshacer"]


async def test_corregir_todo_anulado_lanza_movimiento_anulado(
    sheets: FakeSpreadsheet,
) -> None:
    sheets.tabs[TELEFONO] = FakeWorksheet(
        TELEFONO,
        [
            TRANSACTION_HEADERS,
            _fila_canonica(
                "2026-08-20 19:29:13",
                300000,
                "Alimentación",
                "Tres perros",
                movimiento_id="mov-1",
                estado="anulado",
            ),
        ],
    )

    with pytest.raises(MovimientoAnuladoError) as error:
        await update_last_transaction_to_sheet(
            {"monto": 1000, "categoria": None, "tipo_movimiento": None, "detalle": None},
            TELEFONO,
        )

    assert error.value.movimiento["movimiento_id"] == "mov-1"


async def test_historial_filtra_por_actor(sheets: FakeSpreadsheet) -> None:
    primero = await append_transaction_to_sheet(
        {"monto": 1000, "categoria": "Ventas", "tipo_movimiento": "Ingreso", "detalle": "a"},
        TELEFONO,
    )
    segundo = await append_transaction_to_sheet(
        {"monto": 2000, "categoria": "Ventas", "tipo_movimiento": "Ingreso", "detalle": "b"},
        TELEFONO,
    )
    await append_transaction_to_sheet(
        {"monto": 3000, "categoria": "Compras", "tipo_movimiento": "Gasto", "detalle": "c"},
        OTRO_TELEFONO,
    )

    assert primero is not None
    assert segundo is not None

    historial = await obtener_historial(TELEFONO)

    assert len(historial) == 2
    assert {entrada["actor_id"] for entrada in historial} == {TELEFONO}
    assert {entrada["entidad_id"] for entrada in historial} == {
        primero["movimiento_id"],
        segundo["movimiento_id"],
    }
    assert all(entrada["accion"] == "crear" for entrada in historial)

    ultimo = await obtener_historial(TELEFONO, limite=1)
    assert len(ultimo) == 1
    assert ultimo[0]["entidad_id"] == segundo["movimiento_id"]


async def test_obtener_movimientos_cliente_devuelve_dicts_sin_fila(
    sheets: FakeSpreadsheet,
) -> None:
    sheets.tabs[TELEFONO] = _tab_canonica()

    movimientos = await obtener_movimientos_cliente(TELEFONO)

    assert len(movimientos) == 2
    assert all("_fila" not in movimiento for movimiento in movimientos)
    assert movimientos[0]["movimiento_id"] == "mov-1"
    assert movimientos[0]["monto_centimos"] == 300000
    assert movimientos[1]["tipo_movimiento"] == "ingreso"

    activos = await obtener_movimientos_cliente(TELEFONO, incluir_inactivos=False)
    assert len(activos) == 2


async def test_revertir_correccion_restaura_snapshot_y_audita_deshacer(
    sheets: FakeSpreadsheet,
) -> None:
    sheets.tabs[TELEFONO] = _tab_canonica()

    correccion = await update_last_transaction_to_sheet(
        {"monto": 5000, "categoria": "Transporte", "detalle": "taxi"},
        TELEFONO,
    )
    assert correccion is not None
    assert correccion["despues"]["monto_centimos"] == 500000

    deshecho = await revertir_movimiento(TELEFONO, "mov-2", correccion["antes"])

    assert deshecho is not None
    assert deshecho["despues"]["monto_centimos"] == 250000
    assert deshecho["despues"]["categoria"] == "Ventas"
    assert deshecho["despues"]["tipo_movimiento"] == "ingreso"
    assert deshecho["despues"]["estado"] == "confirmado"
    assert deshecho["despues"]["version"] == 3

    filas = sheets.tabs[TELEFONO].get_all_values()
    assert filas[2][1] == "250000"
    assert filas[2][2] == "Ventas"
    assert filas[2][6] == "ingreso"
    assert filas[2][9] == "confirmado"
    assert filas[2][10] == "3"

    acciones = [fila[3] for fila in sheets.tabs[AUDITORIA_TAB_NAME].get_all_values()[1:]]
    assert acciones == ["corregir", "deshacer"]
    ultima = sheets.tabs[AUDITORIA_TAB_NAME].get_all_values()[-1]
    assert '"monto_centimos": 500000' in ultima[4]
    assert '"monto_centimos": 250000' in ultima[5]


async def test_anular_con_accion_deshacer_no_se_confunde_con_anular(
    sheets: FakeSpreadsheet,
) -> None:
    sheets.tabs[TELEFONO] = _tab_canonica()

    resultado = await anular_movimiento(
        TELEFONO, "mov-1", motivo="deshacer registro", accion="deshacer"
    )

    assert resultado is not None
    assert resultado["despues"]["estado"] == "anulado"

    historial = await obtener_historial(TELEFONO)
    assert len(historial) == 1
    assert historial[0]["accion"] == "deshacer"
    assert historial[0]["entidad_id"] == "mov-1"
