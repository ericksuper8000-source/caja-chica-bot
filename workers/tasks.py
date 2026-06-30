import os
import httpx
import logging
import asyncio
from typing import Any
from workers.celery_app import celery_app
from app.config import settings
from services.sheets_service import append_transaction_to_sheet
from services.openai_service import procesar_audio_a_transaccion
from services.whatsapp_service import enviar_mensaje_whatsapp

logger = logging.getLogger(__name__)


async def run_pipeline(media_id: str, user_phone: str) -> str:
    """
    Pipeline completo: Descarga, IA, Sheets y Notificación.
    """
    headers: dict[str, str] = {"Authorization": f"Bearer {settings.WHATSAPP_API_TOKEN}"}
    file_path: str = f"/tmp/caja_chica/{media_id}.ogg"

    try:
        # A) Descarga
        async with httpx.AsyncClient() as client:
            meta_url: str = f"https://graph.facebook.com/v18.0/{media_id}"
            response = await client.get(meta_url, headers=headers)
            response.raise_for_status()
            media_data: dict[str, Any] = response.json()

            download_url: str = media_data.get("url", "")
            audio_response = await client.get(download_url, headers=headers)
            audio_content: bytes = audio_response.content

        os.makedirs("/tmp/caja_chica", exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(audio_content)

        # B) Procesamiento IA
        parsed_data: dict[str, Any] | None = await procesar_audio_a_transaccion(
            file_path
        )

        if not parsed_data:
            await enviar_mensaje_whatsapp(
                user_phone, "No pude entender el audio, ¿podrías repetirlo?"
            )
            return "Error: IA no pudo procesar la entrada."

        # C) Persistencia
        await append_transaction_to_sheet(parsed_data)

        # D) Notificación al usuario
        mensaje_confirmacion: str = (
            f"✅ ¡Entendido, jefe! Registré: {parsed_data.get('detalle', 'Gasto')} "
            f"por ₡{parsed_data.get('monto', 0)} en {parsed_data.get('categoria', 'Varios')}."
        )
        await enviar_mensaje_whatsapp(user_phone, mensaje_confirmacion)

        return "Pipeline ejecutado con éxito"

    except Exception as e:
        logger.error(f"Error crítico en el pipeline: {e}")
        return f"Error: {str(e)}"
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


# type: ignore[misc]
@celery_app.task(name="workers.tasks.download_audio_task")
def download_audio_task(media_id: str, user_phone: str) -> str:
    """
    Tarea de Celery que inicia el pipeline asíncrono.
    """
    return asyncio.run(run_pipeline(media_id, user_phone))
