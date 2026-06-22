from pydantic import BaseModel


# Este es el molde básico para entender quién nos escribe y qué nos dice
class MensajeTexto(BaseModel):
    id: str
    texto: str
    remitente: str  # El número de teléfono de la persona (ej: "50688888888")


# Este es el molde del paquete grande que nos enviará Meta
class WebhookPayload(BaseModel):
    object: str
    entry: list[dict]  # Por ahora lo dejamos flexible para inspeccionar cómo viene
