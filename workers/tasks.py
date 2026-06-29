import os
import httpx
import logging
import asyncio
from workers.celery_app import celery_app
from app.config import settings
from services.sheets_service import append_transaction_to_sheet

logger = logging.getLogger(__name__)


@celery_app.task(name="workers.tasks.download_audio_task")
def download_audio_task(media_id: str) -> str:
    """
    Pipeline Orquestador:
    1. Descarga el audio desde los servidores de Meta.
    2. [Fase 4 - Pendiente] Procesa con OpenAI Whisper y Chat API.
    3. Persiste de forma segura en Google Sheets conectando el puente asíncrono.
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
        
        logger.info(f"Audio descargado con éxito en: {file_path}")

        # ---------------------------------------------------------------------
        # PASO B: Mock del Parser de OpenAI (Estructura de la Fase 4)
        # ---------------------------------------------------------------------
        fake_parsed_transaction = {
            "monto": 3500,
            "categoria": "Servicios",
            "tipo_movimiento": "Gasto",
            "detalle": "Prueba de Integración End-to-End Celery-Sheets",
        }

        # ---------------------------------------------------------------------
        # PASO C: Persistencia Asíncrona en Google Sheets vía Puente asyncio
        # ---------------------------------------------------------------------
        success = asyncio.run(append_transaction_to_sheet(fake_parsed_transaction))
        if success:
            logger.info("Integración E2E completada: Fila registrada en Google Sheets.")
        else:
            logger.error("Fallo la persistencia en el flujo de Celery.")
            
        return file_path

    except Exception as e:
        logger.error(f"Error crítico en el pipeline de la tarea: {e}")
        raise e

    finally:
        # Limpieza obligatoria del archivo temporal para evitar fugas de almacenamiento
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Archivo temporal eliminado de forma segura: {file_path}")