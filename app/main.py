from fastapi import FastAPI, Query, HTTPException, Depends
from fastapi.responses import PlainTextResponse
from app.schemas.whatsapp import WebhookPayload
from app.core.security import validar_firma_whatsapp
from workers.tasks import download_audio_task  # 👈 Importamos la tarea

app = FastAPI(title="Caja Chica Bot API", version="0.1.0")

# Token de verificación real (debería venir del .env)
TOKEN_VERIFICACION_TEMPORAL = "mi_token_secreto_tico_123"


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "healthy"}


@app.get("/v1/whatsapp/webhook", response_class=PlainTextResponse)
async def verificar_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
) -> str:
    if hub_mode == "subscribe" and hub_verify_token == TOKEN_VERIFICACION_TEMPORAL:
        return hub_challenge
    raise HTTPException(status_code=403, detail="Token de verificación inválido")


@app.post("/v1/whatsapp/webhook", dependencies=[Depends(validar_firma_whatsapp)])
async def recibir_mensaje(payload: WebhookPayload) -> dict[str, str]:
    """
    Recibe el webhook, extrae el media_id y el número de teléfono,
    y dispara la tarea asíncrona de Celery.
    """
    try:
        # Navegamos la estructura de Meta para extraer los datos
        entry = payload.entry[0]
        changes = entry["changes"][0]
        value = changes["value"]

        if "messages" in value:
            message = value["messages"][0]

            # Solo procesamos si es un mensaje de tipo audio
            if message.get("type") == "audio":
                audio = message["audio"]
                media_id = audio["id"]
                sender_phone = message["from"]

                # Disparamos la tarea de fondo
                download_audio_task.delay(media_id, sender_phone)

                return {"status": "procesando_audio"}

        return {"status": "ignorado_no_es_audio"}

    except (KeyError, IndexError) as e:
        print(f"Error parseando payload de Meta: {e}")
        return {"status": "error_formato"}
