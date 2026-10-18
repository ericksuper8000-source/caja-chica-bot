import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

LIMITE_TEXTO_WHATSAPP = 4000


def dividir_mensaje_largo(texto: str, limite: int = LIMITE_TEXTO_WHATSAPP) -> list[str]:
    """
    Divide un texto largo en bloques de a lo sumo `limite` caracteres, respetando
    los saltos de línea. WhatsApp rechaza con HTTP 400 los mensajes de texto de
    más de 4096 caracteres (por eso el límite por defecto de 4000, con margen).
    Una línea individual más larga que el límite se parte en seco.
    """
    if not texto:
        return []

    bloques: list[str] = []
    actual: list[str] = []

    def _largo(lineas: list[str]) -> int:
        return sum(len(linea) for linea in lineas) + len(lineas) - 1

    for linea in texto.split("\n"):
        fragmentos = [linea[i : i + limite] for i in range(0, len(linea), limite)] or [""]
        for fragmento in fragmentos:
            if actual and _largo(actual) + 1 + len(fragmento) > limite:
                bloques.append("\n".join(actual))
                actual = []
            actual.append(fragmento)

    if actual:
        bloques.append("\n".join(actual))
    return bloques


async def enviar_mensaje_whatsapp(to_phone: str, mensaje: str) -> bool:
    """
    Envía un mensaje de texto a través de la API de WhatsApp Business.

    Crea un AsyncClient por llamada: cada tarea de Celery ejecuta su propio
    event loop (asyncio.run), y un cliente global quedaría atado a un loop
    ya cerrado (error "Event loop is closed").
    """
    url = f"https://graph.facebook.com/v18.0/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_API_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "text",
        "text": {"body": mensaje},
    }

    try:
        async with httpx.AsyncClient() as _http_client:
            response = await _http_client.post(url, headers=headers, json=payload)
            response.raise_for_status()

        logger.info(f"Mensaje enviado con éxito a {to_phone}.")
        return True

    except Exception as e:
        logger.error(f"Error al enviar mensaje a WhatsApp: {e}")
        return False
