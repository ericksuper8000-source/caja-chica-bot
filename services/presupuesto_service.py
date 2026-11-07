import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from services.sheets_service import (
    eliminar_presupuesto_sheet,
    guardar_presupuesto_sheet,
    marcar_alerta_presupuesto_sheet,
    obtener_presupuestos_sheet,
)

logger = logging.getLogger(__name__)


@dataclass
class Presupuesto:
    categoria: str
    limite: int


def _normalizar_categoria(cat: str) -> str:
    cat = cat.lower().strip()
    cat = (
        cat.replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
    )
    return cat


def _periodo_actual() -> str:
    return datetime.now().strftime("%Y-%m")


async def obtener_presupuestos(sender_phone: str) -> dict[str, int]:
    """Retorna {categoria: limite} del teléfono, leído de la pestaña `Presupuestos`."""
    filas = await obtener_presupuestos_sheet()
    resultado: dict[str, int] = {}
    for fila in filas:
        if str(fila.get("telefono", "")).strip() != sender_phone:
            continue
        categoria = str(fila.get("categoria", "")).strip()
        if not categoria:
            continue
        try:
            limite = int(float(str(fila.get("limite", "0")) or 0))
        except (TypeError, ValueError):
            continue
        if limite > 0:
            resultado[_normalizar_categoria(categoria)] = limite
    return resultado


async def obtener_presupuesto_categoria(sender_phone: str, categoria: str) -> int | None:
    """Retorna el límite de una categoría específica o None si no tiene presupuesto."""
    presupuestos = await obtener_presupuestos(sender_phone)
    return presupuestos.get(_normalizar_categoria(categoria))


async def establecer_presupuesto(sender_phone: str, categoria: str, limite: int) -> bool:
    """Establece o actualiza el presupuesto de una categoría. Retorna True si OK."""
    if limite <= 0:
        return False
    guardado = await guardar_presupuesto_sheet(sender_phone, categoria, limite)
    if guardado:
        logger.info("Presupuesto establecido: %s -> %s = %d", sender_phone, categoria, limite)
    return guardado


async def eliminar_presupuesto(sender_phone: str, categoria: str) -> bool:
    """Elimina el presupuesto de una categoría. Retorna True si existía."""
    eliminado = await eliminar_presupuesto_sheet(sender_phone, categoria)
    if eliminado:
        logger.info("Presupuesto eliminado: %s -> %s", sender_phone, categoria)
    return eliminado


def calcular_gastado_mes(
    filas: list[list[Any]], categoria: str, ahora: datetime | None = None
) -> int:
    """
    Suma los gastos del mes en curso para una categoría (misma regla que las
    consultas: montos negativos de la pestaña del cliente, mes calendario).
    """
    referencia = ahora or datetime.now()
    inicio_mes = referencia.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    categoria_norm = _normalizar_categoria(categoria)
    gastado = 0
    for row in filas:
        if len(row) < 3:
            continue
        try:
            dt = datetime.fromisoformat(str(row[0]).replace("/", "-"))
        except ValueError:
            continue
        if dt < inicio_mes:
            continue
        categoria_hoja = _normalizar_categoria(str(row[2]))
        if not (
            categoria_hoja == categoria_norm
            or categoria_norm in categoria_hoja
            or categoria_hoja in categoria_norm
        ):
            continue
        try:
            monto = int(str(row[1]))
        except (TypeError, ValueError):
            continue
        if monto < 0:
            gastado += abs(monto)
    return gastado


