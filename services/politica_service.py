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


def _normalizar(texto: str) -> str:
    """Normaliza el texto: minúsculas, sin tildes y con espacios colapsados."""
    texto = texto.lower()
    texto = re.sub(r"[áàäâ]", "a", texto)
    texto = re.sub(r"[éèëê]", "e", texto)
    texto = re.sub(r"[íìïî]", "i", texto)
    texto = re.sub(r"[óòöô]", "o", texto)
    texto = re.sub(r"[úùüû]", "u", texto)
    return " ".join(texto.split())


def detectar_respuesta_consentimiento(texto: str) -> Literal["aceptar", "rechazar"] | None:
    """
    Detecta si un mensaje de texto constituye la aceptación o el rechazo explícito
    de la política de privacidad (Fase 6.5.1, ADR-0011). Retorna 'aceptar',
    'rechazar' o None si el mensaje no es una respuesta de consentimiento.
    """
    normalizado = _normalizar(texto)
    if not normalizado:
        return None

    if _contiene_negacion(normalizado):
        return "rechazar"

    if any(
        marca in normalizado
        for marca in (
            "acepto",
            "aceptar",
            "aceptamos",
            "estoy de acuerdo",
            "de acuerdo",
            "si acepto",
        )
    ):
        return "aceptar"

    return None


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
