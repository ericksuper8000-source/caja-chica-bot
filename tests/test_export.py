"""
Tests de exportación CSV/XLSX (P1-4, D5).

Verifican el contrato de columnas, el BOM UTF-8 que evita romper tildes en Excel, los
montos con signo, la neutralización de fórmulas y el envío por WhatsApp con degradación
a texto si Meta rechaza el documento.
"""

import csv
import io
from contextlib import ExitStack
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from openpyxl import load_workbook

from services.export_service import (
    EXPORT_HEADERS,
    MIME_CSV,
    MIME_XLSX,
    TEXTO_EXPORTACION_DOCUMENTO,
    fila_exportacion,
    generar_csv,
    generar_exportacion,
    generar_xlsx,
    nombre_exportacion,
)
from services.politica_service import (
    POLITICA_VERSION,
    TEXTO_EXPORTACION_ENCABEZADO,
    TEXTO_EXPORTACION_VACIA,
)
from workers.tasks import procesar_mensaje_texto_task

TELEFONO = "50688888888"


def _fila(
    fecha: str = "2026-11-08 18:00:00",
    monto_centimos: int = 150000,
    categoria: str = "Alimentación",
    detalle: str = "almuerzo",
    *,
    tipo: str = "gasto",
    moneda: str = "CRC",
    contexto: str = "personal",
    estado: str = "confirmado",
    movimiento_id: str = "mov-1",
) -> list[Any]:
    """Fila canónica de 13 columnas, tal como la devuelve `obtener_transacciones_cliente`."""
    return [
        fecha,
        monto_centimos,
        categoria,
        detalle,
        TELEFONO,
        movimiento_id,
        tipo,
        moneda,
        contexto,
        estado,
        1,
        fecha,
        "chat",
    ]


# ==========================================
# Contrato de columnas
# ==========================================
def test_fila_exportacion_mapea_las_siete_columnas_y_el_signo() -> None:
    gasto = fila_exportacion(_fila())
    ingreso = fila_exportacion(
        _fila(monto_centimos=250000, categoria="Ventas", detalle="camisetas", tipo="ingreso")
    )
    devolucion = fila_exportacion(
        _fila(monto_centimos=50000, categoria="Compras", detalle="devolución", tipo="devolucion")
    )

    assert gasto == [
        "2026-11-08 18:00:00",
        "Gasto",
        -1500,
        "CRC",
        "Alimentación",
        "personal",
        "almuerzo",
    ]
    assert ingreso[1] == "Ingreso"
    assert ingreso[2] == 2500
    assert devolucion[1] == "Devolución"
    assert devolucion[2] == 500


def test_fila_exportacion_tolera_pestana_legacy_sin_inventar_columnas() -> None:
    fila = fila_exportacion(
        ["2026-08-20 19:29:13", "-3000", "Alimentación", "Tres perros", TELEFONO]
    )

    assert fila == [
        "2026-08-20 19:29:13",
        "Gasto",
        -3000,
        "CRC",
        "Alimentación",
        "personal",
        "Tres perros",
    ]


def test_fila_exportacion_marca_anulados_y_pendientes_en_el_tipo() -> None:
    """
    El export ARCO incluye anulados/pendientes; sin marca, el contador los sumaría
    como gastos válidos. Se anotan en la columna Tipo para no agregar una octava columna.
    """
    anulado = fila_exportacion(_fila(estado="anulado"))
    pendiente = fila_exportacion(_fila(estado="pendiente"))
    corregido = fila_exportacion(_fila(estado="corregido"))

    assert anulado[1] == "Gasto (anulado)"
    assert pendiente[1] == "Gasto (pendiente)"
    assert corregido[1] == "Gasto"  # corregido sí cuenta en reportes


def test_fila_exportacion_conserva_centimos_cuando_existen() -> None:
    fila = fila_exportacion(_fila(monto_centimos=150050))

    assert fila[2] == -1500.5


# ==========================================
# CSV
# ==========================================
def test_csv_tiene_bom_utf8_columnas_y_tildes_intactas() -> None:
    contenido = generar_csv(
        [
            _fila(),
            _fila(
                fecha="2026-11-09 09:00:00",
                monto_centimos=250000,
                categoria="Ventas",
                detalle="camisetas",
                tipo="ingreso",
                movimiento_id="mov-2",
            ),
        ]
    )

    assert contenido.startswith(b"\xef\xbb\xbf")

    texto = contenido.decode("utf-8-sig")
    assert "Alimentación" in texto
    assert "camisetas" in texto
    assert "\r\n" in texto

    filas = list(csv.reader(io.StringIO(texto)))
    assert filas[0] == EXPORT_HEADERS
    assert len(filas) == 3
    assert filas[1] == [
        "2026-11-08 18:00:00",
        "Gasto",
        "-1500",
        "CRC",
        "Alimentación",
        "personal",
        "almuerzo",
    ]
    assert filas[2][1] == "Ingreso"
    assert filas[2][2] == "2500"


def test_csv_neutraliza_formulas_en_campos_de_texto() -> None:
    contenido = generar_csv([_fila(detalle="=SUM(A1:A2)", categoria="+Categoría")])
    filas = list(csv.reader(io.StringIO(contenido.decode("utf-8-sig"))))

    assert filas[1][4] == "'+Categoría"
    assert filas[1][6] == "'=SUM(A1:A2)"
    # El monto numérico negativo no se toca: sigue siendo un número para Excel.
    assert filas[1][2] == "-1500"


