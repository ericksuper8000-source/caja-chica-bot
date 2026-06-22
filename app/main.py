from fastapi import FastAPI, Query, HTTPException, Depends, Request  # 👈 Agregamos Depends y Request
from fastapi.responses import PlainTextResponse
from app.schemas.whatsapp import WebhookPayload
from app.core.security import validar_firma_whatsapp  # 👈 Importamos nuestro escáner

app = FastAPI(title="Caja Chica Bot API", version="0.1.0")

# Token temporal para validar el desarrollo del Paso 1.1
TOKEN_VERIFICACION_TEMPORAL = "mi_token_secreto_tico_123"

@app.get("/health")
async def health_check() -> dict[str, str]:
    """Endpoint de sanidad."""
    return {"status": "healthy"}

@app.get("/v1/whatsapp/webhook", response_class=PlainTextResponse)
async def verificar_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge")
) -> str:
    """
    Paso 1.1: Resuelve el desafío de verificación (handshake) de Meta API.
    Devuelve el hub.challenge en texto plano si el token coincide.
    """
    if hub_mode == "subscribe" and hub_verify_token == TOKEN_VERIFICACION_TEMPORAL:
        if hub_challenge:
            return hub_challenge
    
    raise HTTPException(status_code=403, detail="Token de verificación inválido")

# 🔐 Aquí agregamos el guarda de seguridad usando Depends(validar_firma_whatsapp)
@app.post("/v1/whatsapp/webhook", dependencies=[Depends(validar_firma_whatsapp)])
async def recibir_mensaje(payload: WebhookPayload) -> dict[str, str]:
    """
    Paso 1.2 & 1.3: Recibe las notificaciones de mensajes de Meta.
    Valida la estructura con Pydantic y el origen con X-Hub-Signature-256.
    """
    # Si llega aquí, significa que pasó el escáner criptográfico con éxito
    print(f"📦 Payload verificado y recibido de Meta: {payload.model_dump()}")
    
    return {"status": "recibido", "object": payload.object}