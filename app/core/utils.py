def extraer_datos_audio(payload: dict) -> dict[str, str] | None:
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
            return {"media_id": audio.get("id"), "from_phone": messages.get("from")}
    except (IndexError, KeyError, AttributeError):
        return None

    return None
