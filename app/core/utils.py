from typing import Any


def extraer_datos_audio(payload: dict[str, Any]) -> dict[str, str] | None:
    """
    Navega el payload del webhook de WhatsApp para extraer el media_id y el teléfono.
    Retorna un diccionario con {'media_id': ..., 'from_phone': ...} o None si no es audio.
    """
    try:
        entry = payload.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])[0]

        if messages.get("type") == "audio":
            audio = messages.get("audio", {})
            media_id = audio.get("id")
            from_phone = messages.get("from")
            if media_id and from_phone:
                return {"media_id": media_id, "from_phone": from_phone}
            return None
    except (IndexError, KeyError, AttributeError):
        return None

    return None


def extraer_datos_texto(payload: dict[str, Any]) -> dict[str, str] | None:
    """
    Navega el payload del webhook de WhatsApp para extraer el cuerpo del mensaje
    de texto y el teléfono del remitente. Retorna {'texto': ..., 'from_phone': ...}
    o None si el mensaje no es de tipo texto (canal de texto, fase 6.5).
    """
    try:
        entry = payload.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])[0]

        if messages.get("type") == "text":
            texto = messages.get("text", {}).get("body")
            from_phone = messages.get("from")
            if texto and from_phone:
                return {"texto": texto, "from_phone": from_phone}
            return None
    except (IndexError, KeyError, AttributeError):
        return None

    return None
