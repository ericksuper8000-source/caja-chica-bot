"""
Onboarding guiado por WhatsApp (Fase 6.1, ADR-0019 / especificacion A04-A05).

Contexto: sin onboarding automatizado el fundador configuraba hoja, consentimiento y
contexto a mano (bloqueador comercial #1). El alta guiada mueve esa configuracion al bot,
en pasos cortos, informados y reanudables.

Estado en Redis (broker ya existente, ADR-0005): 0 llamadas extra a Sheets, 0 schema nuevo.
- `onboarding:paso:{telefono}` -> JSON {"paso": str, "datos": dict} (TTL 24h)

Estados de paso:
- consentimiento: gestionado por el gate legal (politica / ARCO / suscripcion); al aceptar
  se retoma el alta guiada en el paso siguiente.
- tipo_uso: el cliente elige el tipo de uso (personal / negocio / trabajo / evento / ruta /
  proyecto).
- espacio: se pide el nombre visible y el nombre del espacio.
- contexto: país, moneda y zona (por defecto Costa Rica, CRC, America/Costa_Rica).
- categorias: categorías iniciales sugeridas según el tipo de uso.

Diseno incremental: el contrato del servicio (`obtener_paso`, `guardar_paso`,
`limpiar_paso`, `detectar_tipo_uso`) se mantiene estable; los pasos siguientes se incorporan
sobre esta base sin cambiar el contrato.
"""

import json
import logging
import re
from typing import Any

import redis.asyncio as aioredis

from app.config import settings
from services.politica_service import _normalizar

logger = logging.getLogger(__name__)

KEY_PREFIX = "onboarding:paso"
TTL_SEGUNDOS = 86_400

PASO_CONSENTIMIENTO = "consentimiento"
PASO_TIPO_USO = "tipo_uso"
PASO_ESPACIO = "espacio"
PASO_CONTEXTO = "contexto"
PASO_CATEGORIAS = "categorias"
PASO_PRIMER_MOVIMIENTO = "primer_movimiento"
PASO_COMPLETADO = "completado"

TEXTO_ONBOARDING_TIPO_USO = (
    "Listo, ya empezamos!\n"
    "¿Para qué usas tu caja chica? Elige una opción (puedes responder solo la palabra):\n"
    "• Personal: tus gastos de casa\n"
    "• Negocio: tu tienda o emprendimiento\n"
    "• Trabajo: gastos de oficina o equipo\n"
    "• Evento: una fiesta o boda\n"
    "• Ruta: un viaje o gira\n"
    "• Proyecto: una obra o encargo"
)

TEXTO_ONBOARDING_TIPO_USO_REINTENTO = (
    "No te entendí. Responde una de estas palabras: "
    "Personal, Negocio, Trabajo, Evento, Ruta o Proyecto."
)

TEXTO_ONBOARDING_ESPACIO = (
    "¡Perfecto! Guardé ese dato como tu tipo de uso.\n"
    "Ahora, ¿cómo se llama tu espacio? Así aparecerá en tus reportes.\n"
    "Ejemplo: 'La Panadería de Ana'."
)

TEXTO_ONBOARDING_ESPACIO_REINTENTO = (
    "No pude usar ese nombre. Envíame el nombre de tu espacio " "(ej. 'La Panadería de Ana')."
)

TEXTO_ONBOARDING_CONTEXTO = (
    "¡Guardé tu espacio como «{espacio}»!\n"
    "Ahora el contexto: por defecto usaré Costa Rica, colones (₡) y hora de "
    "Costa Rica.\n"
    "Si está bien, responde 'sí'. Si no, dime tu país (ej. 'Panamá' o "
    "'México')."
)

TEXTO_ONBOARDING_CONTEXTO_CONFIRMADO = "¡Guardado! Usaré {pais}, {moneda} y hora de {pais}."

TEXTO_ONBOARDING_CONTEXTO_REINTENTO = (
    "No te entendí. Responde 'sí' para usar Costa Rica y colones, o dime tu " "país (ej. 'Panamá')."
)


def clave_paso(sender_phone: str) -> str:
    return f"{KEY_PREFIX}:{sender_phone}"


