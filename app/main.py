import logging

import redis.asyncio as aioredis
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import settings
from app.core.security import validar_firma_whatsapp
from app.core.utils import extraer_datos_audio
from app.schemas.whatsapp import WebhookPayload
from workers.celery_app import celery_app
from workers.tasks import download_audio_task

logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="Caja Chica Bot API", version="0.1.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

TOKEN_VERIFICACION = settings.WHATSAPP_VERIFY_TOKEN


@app.get("/health")
async def health_check() -> dict[str, str]:
    statuses: dict[str, str] = {}

    # Redis health check
    try:
        r = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=3)  # type: ignore[no-untyped-call]
        await r.ping()
        await r.aclose()
        statuses["redis"] = "ok"
    except Exception as e:
        logger.error("Health check — Redis: %s", e)
        statuses["redis"] = "error"

    # Celery worker health check
    try:
        workers = celery_app.control.ping(timeout=3)
        if workers:
            statuses["celery"] = "ok"
        else:
            statuses["celery"] = "no_workers"
    except Exception as e:
        logger.error("Health check — Celery: %s", e)
        statuses["celery"] = "error"

    overall = all(v == "ok" for v in statuses.values())
    statuses["status"] = "healthy" if overall else "degraded"

    if not overall:
        raise HTTPException(status_code=503, detail=statuses)
    return statuses


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


@limiter.limit("1000/minute" if settings.ENVIRONMENT == "test" else "10/minute")
@app.post("/v1/whatsapp/webhook", dependencies=[Depends(validar_firma_whatsapp)])
async def recibir_mensaje(request: Request, payload: WebhookPayload) -> dict[str, str]:
    # 1. Intentamos extraer los datos usando nuestra utilidad
    datos_audio = extraer_datos_audio(payload.model_dump(by_alias=True))

    if datos_audio:
        logger.info(f"Audio detectado: {datos_audio}")
        # Despachamos la tarea a Celery
        download_audio_task.delay(datos_audio["media_id"], datos_audio["from_phone"])
        logger.info(f"Tarea enviada a Celery para el media_id: {datos_audio['media_id']}")
    else:
        logger.debug("Mensaje recibido (no es audio o formato no soportado)")

    # Retorno flexible para evitar ResponseValidationError
    return {"status": "recibido"}
