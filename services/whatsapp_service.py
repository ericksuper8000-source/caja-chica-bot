import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

LIMITE_TEXTO_WHATSAPP = 4000
LIMITE_CAPTION_WHATSAPP = 1024
"""Máximo del pie de foto/imagen que acepta WhatsApp (1.024 caracteres)."""


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


async def enviar_imagen_whatsapp(to_phone: str, imagen: bytes, caption: str) -> bool:
    """
    Envía una imagen (PNG en bytes) con pie de texto por la API de WhatsApp Business:
    primero se sube el archivo a Meta (POST /{phone_id}/media) y luego se manda el
    mensaje tipo image con el media_id.

    Devuelve False ante CUALQUIER fallo en vez de lanzar: el llamador (pipeline de
    reportes) degrada a texto — la tarjeta es cosmética, el dato no se pierde.
    El caption se recorta al límite de WhatsApp por si el resumen viene largo.
    """
    base = f"https://graph.facebook.com/v18.0/{settings.WHATSAPP_PHONE_NUMBER_ID}"
    headers = {"Authorization": f"Bearer {settings.WHATSAPP_API_TOKEN}"}

    try:
        async with httpx.AsyncClient() as _http_client:
            subida = await _http_client.post(
                f"{base}/media",
                headers=headers,
                data={"messaging_product": "whatsapp", "type": "image/png"},
                files={"file": ("reporte.png", imagen, "image/png")},
            )
            subida.raise_for_status()
            media_id = subida.json().get("id")
            if not media_id:
                logger.error("Error al subir la imagen a WhatsApp: Meta no devolvió media_id.")
                return False

            payload = {
                "messaging_product": "whatsapp",
                "to": to_phone,
                "type": "image",
                "image": {"id": media_id, "caption": caption[:LIMITE_CAPTION_WHATSAPP]},
            }
            respuesta = await _http_client.post(f"{base}/messages", headers=headers, json=payload)
            respuesta.raise_for_status()

        logger.info(f"Imagen enviada con éxito a {to_phone}.")
        return True

    except Exception as e:
        logger.error(f"Error al enviar imagen a WhatsApp: {e}")
        return False
