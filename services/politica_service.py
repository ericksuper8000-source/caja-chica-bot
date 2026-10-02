import re
from typing import Literal

POLITICA_VERSION = "1.0"

TEXTO_POLITICA_PRIVACIDAD = (
    "POLÍTICA DE PRIVACIDAD (versión 1.0)\n"
    "\n"
    "El Analista Financiero de Caja Chica guarda y procesa tus datos personales "
    "(número de WhatsApp, notas de voz, montos, categorías y detalles de tus "
    "movimientos) únicamente para llevar el control de tu caja chica.\n"
    "\n"
    "Tus audios y textos se procesan con OpenAI (Whisper + GPT-4o-mini) y tus "
    "transacciones se guardan en Google Sheets. Ambos son servicios en servidores "
    "fuera de Costa Rica, por lo que tu aceptación incluye la transferencia "
    "internacional de tus datos (art. 14, Ley 8968).\n"
    "\n"
    "Tus datos NO se venden ni se comparten con terceros para publicidad.\n"
    "\n"
    "Tenés derecho a: (1) acceder a tus datos, (2) corregirlos, (3) cancelarlos y "
    "(4) oponerte a su uso (derechos ARCO). Podés pedir 'exporta mis datos' o "
    "'darme de baja' en cualquier momento.\n"
    "\n"
    "Respondé 'ACEPTO' para aceptar la política y usar el bot, o 'NO ACEPTO' para "
    "rechazarla. Sin tu aceptación no se procesa ni se guarda ninguna transacción."
)

TEXTO_ACEPTACION_CONFIRMADA = (
    "¡Gracias! Aceptaste la política de privacidad. Ya podés registrar tus "
    "movimientos de caja chica."
)

TEXTO_RECHAZO_REGISTRADO = (
    "Entendido. No aceptaste la política de privacidad, así que no guardaré ni "
    "procesaré ninguna de tus transacciones. Si cambiás de opinión, respondé "
    "'ACEPTO' para volver a intentarlo."
)

# Fase 6.5.3 — Derechos ARCO (Ley 8968): exportación y baja (ADR-0011).
TEXTO_EXPORTACION_ENCABEZADO = "Estos son tus movimientos registrados:"
TEXTO_EXPORTACION_VACIA = (
    "No tenés movimientos registrados todavía. Enviame tu primer gasto o ingreso "
    "para que empiece a llevar tu caja chica."
)
TEXTO_BAJA_CONFIRMADA = (
    "Entendido. Tu cuenta quedó cancelada y ya no se registrarán tus movimientos. "
    "Tus datos quedan guardados por si necesitás reclamarlos. Si fue un error o "
    "querés reactivar tu cuenta, escribí 'ACEPTO'."
)

# Fase 6.5.6 — Re-consentimiento por cambio de versión (ADR-0011).
TEXTO_RE_CONSENTIMIENTO = (
    "La política de privacidad se actualizó a la versión {version}. "
    "Para seguir usando el bot, leé la política nueva y respondé 'ACEPTO' "
    "para volver a aceptarla."
)


def _normalizar(texto: str) -> str:
    """Normaliza el texto: minúsculas, sin tildes y con espacios colapsados."""
    texto = texto.lower()
    texto = re.sub(r"[áàäâ]", "a", texto)
    texto = re.sub(r"[éèëê]", "e", texto)
    texto = re.sub(r"[íìïî]", "i", texto)
    texto = re.sub(r"[óòöô]", "o", texto)
    texto = re.sub(r"[úùüû]", "u", texto)
    return " ".join(texto.split())


_MARCAS_ACEPTACION = (
    "acepto",
    "aceptar",
    "aceptamos",
    "estoy de acuerdo",
    "de acuerdo",
    "si acepto",
)
"""Marcas de aceptación explícita. Se evalúan sobre el texto ya normalizado."""

_NEGACION_AMBIGUA = re.compile(r"\b(no|nunca|jamas|tampoco|nada)\b")
"""
Palabra de negación presente en el mensaje. El texto normalizado ya no tiene tildes,
por eso el patrón busca `jamas` y no `jamás`.

**Por qué existe (fix 01/10/2026).** El gate buscaba `aceptar` por *substring*, así que
en `'no quiero aceptar'` no encontraba la fórmula de rechazo (`no acepto`) pero sí
encontraba `aceptar` dentro del texto → devolvía `aceptar`. El usuario decía que NO y el
bot registraba consentimiento válido: datos procesados sin permiso, que es justo lo que
la Ley 8968 prohíbe.
"""