# ==========================================
# XLSX
# ==========================================
def test_xlsx_se_abre_con_columnas_tildes_y_montos_numericos() -> None:
    contenido = generar_xlsx([_fila(), _fila(monto_centimos=250000, tipo="ingreso")])

    libro = load_workbook(io.BytesIO(contenido))
    hoja = libro["Movimientos"]

    assert [celda.value for celda in hoja[1]] == EXPORT_HEADERS
    assert [celda.value for celda in hoja[2]] == [
        "2026-11-08 18:00:00",
        "Gasto",
        -1500,
        "CRC",
        "Alimentación",
        "personal",
        "almuerzo",
    ]
    assert hoja.cell(row=3, column=2).value == "Ingreso"
    assert hoja.cell(row=3, column=3).value == 2500
    assert hoja.cell(row=2, column=3).number_format == "#,##0.##"
    assert hoja.freeze_panes == "A2"
    assert hoja.auto_filter.ref is not None


def test_xlsx_no_convierte_un_detalle_en_formula() -> None:
    contenido = generar_xlsx([_fila(detalle="=SUM(A1:A2)")])

    hoja = load_workbook(io.BytesIO(contenido))["Movimientos"]
    celda = hoja.cell(row=2, column=7)

    assert celda.value == "=SUM(A1:A2)"
    assert celda.data_type == "s"


# ==========================================
# Nombre del archivo y despacho
# ==========================================
def test_nombre_exportacion_incluye_periodo_moneda_y_extension() -> None:
    filas = [
        _fila(fecha="2026-01-15 10:00:00"),
        _fila(fecha="2026-11-08 18:00:00"),
    ]

    assert nombre_exportacion(filas, "csv") == "movimientos_2026-01-15_a_2026-11-08_CRC.csv"
    assert nombre_exportacion(filas, "xlsx") == "movimientos_2026-01-15_a_2026-11-08_CRC.xlsx"


def test_nombre_exportacion_de_un_solo_dia_no_repite_el_periodo() -> None:
    assert nombre_exportacion([_fila()], "csv") == "movimientos_2026-11-08_CRC.csv"


def test_generar_exportacion_despacha_al_formato_pedido() -> None:
    filas = [_fila()]

    assert generar_exportacion(filas, "csv") == generar_csv(filas)
    assert generar_exportacion(filas, "xlsx") == generar_xlsx(filas)


# ==========================================
# Pipeline: documentos y fallback de texto
# ==========================================
@pytest.fixture
def exportacion():
    """Pipeline con ARCO y WhatsApp simulados; no toca Sheets ni Meta."""
    stack = ExitStack()
    mocks = {
        "wa": stack.enter_context(patch("workers.tasks.enviar_mensaje_whatsapp")),
        "documento": stack.enter_context(
            patch(
                "workers.tasks.enviar_documento_whatsapp",
                new=AsyncMock(return_value=True),
            )
        ),
        "transacciones": stack.enter_context(
            patch(
                "workers.tasks.obtener_transacciones_cliente",
                new=AsyncMock(return_value=[_fila()]),
            )
        ),
        "consent": stack.enter_context(
            patch(
                "workers.tasks.obtener_consentimiento",
                return_value={"estado": "aceptado", "version_politica": POLITICA_VERSION},
            )
        ),
        "paso": stack.enter_context(
            patch("workers.tasks.obtener_paso", new=AsyncMock(return_value=None))
        ),
        "consulta": stack.enter_context(
            patch("workers.tasks.detectar_consulta", new=AsyncMock(return_value=None))
        ),
    }
    with stack:
        yield mocks


def test_exportar_envia_csv_y_xlsx_incluyendo_anulados(exportacion: dict[str, Any]) -> None:
    exportacion["transacciones"].return_value = [_fila(estado="anulado")]

    procesar_mensaje_texto_task(TELEFONO, "exporta mis datos")

    exportacion["transacciones"].assert_awaited_once_with(TELEFONO, incluir_inactivos=True)
    assert exportacion["documento"].await_count == 2

    primera = exportacion["documento"].await_args_list[0].kwargs
    segunda = exportacion["documento"].await_args_list[1].kwargs

    assert primera["nombre"] == "movimientos_2026-11-08_CRC.csv"
    assert primera["mime_type"] == MIME_CSV
    assert primera["contenido"].startswith(b"\xef\xbb\xbf")
    assert "Gasto (anulado)" in primera["contenido"].decode("utf-8-sig")
    assert primera["caption"] == TEXTO_EXPORTACION_DOCUMENTO

    assert segunda["nombre"] == "movimientos_2026-11-08_CRC.xlsx"
    assert segunda["mime_type"] == MIME_XLSX
    assert segunda["contenido"].startswith(b"PK")  # firma de un archivo ZIP/XLSX

    # No se manda el texto: el archivo llegó.
    assert exportacion["wa"].await_count == 0


def test_exportar_cae_a_texto_si_meta_rechaza_los_documentos(
    exportacion: dict[str, Any],
) -> None:
    exportacion["documento"].return_value = False

    procesar_mensaje_texto_task(TELEFONO, "exporta mis datos")

    assert exportacion["documento"].await_count == 2
    assert exportacion["wa"].await_count == 1
    mensaje = exportacion["wa"].call_args.kwargs["mensaje"]
    assert mensaje.startswith(TEXTO_EXPORTACION_ENCABEZADO)
    assert "Alimentación" in mensaje
    assert "-₡1500" in mensaje


def test_exportar_sin_movimientos_avisa_sin_generar_archivo(
    exportacion: dict[str, Any],
) -> None:
    exportacion["transacciones"].return_value = []

    procesar_mensaje_texto_task(TELEFONO, "exporta mis datos")

    exportacion["wa"].assert_awaited_once_with(to_phone=TELEFONO, mensaje=TEXTO_EXPORTACION_VACIA)
    assert exportacion["documento"].await_count == 0
