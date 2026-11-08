"""
Exportación de movimientos a CSV/XLSX (P1-4, decisión D5).

El archivo es para el usuario y su contador: columnas estables, montos numéricos con
signo de negocio, moneda explícita y contexto. El CSV sale con BOM UTF-8 para que Excel
abra las tildes correctamente; el XLSX sale con encabezado en negrita, filtro y anchos
legibles. No se presenta como declaración de impuestos.

Funciones puras (sin red ni Sheets): reciben filas canónicas o históricas y devuelven
bytes. El pipeline decide cómo enviarlos por WhatsApp.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from typing import Any, Literal

from services.modelo_service import fila_a_movimiento

FormatoExport = Literal["csv", "xlsx"]

EXPORT_HEADERS = [
    "Fecha",
    "Tipo",
    "Monto",
    "Moneda",
    "Categoría",
    "Contexto",
    "Detalle",
]
"""Columnas estandarizadas de P1-4 (fecha, tipo, monto, moneda, categoría, contexto, detalle)."""

MIME_CSV = "text/csv"
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

TEXTO_EXPORTACION_DOCUMENTO = (
    "Tus movimientos exportados (incluye los anulados, si los hay). "
    "Es un registro de tu caja chica, no una declaración de impuestos."
)

_ETIQUETAS_TIPO = {
    "gasto": "Gasto",
    "ingreso": "Ingreso",
    "transferencia": "Transferencia",
    "reembolso": "Reembolso",
    "devolucion": "Devolución",
}

_CARACTERES_RIESGO_FORMULA = ("=", "+", "@", "\t", "\r")


def _monto_con_signo(movimiento: dict[str, Any]) -> int | float:
    """Monto en colones: negativo para gasto, positivo para el resto (D4)."""
    centimos = abs(int(movimiento.get("monto_centimos") or 0))
    signo = -1 if str(movimiento.get("tipo_movimiento")) == "gasto" else 1
    if centimos % 100 == 0:
        return signo * (centimos // 100)
    return signo * round(centimos / 100, 2)


def fila_exportacion(fila: list[Any]) -> list[Any]:
    """
    Convierte una fila de la hoja (canónica o histórica) a las 7 columnas de export.

    Usa `fila_a_movimiento`, así el export tolera pestañas viejas de 5 columnas sin
    migrarlas y no inventa IDs ni estados.
    """
    movimiento = fila_a_movimiento(fila)
    tipo = str(movimiento.get("tipo_movimiento") or "gasto").lower()
    estado = str(movimiento.get("estado") or "confirmado").lower()
    etiqueta_tipo = _ETIQUETAS_TIPO.get(tipo, tipo.capitalize())
    if estado not in ("confirmado", "corregido"):
        # El export incluye anulados/pendientes (derecho ARCO). Sin esta marca, un
        # anulado parecería un gasto válido y el contador sumaría de más.
        etiqueta_tipo = f"{etiqueta_tipo} ({estado})"
    return [
        str(movimiento.get("fecha_movimiento") or ""),
        etiqueta_tipo,
        _monto_con_signo(movimiento),
        str(movimiento.get("moneda") or "CRC"),
        str(movimiento.get("categoria") or "Otros"),
        str(movimiento.get("contexto_tipo") or "personal"),
        str(movimiento.get("detalle") or ""),
    ]


def _celda_csv(valor: Any) -> Any:
    """Evita que un detalle con '=' o '+' se evalúe como fórmula al abrir el CSV."""
    if isinstance(valor, str) and valor.startswith(_CARACTERES_RIESGO_FORMULA):
        return "'" + valor
    return valor


def generar_csv(filas: list[list[Any]]) -> bytes:
    """
    Genera el CSV con BOM UTF-8 (`utf-8-sig`) y saltos CRLF para Excel.

    El BOM es la diferencia entre "Alimentación" y "AlimentaciÃ³n" en Excel: sin él,
    Excel asume Latin-1 y rompe las tildes del español.
    """
    buffer = io.StringIO()
    escritor = csv.writer(buffer, lineterminator="\r\n")
    escritor.writerow(EXPORT_HEADERS)
    for fila in filas:
        escritor.writerow([_celda_csv(valor) for valor in fila_exportacion(fila)])
    return buffer.getvalue().encode("utf-8-sig")


def generar_xlsx(filas: list[list[Any]]) -> bytes:
    """
    Genera el XLSX con encabezado en negrita, filtro, panel congelado y anchos fijos.

    Las celdas de texto se marcan como string para que un detalle que empiece con '='
    no se convierta en fórmula al abrir el archivo.

    `openpyxl` se importa aquí, no al cargar el módulo: si falta la dependencia en un
    despliegue, el bot sigue funcionando y el pipeline puede mandar el CSV o el texto.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    libro = Workbook()
    hoja = libro.active
    hoja.title = "Movimientos"
    hoja.append(EXPORT_HEADERS)
    for celda in hoja[1]:
        celda.font = Font(bold=True)
        celda.data_type = "s"

    for fila in filas:
        hoja.append(fila_exportacion(fila))

    for numero_fila in range(2, hoja.max_row + 1):
        for celda in hoja[numero_fila]:
            if isinstance(celda.value, str):
                celda.data_type = "s"
            if celda.column == 3:
                celda.number_format = "#,##0.##"

    anchos = (20, 14, 14, 8, 22, 14, 42)
    for indice, ancho in enumerate(anchos, start=1):
        hoja.column_dimensions[get_column_letter(indice)].width = ancho

    hoja.freeze_panes = "A2"
    hoja.auto_filter.ref = hoja.dimensions

    buffer = io.BytesIO()
    libro.save(buffer)
    return buffer.getvalue()


def generar_exportacion(filas: list[list[Any]], formato: FormatoExport) -> bytes:
    """Despacha al generador correspondiente; `formato` es 'csv' o 'xlsx'."""
    if formato == "csv":
        return generar_csv(filas)
    return generar_xlsx(filas)


def nombre_exportacion(filas: list[list[Any]], formato: FormatoExport) -> str:
    """
    Nombre con moneda y periodo: `movimientos_2026-01-01_a_2026-11-08_CRC.csv`.

    El periodo sale de las fechas de los propios movimientos (no del reloj): así el
    archivo dice exactamente qué contiene. Si no hay fechas válidas, usa hoy.
    """
    fechas: list[str] = []
    for fila in filas:
        if not fila:
            continue
        texto = str(fila[0]).strip()
        if len(texto) >= 10:
            fechas.append(texto[:10])
    fechas.sort()
    hoy = datetime.now(UTC).strftime("%Y-%m-%d")
    desde = fechas[0] if fechas else hoy
    hasta = fechas[-1] if fechas else hoy
    periodo = desde if desde == hasta else f"{desde}_a_{hasta}"

    monedas = {str(fila[7]).strip() for fila in filas if len(fila) > 7 and str(fila[7]).strip()}
    moneda = monedas.pop() if len(monedas) == 1 else "CRC"
    return f"movimientos_{periodo}_{moneda}.{formato}"
