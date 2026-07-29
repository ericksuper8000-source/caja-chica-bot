import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_http_client: httpx.AsyncClient | None = None


async def enviar_mensaje_whatsapp(to_phone: str, mensaje: str) -> bool:
    """
    Envía un mensaje de texto a través de la API de WhatsApp Business.
    """
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient()

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
        response = await _http_client.post(url, headers=headers, json=payload)
        response.raise_for_status()

        logger.info(f"Mensaje enviado con éxito a {to_phone}.")
        return True

    except Exception as e:
        logger.error(f"Error al enviar mensaje a WhatsApp: {e}")
        return False