async def _redis() -> "aioredis.Redis":
    cliente = aioredis.from_url(  # type: ignore[no-untyped-call]
        settings.REDIS_URL, socket_connect_timeout=3
    )
    return cliente  # type: ignore[no-any-return]


async def obtener_paso(sender_phone: str) -> dict[str, Any] | None:
    try:
        cliente = await _redis()
        try:
            crudo = await cliente.get(clave_paso(sender_phone))
        finally:
            await cliente.aclose()
        if not crudo:
            return None
        if isinstance(crudo, bytes):
            crudo = crudo.decode("utf-8")
        return json.loads(crudo)  # type: ignore[no-any-return]
    except Exception as exc:
        logger.warning("onboarding: no se pudo leer el paso (%s)", exc)
        return None


async def guardar_paso(sender_phone: str, paso: str, **datos: Any) -> bool:
    payload: dict[str, Any] = {"paso": paso}
    payload.update(datos)
    try:
        cliente = await _redis()
        try:
            await cliente.set(clave_paso(sender_phone), json.dumps(payload), ex=TTL_SEGUNDOS)
        finally:
            await cliente.aclose()
        return True
    except Exception as exc:
        logger.warning("onboarding: no se pudo guardar el paso (%s)", exc)
        return False


async def limpiar_paso(sender_phone: str) -> bool:
    try:
        cliente = await _redis()
        try:
            await cliente.delete(clave_paso(sender_phone))
        finally:
            await cliente.aclose()
        return True
    except Exception as exc:
        logger.warning("onboarding: no se pudo limpiar el paso (%s)", exc)
        return False


_TIPOS_USO: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("personal", ("personal",)),
    ("negocio", ("negocio", "negocios")),
    ("trabajo", ("trabajo", "trabajos")),
    ("evento", ("evento", "eventos")),
    ("ruta", ("ruta", "rutas")),
    ("proyecto", ("proyecto", "proyectos")),
)


def detectar_tipo_uso(texto: str) -> str | None:
    """Detecta el tipo de uso en la respuesta del cliente al onboarding (Fase 6.1)."""
    normalizado = _normalizar(texto)
    if not normalizado:
        return None
    palabras = set(re.findall(r"[a-z0-9]+", normalizado))
    for tipo, marcas in _TIPOS_USO:
        if palabras.intersection(marcas):
            return tipo
    return None


LARGO_MAX_NOMBRE_ESPACIO = 60

_SENAL_MOVIMIENTO = re.compile(r"gaste|compre|pague|colones|dolares|[\u20a1$]")


def detectar_nombre_espacio(texto: str) -> str | None:
    """Devuelve el nombre de espacio limpio o None si no es un nombre usable."""
    nombre = " ".join(texto.split())
    if not nombre or len(nombre) > LARGO_MAX_NOMBRE_ESPACIO:
        return None
    if not any(caracter.isalnum() for caracter in nombre):
        return None
    return nombre


def parece_movimiento(texto: str) -> bool:
    """Heuristica: texto con monto y senal de gasto se trata como movimiento, no onboarding."""
    normalizado = _normalizar(texto)
    tiene_numero = bool(re.search(r"\d", normalizado))
    tiene_senal = bool(_SENAL_MOVIMIENTO.search(normalizado))
    return tiene_numero and tiene_senal


CONTEXTO_DEFECTO: dict[str, str] = {
    "pais": "Costa Rica",
    "moneda": "CRC",
    "zona": "America/Costa_Rica",
}

_PAISES_CONTEXTO: dict[str, tuple[str, str, str]] = {
    "costa rica": ("Costa Rica", "CRC", "America/Costa_Rica"),
    "panama": ("Panamá", "USD", "America/Panama"),
    "nicaragua": ("Nicaragua", "NIO", "America/Managua"),
    "honduras": ("Honduras", "HNL", "America/Tegucigalpa"),
    "guatemala": ("Guatemala", "GTQ", "America/Guatemala"),
    "el salvador": ("El Salvador", "USD", "America/El_Salvador"),
    "mexico": ("México", "MXN", "America/Mexico_City"),
    "colombia": ("Colombia", "COP", "America/Bogota"),
    "peru": ("Perú", "PEN", "America/Lima"),
    "ecuador": ("Ecuador", "USD", "America/Guayaquil"),
    "venezuela": ("Venezuela", "VES", "America/Caracas"),
    "chile": ("Chile", "CLP", "America/Santiago"),
    "argentina": ("Argentina", "ARS", "America/Argentina/Buenos_Aires"),
    "espana": ("España", "EUR", "Europe/Madrid"),
    "estados unidos": ("Estados Unidos", "USD", "America/New_York"),
    "usa": ("Estados Unidos", "USD", "America/New_York"),
}

