#!/usr/bin/env python3
import asyncio
import logging
import os
import tempfile

import httpx

from app.config import settings
from services.openai_service import (
    parse_financial_text,
    transcribir_audio_whisper,
)
from services.politica_service import (
    TEXTO_ACEPTACION_CONFIRMADA,
    TEXTO_POLITICA_PRIVACIDAD,
    TEXTO_RECHAZO_REGISTRADO,
    detectar_respuesta_consentimiento,
)
from services.sheets_service import (
    append_transaction_to_sheet,
    obtener_consentimiento,
    registrar_consentimiento,
    update_last_transaction_to_sheet,
)
from services.whatsapp_service import enviar_mensaje_whatsapp
from workers.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _procesar_pipeline(
    file_path: str | None, sender_phone: str, texto_entrante: str | None = None
) -> str:
    # 1. Obtenemos el texto: transcripción del audio o el texto directo del canal texto
    transcripcion: str | None
    if texto_entrante is not None:
        transcripcion = texto_entrante
    else:
        transcripcion = await transcribir_audio_whisper(file_path or "")

    if not transcripcion:
        await enviar_mensaje_whatsapp(
            to_phone=sender_phone,
            mensaje="No entendí el audio. Por favor, intentá de nuevo con más claridad.",
        )
        return file_path or ""

    # 2. GATE 6.5.1 — Consentimiento (ADR-0011, Ley 8968): sin aceptación no se procesa nada
    consentimiento = await obtener_consentimiento(sender_phone)
    consentido = consentimiento is not None and consentimiento.get("estado") == "aceptado"

    if not consentido:
        respuesta = detectar_respuesta_consentimiento(transcripcion)

        if respuesta == "aceptar":
            await registrar_consentimiento(sender_phone, "aceptado")
            await enviar_mensaje_whatsapp(
                to_phone=sender_phone,
                mensaje=TEXTO_ACEPTACION_CONFIRMADA,
            )
            return file_path or ""

        if respuesta == "rechazar":
            await registrar_consentimiento(sender_phone, "rechazado")
            await enviar_mensaje_whatsapp(
                to_phone=sender_phone,
                mensaje=TEXTO_RECHAZO_REGISTRADO,
            )
            return file_path or ""

        await enviar_mensaje_whatsapp(
            to_phone=sender_phone,
            mensaje=TEXTO_POLITICA_PRIVACIDAD,
        )
        return file_path or ""

    # 3. Flujo financiero normal (solo con consentimiento aceptado)
    transaction_data = await parse_financial_text(transcripcion)

    if not transaction_data:
        await enviar_mensaje_whatsapp(
            to_phone=sender_phone,
            mensaje=(
                "No encontré datos financieros en tu mensaje. Intentá de nuevo "
                "indicando monto, categoría y si es gasto o ingreso."
            ),
        )
        return file_path or ""

    accion = transaction_data.get("accion", "registrar")

    if accion == "aclaracion":
        await enviar_mensaje_whatsapp(
            to_phone=sender_phone,
            mensaje=(
                "Vi dos movimientos en tu mensaje y solo registro uno a la vez. "
                "¿Cuál querés que apunte?"
            ),
        )
        return file_path or ""

    if accion == "corregir":
        corregido = await update_last_transaction_to_sheet(transaction_data, sender_phone)
        if corregido:
            monto_aplicado, categoria_aplicada = corregido[0], corregido[1]
            await enviar_mensaje_whatsapp(
                to_phone=sender_phone,
                mensaje=(f"Corregido: {categoria_aplicada} - " f"₡{abs(monto_aplicado)}"),
            )
        else:
            await enviar_mensaje_whatsapp(
                to_phone=sender_phone,
                mensaje=(
                    "No encontré una transacción previa tuya para corregir. "
                    "Mandame primero el movimiento."
                ),
            )
        return file_path or ""

    if transaction_data.get("monto") is None:
        await enviar_mensaje_whatsapp(
            to_phone=sender_phone,
            mensaje=(
                "No encontré un monto en tu mensaje. Intentá de nuevo "
                "indicando monto, categoría y si es gasto o ingreso."
            ),
        )
        return file_path or ""

    await append_transaction_to_sheet(transaction_data, sender_phone)
    await enviar_mensaje_whatsapp(
        to_phone=sender_phone,
        mensaje=(
            f"Transacción registrada: {transaction_data['categoria']} - "
            f"₡{transaction_data['monto']}"
        ),
    )
    return file_path or ""


@celery_app.task(name="workers.tasks.download_audio_task")  # type: ignore[untyped-decorator]
def download_audio_task(media_id: str, sender_phone: str) -> str:
    token = settings.WHATSAPP_API_TOKEN
    if not token:
        logger.error("Integración abortada: WHATSAPP_API_TOKEN no configurado.")
        return "ERROR_MISSING_TOKEN"

    headers = {"Authorization": f"Bearer {token}"}
    temp_dir = os.path.join(tempfile.gettempdir(), "caja_chica")
    file_path = os.path.join(temp_dir, f"{media_id}.ogg")

    try:
        with httpx.Client() as client:
            meta_url = f"https://graph.facebook.com/v18.0/{media_id}"
            response = client.get(meta_url, headers=headers)
            response.raise_for_status()
            media_data = response.json()

            download_url = media_data.get("url")
            if not download_url:
                raise ValueError(f"No se encontró URL para media_id: {media_id}")

            audio_response = client.get(download_url, headers=headers)
            audio_response.raise_for_status()

            os.makedirs(temp_dir, exist_ok=True)
            with open(file_path, "wb") as f:
                f.write(audio_response.content)

        return asyncio.run(_procesar_pipeline(file_path, sender_phone))

    except Exception as e:
        logger.error(f"Error en el pipeline: {e}")
        raise

    finally:
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass


@celery_app.task(name="workers.tasks.procesar_mensaje_texto_task")  # type: ignore[untyped-decorator]
def procesar_mensaje_texto_task(sender_phone: str, texto: str) -> str:
    """
    Tarea de Celery para mensajes de TEXTO (canal nuevo de la Fase 6.5):
    recibe directamente el cuerpo del mensaje, sin descargar ni transcribir audio.
    """
    return asyncio.run(_procesar_pipeline(None, sender_phone, texto_entrante=texto))
