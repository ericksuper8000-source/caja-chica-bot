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


_NUMEROS_PALABRA = {
    "cero": 0,
    "un": 1,
    "uno": 1,
    "una": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
    "once": 11,
    "doce": 12,
    "trece": 13,
    "catorce": 14,
    "quince": 15,
    "dieciseis": 16,
    "diecisiete": 17,
    "dieciocho": 18,
    "diecinueve": 19,
    "veinte": 20,
    "veintiuno": 21,
    "veintiun": 21,
    "veintidos": 22,
    "veintitres": 23,
    "veinticuatro": 24,
    "veinticinco": 25,
    "veintiseis": 26,
    "veintisiete": 27,
    "veintiocho": 28,
    "veintinueve": 29,
    "treinta": 30,
    "cuarenta": 40,
    "cincuenta": 50,
    "sesenta": 60,
    "setenta": 70,
    "ochenta": 80,
    "noventa": 90,
    "cien": 100,
    "ciento": 100,
    "doscientos": 200,
    "trescientos": 300,
    "cuatrocientos": 400,
    "quinientos": 500,
    "seiscientos": 600,
    "setecientos": 700,
    "ochocientos": 800,
    "novecientos": 900,
}

_PALABRAS_IGNORADAS = frozenset(
    {"y", "de", "del", "para", "en", "colones", "colon", "pesos", "peso"}
)


def _sin_tildes(texto: str) -> str:
    return (
        texto.lower()
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ü", "u")
    )


def _palabras_a_numero(texto: str) -> int | None:
    """Convierte montos dichos con palabras: 'veinte mil', 'cien mil', 'un millón'."""
    palabras = _sin_tildes(texto).replace("-", " ").split()
    if not palabras:
        return None
    total = 0
    actual = 0
    visto = False
    for palabra in palabras:
        if palabra in _PALABRAS_IGNORADAS:
            continue
        if palabra == "mil":
            total += (actual or 1) * 1000
            actual = 0
            visto = True
        elif palabra in ("millon", "millones"):
            total += (actual or 1) * 1_000_000
            actual = 0
            visto = True
        elif palabra in _NUMEROS_PALABRA:
            actual += _NUMEROS_PALABRA[palabra]
            visto = True
        else:
            return None
    return total + actual if visto else None


def _parsear_monto(valor: str) -> int | None:
    """Interpreta montos dichos/escritos: '20000', '20.000', '20 mil', 'veinte mil'."""
    limpio = valor.lower().strip().replace("₡", "")
    for sufijo in ("colones", "colon", "colón"):
        if limpio.endswith(sufijo):
            limpio = limpio[: -len(sufijo)].strip()
    solo_digitos = limpio.replace(".", "").replace(",", "").replace(" ", "")
    multiplicador = 1
    if solo_digitos.endswith("mil"):
        multiplicador = 1000
        solo_digitos = solo_digitos[:-3]
    if solo_digitos.isdigit():
        return int(solo_digitos) * multiplicador
    return _palabras_a_numero(limpio)


def detectar_presupuesto(texto: str) -> tuple[str, int] | None:
    """
    Detecta comandos de presupuesto con tolerancia a cómo llega la transcripción:
    "presupuesto comida 50000", "presupuesto de comida 50.000",
    "presupuesto para transporte 20 mil", "presupuesto luz 30000 colones".
    Retorna (categoria, limite) o None.
    """
    import re

    t = texto.lower().strip()
    t = re.sub(r"[¿?¡!.,;:()\"'«»]", "", t)

    if not t.startswith("presupuesto"):
        return None

    resto = t[len("presupuesto") :].strip()
    palabras = resto.split()
    relleno = {"de", "del", "para", "el", "la", "los", "las", "un", "una", "mi", "mis"}
    while palabras and palabras[0] in relleno:
        palabras.pop(0)
    if len(palabras) < 2:
        return None

    categoria_raw = palabras[0]
    limite = _parsear_monto(" ".join(palabras[1:]))
    if limite is None or limite <= 0:
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
    cat_norm = _normalizar_categoria(categoria_raw)
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
