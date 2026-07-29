#!/usr/bin/env python3
import asyncio
import concurrent.futures
import logging
import os
from collections.abc import Coroutine
from typing import Any

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


def _run_async(coro: Coroutine[Any, Any, Any]) -> Any:
    """
    Ejecuta una corrutina de forma segura dentro de un Celery task.
    Reutiliza el event loop existente si ya está corriendo, o crea uno nuevo.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        else:
            return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


@celery_app.task(name="workers.tasks.download_audio_task")  # type: ignore[untyped-decorator]
def download_audio_task(media_id: str, sender_phone: str) -> str:
    # 1. Validación de seguridad
    token = settings.WHATSAPP_API_TOKEN
    if not token:
        logger.error("Integración abortada: WHATSAPP_API_TOKEN no configurado.")
        return "ERROR_MISSING_TOKEN"

    headers = {"Authorization": f"Bearer {token}"}
    file_path = f"/tmp/caja_chica/{media_id}.ogg"

    try:
        # 2. Descarga del binario
        with httpx.Client() as client:
            meta_url = f"https://graph.facebook.com/v18.0/{media_id}"
            response = client.get(meta_url, headers=headers)
            response.raise_for_status()
            media_data = response.json()

            download_url = media_data.get("url")
            if not download_url:
                raise ValueError(f"No se encontró URL para media_id: {media_id}")

            # La URL de descarga suele ser firmada, no requiere token
            audio_response = client.get(download_url)
            audio_response.raise_for_status()

            os.makedirs("/tmp/caja_chica", exist_ok=True)
            with open(file_path, "wb") as f:
                f.write(audio_response.content)

        # 3. Procesamiento IA
        transcripcion = _run_async(transcribir_audio_whisper(file_path))

        if not transcripcion:
            _run_async(
                enviar_mensaje_whatsapp(
                    to_phone=sender_phone,
                    mensaje="No entendí el audio. Por favor, intentá de nuevo con más claridad.",
                )
            )
            return file_path

        transaction_data = _run_async(parse_financial_text(transcripcion))

        # 4. Persistencia e Integración de Respuesta
        if not transaction_data:
            _run_async(
                enviar_mensaje_whatsapp(
                    to_phone=sender_phone,
                    mensaje=(
                        "No encontré datos financieros en tu mensaje. Intentá de nuevo "
                        "indicando monto, categoría y si es gasto o ingreso."
                    ),
                )
            )
            return file_path

        # Caso de éxito
        _run_async(append_transaction_to_sheet(transaction_data))
        _run_async(
            enviar_mensaje_whatsapp(
                to_phone=sender_phone,
                mensaje=(
                    f"Transacción registrada: {transaction_data['categoria']} - "
                    f"₡{transaction_data['monto']}"
                ),
            )
        )

        return file_path

    except Exception as e:
        logger.error(f"Error en el pipeline: {e}")
        raise

    finally:
        # Limpieza del archivo temporal tras procesar
        if os.path.exists(file_path):
            os.remove(file_path)