_AFIRMACIONES_CONTEXTO = frozenset(
    {
        "si",
        "ok",
        "okay",
        "dale",
        "correcto",
        "esta bien",
        "asi esta bien",
        "por defecto",
        "default",
        "confirmo",
        "listo",
    }
)


def detectar_contexto(texto: str) -> dict[str, str] | None:
    """Detecta el contexto (país/moneda/zona) en la respuesta al onboarding (Fase 6.1)."""
    normalizado = _normalizar(texto)
    limpio = " ".join(re.sub(r"[^a-z0-9\s]", "", normalizado).split())
    if not limpio:
        return None
    if limpio in _AFIRMACIONES_CONTEXTO:
        return dict(CONTEXTO_DEFECTO)
    for clave, (pais, moneda, zona) in _PAISES_CONTEXTO.items():
        if re.search(r"\b" + re.escape(clave) + r"\b", limpio):
            return {"pais": pais, "moneda": moneda, "zona": zona}
    return None


CATEGORIAS_BASE: dict[str, tuple[str, ...]] = {
    "personal": ("Alimentación", "Transporte", "Casa", "Salud", "Ocio", "Otros"),
    "negocio": ("Ventas", "Insumos", "Transporte", "Servicios", "Salarios", "Otros"),
    "trabajo": ("Transporte", "Comidas", "Oficina", "Servicios", "Otros"),
    "evento": ("Comida", "Local", "Decoración", "Música", "Transporte", "Otros"),
    "ruta": ("Combustible", "Peajes", "Comida", "Hospedaje", "Viáticos", "Otros"),
    "proyecto": ("Materiales", "Mano de obra", "Transporte", "Servicios", "Otros"),
}

TEXTO_ONBOARDING_CATEGORIAS = (
    "Ahora tus categorías iniciales (según tu tipo de uso):\n"
    "{lista}\n"
    "Responde 'todas' para usarlas, o dime cambios "
    "(ej. 'sin Ocio' o 'agrega Mascotas')."
)

TEXTO_ONBOARDING_CATEGORIAS_CONFIRMADO = "¡Listo! Tus categorías quedaron así: {categorias}."

TEXTO_ONBOARDING_CATEGORIAS_REINTENTO = (
    "No te entendí. Responde 'todas' para usar las categorías sugeridas, "
    "o dime cambios (ej. 'sin Ocio' o 'agrega Mascotas')."
)

_AFIRMACIONES_CATEGORIAS = frozenset(
    {
        "todas",
        "todos",
        "si",
        "ok",
        "dale",
        "correcto",
        "esta bien",
        "asi esta bien",
        "listo",
        "acepto",
        "dejarlas",
        "dejalas",
        "estan bien",
        "me sirven",
    }
)

_VERBOS_QUITAR = frozenset({"sin", "quita", "quitar", "elimina", "eliminar", "saca", "sacar"})
_VERBOS_AGREGAR = frozenset(
    {"agrega", "agregar", "anade", "crea", "crear", "incluye", "incluir", "suma", "sumar"}
)


def categorias_sugeridas(tipo_uso: str) -> list[str]:
    """Categorías base según el tipo de uso (Fase 6.1, spec 5.4)."""
    base = CATEGORIAS_BASE.get(_normalizar(tipo_uso).strip(), CATEGORIAS_BASE["personal"])
    return list(base)


def formatear_pregunta_categorias(tipo_uso: str) -> str:
    lista = "\n".join("• " + categoria for categoria in categorias_sugeridas(tipo_uso))
    return TEXTO_ONBOARDING_CATEGORIAS.format(lista=lista)


