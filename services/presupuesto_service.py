import json
import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

PRESUPUESTOS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "presupuestos.json")


@dataclass
class Presupuesto:
    categoria: str
    limite: int


def _asegurar_directorio() -> None:
    os.makedirs(os.path.dirname(PRESUPUESTOS_PATH), exist_ok=True)


def _cargar_presupuestos() -> dict[str, dict[str, int]]:
    """Carga presupuestos desde JSON. Retorna dict[user_id][categoria] = limite."""
    _asegurar_directorio()
    if not os.path.exists(PRESUPUESTOS_PATH):
        return {}
    try:
        with open(PRESUPUESTOS_PATH, encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Error cargando presupuestos: %s", e)
        return {}


def _guardar_presupuestos(data: dict[str, dict[str, int]]) -> None:
    _asegurar_directorio()
    try:
        with open(PRESUPUESTOS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.error("Error guardando presupuestos: %s", e)


async def obtener_presupuestos(sender_phone: str) -> dict[str, int]:
    """Retorna todos los presupuestos del usuario: {categoria: limite}."""
    data = _cargar_presupuestos()
    return data.get(sender_phone, {})


async def obtener_presupuesto_categoria(sender_phone: str, categoria: str) -> int | None:
    """Retorna el límite de una categoría específica o None si no tiene presupuesto."""
    presupuestos = await obtener_presupuestos(sender_phone)
    return presupuestos.get(categoria)


async def establecer_presupuesto(sender_phone: str, categoria: str, limite: int) -> bool:
    """Establece o actualiza el presupuesto de una categoría. Retorna True si OK."""
    if limite <= 0:
        return False
    data = _cargar_presupuestos()
    user_data = data.get(sender_phone, {})
    user_data[categoria] = limite
    data[sender_phone] = user_data
    _guardar_presupuestos(data)
    logger.info("Presupuesto establecido: %s -> %s = %d", sender_phone, categoria, limite)
    return True


async def eliminar_presupuesto(sender_phone: str, categoria: str) -> bool:
    """Elimina el presupuesto de una categoría. Retorna True si existía."""
    data = _cargar_presupuestos()
    user_data = data.get(sender_phone, {})
    if categoria in user_data:
        del user_data[categoria]
        data[sender_phone] = user_data
        _guardar_presupuestos(data)
        logger.info("Presupuesto eliminado: %s -> %s", sender_phone, categoria)
        return True
    return False


async def verificar_y_alertar_presupuesto(
    sender_phone: str, categoria: str, monto_nuevo: int, total_mes: int
) -> str | None:
    """
    Verifica si el gasto supera el presupuesto de la categoría.
    Retorna mensaje de alerta si se superó, None si no hay presupuesto o no se superó.
    """
    limite = await obtener_presupuesto_categoria(sender_phone, categoria)
    if limite is None:
        return None
    if total_mes > limite:
        return (
            f"⚠️ Presupuesto {categoria} superado: "
            f"₡{total_mes:,} / ₡{limite:,} ({total_mes * 100 // limite}%)."
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