def detectar_respuesta_consentimiento(texto: str) -> Literal["aceptar", "rechazar"] | None:
    """
    Detecta si un mensaje de texto constituye la aceptación o el rechazo explícito
    de la política de privacidad (Fase 6.5.1, ADR-0011). Retorna 'aceptar', 'rechazar'
    o None si el mensaje no es una respuesta de consentimiento.

    **Criterio de seguridad: ante la duda, `None` — nunca `aceptar`.** Los dos sentidos de
    equivocarse no son equivalentes:

    - `aceptar` de más = registrar consentimiento que el usuario NO dio y procesar sus
      datos. Es riesgo legal bajo la Ley 8968.
    - `None` de más = el bot reenvía la política y el usuario contesta otra vez. Cuesta
      un mensaje.

    Cuando hay negación y aceptación a la vez (`'no quiero aceptar'`, `'acepto no'`),
    la decisión no se toma: se devuelve `None` y se repregunta.
    """
    normalizado = _normalizar(texto)
    if not normalizado:
        return None

    # 1. Rechazo explícito: manda sobre todo lo demás.
    if _contiene_negacion(normalizado):
        return "rechazar"

    tiene_aceptacion = any(marca in normalizado for marca in _MARCAS_ACEPTACION)
    if not tiene_aceptacion:
        return None

    # 2. Negación + aceptación en el mismo mensaje = ambiguo. No se decide.
    if _NEGACION_AMBIGUA.search(normalizado):
        return None

    # 3. Aceptación limpia.
    return "aceptar"


def _contiene_negacion(texto_normalizado: str) -> bool:
    """Detecta expresiones de rechazo antes de las de aceptación (evita falsos 'acepto')."""
    return any(
        marca in texto_normalizado
        for marca in (
            "no acepto",
            "no aceptar",
            "no aceptamos",
            "rechazo",
            "no estoy de acuerdo",
            "no de acuerdo",
        )
    )


def detectar_respuesta_exportacion_baja(texto: str) -> Literal["exportar", "baja"] | None:
    """
    Detecta si un mensaje pide exportar los datos ("exporta mis datos") o darse de
    baja ("darme de baja") — derechos ARCO de la Ley 8968 (Fase 6.5.3, ADR-0011).
    Retorna 'exportar', 'baja' o None si el mensaje no es uno de estos comandos.
    """
    normalizado = _normalizar(texto)
    if not normalizado:
        return None

    if any(
        marca in normalizado
        for marca in (
            "exporta mis datos",
            "exportar mis datos",
            "exporta mi informacion",
            "exportar mi informacion",
            "exportacion",
            "exportar datos",
            "mis datos",
            "quiero mis datos",
            "pedir mis datos",
        )
    ):
        return "exportar"

    if any(
        marca in normalizado
        for marca in (
            "darme de baja",
            "darme baja",
            "me doy de baja",
            "darme de baja del servicio",
            "cancelar mi cuenta",
            "cancelar cuenta",
            "eliminar mi cuenta",
        )
    ):
        return "baja"

    return None


# ==========================================
# FASE 6.5.6 — RE-CONSENTIMIENTO POR VERSIÓN (ADR-0011)
# ==========================================
def _normalizar_version(version: str) -> str:
    """Normaliza una versión para comparar (evita falsas diferencias: '1.0' vs '1')."""
    v = str(version).strip()
    while v.endswith(".0"):
        v = v[:-2]
    return v


def politica_aceptada_vigente(consentimiento: dict[str, object] | None) -> bool:
    """
    True si el consentimiento es un 'aceptado' de la versión vigente de la política
    (Fase 6.5.6, ADR-0011). Un 'aceptado' de una versión anterior queda pendiente de
    re-consentimiento; cualquier otro estado (None, 'rechazado', 'cancelado') no pasa.
    """
    if consentimiento is None:
        return False
    if consentimiento.get("estado") != "aceptado":
        return False
    return _normalizar_version(
        str(consentimiento.get("version_politica", ""))
    ) == _normalizar_version(POLITICA_VERSION)