def procesar_categorias(texto: str, tipo_uso: str) -> list[str] | None:
    """Aplica 'todas', quitas y agregados sobre las categorías sugeridas (Fase 6.1)."""
    limpio = " ".join(re.sub(r"[^a-z0-9\s,]", " ", _normalizar(texto)).split())
    if not limpio:
        return None
    if limpio in _AFIRMACIONES_CATEGORIAS:
        return categorias_sugeridas(tipo_uso)

    base = {_normalizar(categoria): categoria for categoria in categorias_sugeridas(tipo_uso)}

    if limpio.startswith("todas menos ") or limpio.startswith("todas excepto "):
        resto = limpio.split(" ", 2)[2]
        for nombre in re.split(r",| y | e ", resto):
            base.pop(nombre.strip(), None)
        return list(base.values()) or ["Otros"]

    limpio = limpio.replace("no quiero ", "sin ").replace("no me interesa ", "sin ")
    resultado = dict(base)
    verbo_actual: str | None = None
    aplicado = False
    for trozo in re.split(r",| y | e ", limpio):
        palabras = trozo.split()
        if not palabras:
            continue
        if palabras[0] in _VERBOS_QUITAR or palabras[0] in _VERBOS_AGREGAR:
            verbo_actual = palabras[0]
            resto = " ".join(palabras[1:]).strip()
        else:
            resto = " ".join(palabras).strip()
        if not resto or verbo_actual is None:
            continue
        if verbo_actual in _VERBOS_QUITAR:
            resultado.pop(resto, None)
            aplicado = True
        else:
            resultado[resto] = resto[:1].upper() + resto[1:]
            aplicado = True
    if not aplicado:
        return None
    return list(resultado.values()) or ["Otros"]


TEXTO_ONBOARDING_PRIMER_MOVIMIENTO = (
    "¡Listo! Ya casi terminamos.\n"
    "Enviame tu primer gasto (ej. 'gasté 2 mil en café') o responde 'saltar' "
    "si preferís empezar después."
)

TEXTO_ONBOARDING_RESUMEN = (
    "¡Excelente! Tu espacio «{espacio}» quedó listo.\n"
    "• Tipo de uso: {tipo_uso}\n"
    "• País: {pais} ({moneda})\n"
    "• Categorías: {categorias}\n"
    "{linea_movimiento}"
    "Ya podés registrar gastos por audio o texto."
)

TEXTO_ONBOARDING_RESUMEN_SIN_MOVIMIENTO = (
    "• Primer movimiento: pendiente (mandámelo cuando quieras).\n"
)

_SIMBOLOS_MONEDA = {
    "CRC": "₡",
    "USD": "$",
    "MXN": "$",
    "COP": "$",
    "EUR": "€",
}

_AFIRMACIONES_SALTAR = frozenset(
    {
        "saltar",
        "saltear",
        "omitir",
        "saltar por ahora",
        "luego",
        "despues",
        "despues lo hago",
        "luego lo hago",
        "ahora no",
        "no",
        "manana",
        "mas tarde",
    }
)


def detectar_saltar_primer_movimiento(texto: str) -> bool:
    """Detecta si el cliente prefiere no registrar el primer movimiento ahora (Fase 6.1)."""
    limpio = " ".join(re.sub(r"[^a-z0-9\s]", "", _normalizar(texto)).split())
    return limpio in _AFIRMACIONES_SALTAR


def _simbolo_moneda(moneda: str) -> str:
    return _SIMBOLOS_MONEDA.get(moneda, moneda + " ")


def texto_resumen_onboarding(
    estado: dict[str, Any], movimiento: dict[str, Any] | None = None
) -> str:
    """Arma el resumen de cierre del alta guiada (Fase 6.1)."""
    moneda = str(estado.get("moneda", "CRC"))
    if movimiento is not None:
        monto = movimiento.get("monto", 0)
        linea_movimiento = (
            "• Primer movimiento: "
            f"{movimiento.get('categoria', 'Otros')} - "
            f"{_simbolo_moneda(moneda)}{monto}\n"
        )
    else:
        linea_movimiento = TEXTO_ONBOARDING_RESUMEN_SIN_MOVIMIENTO
    return TEXTO_ONBOARDING_RESUMEN.format(
        espacio=estado.get("espacio", "Mi espacio"),
        tipo_uso=estado.get("tipo_uso", "personal"),
        pais=estado.get("pais", "Costa Rica"),
        moneda=moneda,
        categorias=estado.get("categorias", "Otros"),
        linea_movimiento=linea_movimiento,
    )
