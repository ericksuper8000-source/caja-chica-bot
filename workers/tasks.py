import os
import httpx
import logging
import asyncio
from workers.celery_app import celery_app
from app.config import settings
from services.sheets_service import append_transaction_to_sheet
from services.openai_service import transcribir_audio_whisper, parse_financial_text

logger = logging.getLogger(__name__)


@celery_app.task(name="workers.tasks.download_audio_task")
def download_audio_task(media_id: str) -> str:
    """
    Pipeline Orquestador:
    1. Descarga el audio desde Meta.
    2. Transcribe con Whisper.
    3. Extrae datos financieros con GPT-4o.
    4. Persiste en Google Sheets.
    """
    headers = {"Authorization": f"Bearer {settings.WHATSAPP_API_TOKEN}"}
    file_path = f"/tmp/caja_chica/{media_id}.ogg"

    try:
        # ---------------------------------------------------------------------
        # PASO A: Descarga del binario de Meta
        # ---------------------------------------------------------------------
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
            audio_content = audio_response.content

        os.makedirs("/tmp/caja_chica", exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(audio_content)

        # ---------------------------------------------------------------------
        # PASO B: Procesamiento IA (Transcripción + Extracción)
        # ---------------------------------------------------------------------
        transcripcion = asyncio.run(transcribir_audio_whisper(file_path))
        logger.info(f"Transcripción: {transcripcion}")

        # Aquí llamamos al servicio de extracción asegurando que enviamos un string
        transaction_data = asyncio.run(parse_financial_text(transcripcion or ""))
        logger.info(f"Datos extraídos por IA: {transaction_data}")

        # ---------------------------------------------------------------------
        # PASO C: Persistencia Asíncrona
        # ---------------------------------------------------------------------
        if transaction_data:
            success = asyncio.run(append_transaction_to_sheet(transaction_data))
            if success:
                logger.info("Integración E2E completada: Fila registrada.")
            else:
                logger.error("Fallo la persistencia en Google Sheets.")
        else:
            logger.warning("La IA no pudo extraer datos financieros del texto.")

        return file_path

    except Exception as e:
        logger.error(f"Error crítico en el pipeline: {e}")
        raise e

    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Archivo temporal eliminado: {file_path}")