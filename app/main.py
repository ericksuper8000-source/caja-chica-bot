import logging

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse

from app.config import settings
from app.core.security import validar_firma_whatsapp
from app.core.utils import extraer_datos_audio
from app.schemas.whatsapp import WebhookPayload
from workers.tasks import download_audio_task

logger = logging.getLogger(__name__)

app = FastAPI(title="Caja Chica Bot API", version="0.1.0")

TOKEN_VERIFICACION = settings.WHATSAPP_VERIFY_TOKEN


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "healthy"}


@app.get("/v1/whatsapp/webhook", response_class=PlainTextResponse)
async def verificar_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
) -> str:
    if hub_mode == "subscribe" and hub_verify_token == TOKEN_VERIFICACION:
        if hub_challenge:
            return hub_challenge
    raise HTTPException(status_code=403, detail="Token de verificación inválido")


@app.post("/v1/whatsapp/webhook", dependencies=[Depends(validar_firma_whatsapp)])
async def recibir_mensaje(payload: WebhookPayload) -> dict[str, str]:
    # 1. Intentamos extraer los datos usando nuestra utilidad
    datos_audio = extraer_datos_audio(payload.model_dump())

    if datos_audio:
        logger.info(f"Audio detectado: {datos_audio}")
        # Despachamos la tarea a Celery
        download_audio_task.delay(datos_audio["media_id"], datos_audio["from_phone"])
        logger.info(
            f"Tarea enviada a Celery para el media_id: {datos_audio['media_id']}"
        )
    else:
        logger.debug("Mensaje recibido (no es audio o formato no soportado)")

    # Retorno flexible para evitar ResponseValidationError
    return {"status": "recibido"}
