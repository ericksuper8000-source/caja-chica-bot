"""
Modelo canónico mínimo de movimientos (A02, `docs/producto/modelo-datos.md`).

La hoja histórica guarda 5 columnas (`fecha, monto, categoria, detalle, telefono`) y
deduce el tipo por el signo del monto. Ese formato no permite estados, auditoría,
contexto ni identidad estable. Este módulo define la representación canónica mínima y
las funciones puras de lectura/migración, sin tocar Google Sheets.

Decisiones del corte mínimo (ratificadas en el modelo de datos):
- `monto_centimos` es positivo y el tipo define el signo.
- `fecha_movimiento` es la fecha del hecho; `fecha_registro` es cuándo se guardó.
- `moneda` es explícita (CRC por defecto).
- `contexto_tipo` es primario (personal por defecto en este corte).
- `estado` distingue confirmado/corregido/anulado/pendiente.
- `version` permite control de concurrencia y auditoría.
- `movimiento_id` es único e inmutable.

La migración es una función pura para poder probarla con filas reales antes de escribir
en una hoja: recibe las filas de datos, devuelve las filas canónicas y un reporte de
conciliación de conteos/totales antes y después.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

TRANSACTION_HEADERS: list[str] = [
    "fecha_movimiento",
    "monto_centimos",
    "categoria",
    "detalle",
    "telefono",
    "movimiento_id",
    "tipo_movimiento",
    "moneda",
    "contexto_tipo",
    "estado",
    "version",
    "fecha_registro",
    "origen",
]

LEGACY_TRANSACTION_HEADERS: list[str] = ["fecha", "monto", "categoria", "detalle", "telefono"]

TIPOS_MOVIMIENTO = ("ingreso", "gasto", "transferencia", "reembolso", "devolucion")
ESTADOS_MOVIMIENTO = ("pendiente", "confirmado", "corregido", "anulado", "eliminado")
ESTADOS_ACTIVOS = ("confirmado", "corregido")
CONTEXTOS_VALIDOS = ("personal", "negocio", "trabajo", "evento", "ruta", "proyecto")

TipoEncabezado = Literal["canonico", "legacy", "desconocido"]


def nuevo_movimiento_id() -> str:
    """Identificador opaco, único e inmutable para un movimiento."""
    return uuid.uuid4().hex


def _texto(valor: Any) -> str:
    return "" if valor is None else str(valor).strip()


def _entero(valor: Any) -> int | None:
    """Convierte un valor de hoja/LLM a entero; None si no es numérico."""
    texto = _texto(valor)
    if not texto:
        return None
    try:
        return int(float(texto.replace(",", "")))
    except (TypeError, ValueError):
        return None


def _normalizar_tipo(valor: Any) -> str:
    tipo = _texto(valor).lower()
    return tipo if tipo in TIPOS_MOVIMIENTO else ""


def _normalizar_estado(valor: Any) -> str:
    estado = _texto(valor).lower()
    return estado if estado in ESTADOS_MOVIMIENTO else ""


def _normalizar_contexto(valor: Any) -> str:
    contexto = _texto(valor).lower()
    return contexto if contexto in CONTEXTOS_VALIDOS else ""


def tipo_encabezado(fila: list[Any] | None) -> TipoEncabezado:
    """Clasifica la primera fila de una pestaña de movimientos."""
    if not fila:
        return "desconocido"
    valores = [_texto(valor) for valor in fila]
    if valores[: len(TRANSACTION_HEADERS)] == TRANSACTION_HEADERS:
        return "canonico"
    if valores[: len(LEGACY_TRANSACTION_HEADERS)] == LEGACY_TRANSACTION_HEADERS:
        return "legacy"
    return "desconocido"


def es_fila_vacia(fila: list[Any]) -> bool:
    return not any(_texto(valor) for valor in fila)


def es_fila_canonica(fila: list[Any]) -> bool:
    """
    True si la fila tiene forma canónica. La columna G (`tipo_movimiento`) es la
    señal estable: Google Sheets omite las celdas vacías del final, así que una fila
    canónica puede volver con menos de 13 celdas aunque no haya perdido datos.
    """
    valores = list(fila) + [""] * max(0, len(TRANSACTION_HEADERS) - len(fila))
    return len(fila) >= len(TRANSACTION_HEADERS) or bool(_texto(valores[6]))


def fila_a_movimiento(fila: list[Any]) -> dict[str, Any]:
    """
    Normaliza una fila de la hoja (canónica o histórica) a un movimiento con contrato
    estable. Una fila histórica no tiene ID; las operaciones que necesitan ID migran la
    pestaña antes de leerla. Los valores se toleran como texto porque gspread devuelve
    strings.
    """
    valores = list(fila) + [""] * max(0, len(TRANSACTION_HEADERS) - len(fila))
    es_canonica = es_fila_canonica(fila)

    if es_canonica:
        monto_centimos = abs(_entero(valores[1]) or 0)
        tipo = _normalizar_tipo(valores[6]) or "gasto"
        movimiento_id = _texto(valores[5])
        estado = _normalizar_estado(valores[9]) or "confirmado"
        version = _entero(valores[10]) or 1
        fecha_registro = _texto(valores[11]) or _texto(valores[0])
        fecha_movimiento = _texto(valores[0])
        origen = _texto(valores[12]) or "importacion"
    else:
        monto_firmado = _entero(valores[1]) or 0
        monto_centimos = abs(monto_firmado) * 100
        tipo = "gasto" if monto_firmado < 0 else "ingreso"
        movimiento_id = ""
        estado = "confirmado"
        version = 1
        fecha_registro = _texto(valores[0])
        fecha_movimiento = _texto(valores[0])
        origen = "importacion"

    signo = -1 if tipo == "gasto" else 1
    return {
        "fecha_movimiento": fecha_movimiento,
        "monto_centimos": monto_centimos,
        "monto": signo * (monto_centimos // 100),
        "categoria": _texto(valores[2]) or "Otros",
        "detalle": _texto(valores[3]),
        "telefono": _texto(valores[4]),
        "movimiento_id": movimiento_id,
        "tipo_movimiento": tipo,
        "moneda": _texto(valores[7]) or "CRC",
        "contexto_tipo": _normalizar_contexto(valores[8]) or "personal",
        "estado": estado,
        "version": version,
        "fecha_registro": fecha_registro,
        "origen": origen,
    }


def movimiento_a_fila(movimiento: dict[str, Any], *, generar_id: bool = True) -> list[Any]:
    """
    Convierte un movimiento normalizado a la fila canónica de 13 columnas.

    `generar_id=False` conserva vacío un movimiento sin ID: así una lectura de una
    pestaña histórica no inventa identidades efímeras. El ID se asigna al migrar o
    al escribir, nunca al solo leer.
    """
    movimiento_id = _texto(movimiento.get("movimiento_id"))
    if not movimiento_id and generar_id:
        movimiento_id = nuevo_movimiento_id()
    return [
        _texto(movimiento.get("fecha_movimiento")),
        int(movimiento.get("monto_centimos") or 0),
        _texto(movimiento.get("categoria")) or "Otros",
        _texto(movimiento.get("detalle")),
        _texto(movimiento.get("telefono")),
        movimiento_id,
        _normalizar_tipo(movimiento.get("tipo_movimiento")) or "gasto",
        _texto(movimiento.get("moneda")) or "CRC",
        _normalizar_contexto(movimiento.get("contexto_tipo")) or "personal",
        _normalizar_estado(movimiento.get("estado")) or "confirmado",
        int(movimiento.get("version") or 1),
        _texto(movimiento.get("fecha_registro")),
        _texto(movimiento.get("origen")) or "importacion",
    ]


def monto_con_signo(fila: list[Any]) -> int:
    """
    Monto en colones con el signo de negocio (gasto negativo, ingreso positivo).

    Es el puente de compatibilidad: las consultas/reportes históricos esperan el signo,
    mientras la hoja canónica guarda `monto_centimos` positivo + tipo explícito.
    """
    return int(fila_a_movimiento(fila)["monto"])


def _totales_centimos(movimientos: list[dict[str, Any]]) -> tuple[int, int]:
    gastos = 0
    ingresos = 0
    for movimiento in movimientos:
        monto = int(movimiento.get("monto_centimos") or 0)
        if str(movimiento.get("tipo_movimiento")) == "gasto":
            gastos += monto
        else:
            ingresos += monto
    return gastos, ingresos


def migrar_filas_legacy(
    filas: list[list[Any]],
    telefono: str,
    *,
    contexto: str = "personal",
    moneda: str = "CRC",
    fecha_registro: str | None = None,
) -> tuple[list[list[Any]], dict[str, Any]]:
    """
    Convierte filas históricas (o mixtas) al modelo canónico sin perder ninguna fila.

    Reglas de la tabla de migración de `modelo-datos.md`:
    - `abs(monto)` → `monto_centimos`; el signo define gasto/ingreso.
    - fila válida → `confirmado`; fila sin fecha/monto válido → `pendiente`.
    - `contexto_tipo` por defecto `personal`; `origen` = `importacion`.
    - cada fila obtiene un `movimiento_id` nuevo e inmutable.

    Devuelve `(filas_canonicas, reporte)`. El reporte concilia conteos y totales antes y
    después; `cuadra` debe ser True para que una migración se considere segura.
    """
    ahora = fecha_registro or datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    filas_limpias = [list(fila) for fila in filas if not es_fila_vacia(fila)]
    antes = [fila_a_movimiento(fila) for fila in filas_limpias]
    gastos_antes, ingresos_antes = _totales_centimos(antes)

    ids_usados: set[str] = set()
    salida: list[list[Any]] = []
    for fila in filas_limpias:
        movimiento = fila_a_movimiento(fila)
        canonical = es_fila_canonica(fila)

        fecha_movimiento = _texto(movimiento.get("fecha_movimiento"))
        monto_centimos = int(movimiento.get("monto_centimos") or 0)
        valido = bool(fecha_movimiento) and monto_centimos > 0
        if not canonical:
            movimiento["estado"] = "confirmado" if valido else "pendiente"
            movimiento["contexto_tipo"] = contexto
            movimiento["moneda"] = moneda
            movimiento["origen"] = "importacion"
            movimiento["fecha_registro"] = ahora
            movimiento["version"] = 1

        movimiento_id = _texto(movimiento.get("movimiento_id"))
        if not movimiento_id or movimiento_id in ids_usados:
            movimiento_id = nuevo_movimiento_id()
        ids_usados.add(movimiento_id)
        movimiento["movimiento_id"] = movimiento_id
        movimiento["telefono"] = _texto(movimiento.get("telefono")) or telefono
        salida.append(movimiento_a_fila(movimiento))

    despues = [fila_a_movimiento(fila) for fila in salida]
    gastos_despues, ingresos_despues = _totales_centimos(despues)

    reporte: dict[str, Any] = {
        "filas_antes": len(filas_limpias),
        "filas_despues": len(salida),
        "gastos_antes_centimos": gastos_antes,
        "gastos_despues_centimos": gastos_despues,
        "ingresos_antes_centimos": ingresos_antes,
        "ingresos_despues_centimos": ingresos_despues,
        "cuadra": (
            len(filas_limpias) == len(salida)
            and gastos_antes == gastos_despues
            and ingresos_antes == ingresos_despues
        ),
    }
    return salida, reporte
