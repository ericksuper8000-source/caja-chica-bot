import hashlib
import hmac
from typing import Optional
from fastapi import Header, HTTPException, Request
from app.config import settings

APP_SECRET = settings.WHATSAPP_APP_SECRET


async def validar_firma_whatsapp(
    request: Request, x_hub_signature_256: Optional[str] = Header(None)
) -> None:
    if not x_hub_signature_256:
        raise HTTPException(status_code=403, detail="Falta la firma de seguridad")

    try:
        signature_prefix, actual_signature = x_hub_signature_256.split("=")
        if signature_prefix != "sha256":
            raise HTTPException(status_code=403, detail="Formato de firma inválido")
    except ValueError:
        raise HTTPException(status_code=403, detail="Estructura de firma dañada")

    body_bytes = await request.body()

    expected_signature = hmac.new(
        APP_SECRET.encode("utf-8"), body_bytes, hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, actual_signature):
        raise HTTPException(
            status_code=403, detail="Firma inválida. Origen no legítimo."
        )
