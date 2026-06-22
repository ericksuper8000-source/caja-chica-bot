from pydantic import BaseModel
from typing import Any  # 👈 Importamos Any para el tipado estricto del dict


# Asegúrate de que el modelo se vea estructurado de esta forma:
class WebhookPayload(BaseModel):
    object: str
    # Cambia el 'dict' plano por 'dict[str, Any]' en el campo correspondiente
    entry: list[dict[str, Any]]
