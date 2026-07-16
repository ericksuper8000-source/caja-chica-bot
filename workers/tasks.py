import asyncio
import logging
import os

import httpx

from app.config import settings
from services.openai_service import (
    parse_financial_text,
    transcribir_audio_whisper,
)
from services.sheets_service import append_transaction_to_sheet
from services.whatsapp_service import enviar_mensaje_whatsapp
from workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="workers.tasks.download_audio_task")
def download_audio_task(media_id: str) -> str:
    # 1. Validación de seguridad antes de proceder
    token = settings.WHATSAPP_API_TOKEN
    if not token or token == "your_meta_access_token_here":
        logger.error(
            "Integración abortada: WHATSAPP_API_TOKEN no configurado"
            " correctamente para media_id: %s",
            media_id,
        )
        return "ERROR_MISSING_TOKEN"

    headers = {"Authorization": f"Bearer {token}"}
    file_path = f"/tmp/caja_chica/{media_id}.ogg"

    try:
        # 2. Descarga del binario de Meta
        with httpx.Client() as client:
            meta_url = f"https://graph.facebook.com/v18.0/{media_id}"
            response = client.get(meta_url, headers=headers)
            response.raise_for_status()
            media_data = response.json()

            download_url = media_data.get("url")
            if not download_url:
                raise ValueError(f"No se encontró la URL para el media_id: {media_id}")

            audio_response = client.get(download_url, headers=headers)
            audio_response.raise_for_status()

            os.makedirs("/tmp/caja_chica", exist_ok=True)
            with open(file_path, "wb") as f:
                f.write(audio_response.content)

        # 3. Procesamiento IA
        transcripcion = asyncio.run(transcribir_audio_whisper(file_path))
        transaction_data = asyncio.run(parse_financial_text(transcripcion or ""))

        # 4. Persistencia e Integración de Respuesta
        if transaction_data:
            asyncio.run(append_transaction_to_sheet(transaction_data))
            # Envío de respuesta al usuario vía WhatsApp
            asyncio.run(
                enviar_mensaje_whatsapp(
                    to_phone=settings.WHATSAPP_PHONE_NUMBER_ID,
                    mensaje=f"Transacción registrada: {transaction_data['categoria']} - ₡{transaction_data['monto']}",
                )
            )

        return file_path

    except Exception as e:
        logger.error(f"Error en el pipeline: {e}")
        raise

    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