async def verificar_y_alertar_presupuesto(
    sender_phone: str, categoria: str, monto_nuevo: int, total_mes: int
) -> str | None:
    """
    (Paso 4, P1-1) Devuelve la alerta de presupuesto si corresponde: al 80% y al
    100% del límite mensual, una sola vez por umbral y periodo. La marca se guarda
    en la propia fila de la pestaña `Presupuestos` (alerta_80/alerta_100), así no
    se pierde al reiniciar el worker.
    """
    filas = await obtener_presupuestos_sheet()
    categoria_norm = _normalizar_categoria(categoria)
    fila_objetivo: dict[str, str] | None = None
    for fila in filas:
        if str(fila.get("telefono", "")).strip() != sender_phone:
            continue
        if _normalizar_categoria(str(fila.get("categoria", ""))) == categoria_norm:
            fila_objetivo = fila
    if fila_objetivo is None:
        return None
    try:
        limite = int(float(str(fila_objetivo.get("limite", "0")) or 0))
    except (TypeError, ValueError):
        return None
    if limite <= 0:
        return None

    periodo = _periodo_actual()
    pct = total_mes * 100 // limite
    if total_mes >= limite and str(fila_objetivo.get("alerta_100", "")).strip() != periodo:
        await marcar_alerta_presupuesto_sheet(sender_phone, categoria, 100, periodo)
        await marcar_alerta_presupuesto_sheet(sender_phone, categoria, 80, periodo)
        return (
            f"🚨 Te pasaste del presupuesto de {categoria}: "
            f"₡{total_mes:,} / ₡{limite:,} ({pct}%). "
            "Queda registrado igual; revisá tus gastos si querés ajustar."
        )
    if pct >= 80 and str(fila_objetivo.get("alerta_80", "")).strip() != periodo:
        await marcar_alerta_presupuesto_sheet(sender_phone, categoria, 80, periodo)
        restante = max(0, limite - total_mes)
        return (
            f"⚠️ Vas por ₡{total_mes:,} de ₡{limite:,} en {categoria} ({pct}%). "
            f"Te quedan ₡{restante:,} este mes."
        )
    return None


def detectar_presupuesto(texto: str) -> tuple[str, int] | None:
    """
    Detecta comando de presupuesto: "presupuesto comida 50000" o "presupuesto de comida 10000"
    Retorna (categoria, limite) o None.
    """
    import re

    t = texto.lower().strip()
    t = re.sub(r"[¿?¡!.,;:()\"'«»]", "", t)

    if not t.startswith("presupuesto"):
        return None

    partes = t.split()
    # Aceptar "presupuesto comida 10000" (3 partes) o "presupuesto de comida 10000" (4 partes)
    if len(partes) not in (3, 4):
        return None

    # Si tiene 4 partes y la segunda es "de", saltarla
    if len(partes) == 4 and partes[1] == "de":
        _, _, categoria_raw, limite_raw = partes
    else:
        _, categoria_raw, limite_raw = partes

    try:
        limite = int(limite_raw)
    except ValueError:
        return None

    if limite <= 0:
        return None

    # Normalizar categoría (sinónimos básicos)
    sinónimos = {
        "comida": "alimentacion",
        "alimentos": "alimentacion",
        "transporte": "transporte",
        "bus": "transporte",
        "taxi": "transporte",
        "uber": "transporte",
        "gasolina": "transporte",
        "combustible": "transporte",
        "vivienda": "vivienda",
        "alquiler": "vivienda",
        "servicios": "servicios",
        "luz": "servicios",
        "agua": "servicios",
        "internet": "servicios",
        "salud": "salud",
        "medico": "salud",
        "medicina": "salud",
        "educacion": "educacion",
        "entretenimiento": "entretenimiento",
        "ropa": "ropa",
        "tecnologia": "tecnologia",
        "otros": "otros",
    }
    cat_norm = categoria_raw.lower().strip()
    categoria = sinónimos.get(cat_norm, cat_norm)

    return (categoria, limite)


def detectar_eliminar_presupuesto(texto: str) -> str | None:
    """Detecta: 'borrar presupuesto comida' o 'eliminar presupuesto de comida'."""
    import re

    t = texto.lower().strip()
    t = re.sub(r"[¿?¡!.,;:()\"'«»]", "", t)

    for verbo in ("borrar", "eliminar", "quitar", "quite"):
        if t.startswith(f"{verbo} presupuesto"):
            partes = t.split()
            if len(partes) >= 3:
                # Saltar "de" si está en posición 2: "borrar presupuesto de comida"
                idx_categoria = 2
                if len(partes) >= 4 and partes[2] == "de":
                    idx_categoria = 3
                if idx_categoria < len(partes):
                    categoria_raw = partes[idx_categoria]
                    sinónimos = {
                        "comida": "alimentacion",
                        "alimentos": "alimentacion",
                        "transporte": "transporte",
                        "bus": "transporte",
                        "taxi": "transporte",
                        "uber": "transporte",
                        "vivienda": "vivienda",
                        "servicios": "servicios",
                        "salud": "salud",
                        "otros": "otros",
                    }
                    cat = sinónimos.get(
                        categoria_raw.lower().strip(), categoria_raw.lower().strip()
                    )
                    # Defensa: si por alguna razón devolvimos "de", forzar None
                    if cat == "de":
                        return None
                    return cat
    return None
