#!/usr/bin/env python3
import asyncio
import json
import logging
import os
import tempfile
import time
from datetime import datetime
from typing import Any, Literal

import httpx
import redis.asyncio as aioredis

from app.config import settings
from services.backup_service import crear_backup
from services.consulta_service import (
    calcular_consulta_categoria,
    calcular_consulta_comparacion,
    calcular_consulta_mayor,
    detectar_consulta,
    formatear_resultado_categoria,
    formatear_resultado_comparacion,
    formatear_resultado_mayor,
)
from services.duplicado_service import (
    TEXTO_CONFIRMACION_DUPLICADO,
    TEXTO_DUPLICADO_CONFIRMADO,
    TEXTO_DUPLICADO_DESCARTADO,
    TTL_DEDUPE_SEGUNDOS,
    clave_pendiente,
    clave_ultimo,
    detectar_confirmacion_duplicado,
    es_mismo_mismo_momento,
    es_mismo_reenvio,
    hash_transaccion,
)
from services.openai_service import (
    parse_financial_text,
    transcribir_audio_whisper,
)
from services.politica_service import (
    POLITICA_VERSION,
    TEXTO_ACEPTACION_CONFIRMADA,
    TEXTO_BAJA_CONFIRMADA,
    TEXTO_EXPORTACION_ENCABEZADO,
    TEXTO_EXPORTACION_VACIA,
    TEXTO_POLITICA_PRIVACIDAD,
    TEXTO_RE_CONSENTIMIENTO,
    TEXTO_RECHAZO_REGISTRADO,
    detectar_respuesta_consentimiento,
    detectar_respuesta_exportacion_baja,
    politica_aceptada_vigente,
)
from services.reporte_service import (
    ZONA_CR,
    calcular_resumen,
    detectar_solicitud_reporte,
    formatear_caption,
    formatear_texto,
    render_reporte_png,
    texto_sin_movimientos,
)
from services.sheets_service import (
    append_transaction_to_sheet,
    obtener_consentimiento,
    obtener_suscripcion,
    obtener_transacciones_cliente,
    registrar_consentimiento,
    update_last_transaction_to_sheet,
)
from services.suscripcion_service import (
    mensaje_suscripcion_no_activa,
    suscripcion_permite_uso,
)
from services.whatsapp_service import (
    dividir_mensaje_largo,
    enviar_imagen_whatsapp,
    enviar_mensaje_whatsapp,
)
from workers.celery_app import celery_app

logger = logging.getLogger(__name__)


# ==========================================
# 8.6.2 — IDEMPOTENCIA ANTI-DOBLE-TAP (helpers)
# ==========================================
# Regla de seguridad (rompe-si a): si Redis falla, NO se bloquea al usuario. El dedupe
# es una comodidad; perderlo es Acceptable, dejar de registrar transacciones NO.
async def _dedupe_redis() -> "aioredis.Redis":
    cliente = aioredis.from_url(  # type: ignore[no-untyped-call]
        settings.REDIS_URL, socket_connect_timeout=3
    )
    return cliente  # type: ignore[no-any-return]


def _media_id_de(file_path: str | None) -> str | None:
    """El media_id de Meta es el nombre del archivo temporal (`{media_id}.ogg`)."""
    if not file_path:
        return None
    return os.path.splitext(os.path.basename(file_path))[0] or None


async def _leer_ultimo_registro(sender_phone: str) -> dict[str, Any] | None:
    try:
        r = await _dedupe_redis()
        try:
            crudo = await r.get(clave_ultimo(sender_phone))
        finally:
            await r.aclose()
        if not crudo:
            return None
        if isinstance(crudo, bytes):
            crudo = crudo.decode("utf-8")
        return json.loads(crudo)  # type: ignore[no-any-return]
    except Exception as exc:  # noqa: BLE001 - degradar a "no duplicado"
        logger.warning("dedupe: no se pudo leer el último registro (%s)", exc)
        return None


async def _marcar_ultimo_registro(
    sender_phone: str, transaction_data: dict[str, Any], media_id: str | None
) -> None:
    try:
        r = await _dedupe_redis()
        try:
            await r.set(
                clave_ultimo(sender_phone),
                json.dumps(
                    {
                        "hash": hash_transaccion(transaction_data),
                        "media_id": media_id,
                        "ts": int(time.time()),
                    }
                ),
                ex=TTL_DEDUPE_SEGUNDOS,
            )
        finally:
            await r.aclose()
    except Exception as exc:  # noqa: BLE001 - degradar a "no duplicado"
        logger.warning("dedupe: no se pudo marcar el registro (%s)", exc)


async def _leer_pendiente(sender_phone: str) -> dict[str, Any] | None:
    try:
        r = await _dedupe_redis()
        try:
            crudo = await r.get(clave_pendiente(sender_phone))
        finally:
            await r.aclose()
        if not crudo:
            return None
        if isinstance(crudo, bytes):
            crudo = crudo.decode("utf-8")
        return json.loads(crudo)  # type: ignore[no-any-return]
    except Exception as exc:  # noqa: BLE001 - degradar a "sin pendiente"
        logger.warning("dedupe: no se pudo leer la pendiente (%s)", exc)
        return None


async def _guardar_pendiente(sender_phone: str, transaction_data: dict[str, Any]) -> None:
    try:
        r = await _dedupe_redis()
        try:
            await r.set(
                clave_pendiente(sender_phone),
                json.dumps(transaction_data),
                ex=TTL_DEDUPE_SEGUNDOS,
            )
        finally:
            await r.aclose()
    except Exception as exc:  # noqa: BLE001 - sin pendiente, el usuario reintenta
        logger.warning("dedupe: no se pudo guardar la pendiente (%s)", exc)


async def _borrar_pendiente(sender_phone: str) -> None:
    try:
        r = await _dedupe_redis()
        try:
            await r.delete(clave_pendiente(sender_phone))
        finally:
            await r.aclose()
    except Exception as exc:  # noqa: BLE001
        logger.warning("dedupe: no se pudo borrar la pendiente (%s)", exc)


async def _es_duplicado(
    transaction_data: dict[str, Any], sender_phone: str, media_id: str | None
) -> bool:
    """True si es el mismo movimiento ya registrado (reenvío o triple toque)."""
    previo = await _leer_ultimo_registro(sender_phone)
    if previo is None:
        return False
    if es_mismo_reenvio(media_id, previo.get("media_id")):
        return True
    return es_mismo_mismo_momento(
        previo.get("hash"), previo.get("ts"), hash_transaccion(transaction_data), int(time.time())
    )


def _formatear_movimiento(fila: list[str]) -> str:
    """Formatea una fila de la pestaña del cliente para el mensaje de exportación (6.5.3)."""
    fecha = fila[0] if len(fila) > 0 else ""
    monto = fila[1] if len(fila) > 1 else ""
    categoria = fila[2] if len(fila) > 2 else ""
    detalle = fila[3] if len(fila) > 3 else ""
    try:
        valor = int(monto)
        monto_formateado = f"-₡{abs(valor)}" if valor < 0 else f"₡{valor}"
    except (TypeError, ValueError):
        monto_formateado = str(monto)
    return f"{fecha} · {monto_formateado} · {categoria} · {detalle}"


async def _enviar_reporte_caja(sender_phone: str, periodo: Literal["semana", "mes"]) -> None:
    """
    Sprint de Valor Visible (S4/S4b) — Arma el reporte pedido por chat y lo envía
    como tarjeta PNG + caption; si la tarjeta no se puede generar o enviar, degrada
    al texto completo. La tarjeta es cosmética: jamás tira el pipeline.
    """
    filas = await obtener_transacciones_cliente(sender_phone)
    resumen = calcular_resumen(filas, periodo, datetime.now(ZONA_CR))

    if not resumen.tiene_datos:
        await enviar_mensaje_whatsapp(to_phone=sender_phone, mensaje=texto_sin_movimientos(periodo))
        return

    try:
        enviado = await enviar_imagen_whatsapp(
            to_phone=sender_phone,
            imagen=render_reporte_png(resumen),
            caption=formatear_caption(resumen),
        )
    except Exception as exc:  # noqa: BLE001 - degradar a texto, nunca perder el dato
        logger.error("reporte: falló la generación de la tarjeta (%s); plan B en texto.", exc)
        enviado = False

    if enviado:
        logger.info("reporte: tarjeta de %s enviada a %s.", periodo, sender_phone)
        return

    for bloque in dividir_mensaje_largo(formatear_texto(resumen)):
        await enviar_mensaje_whatsapp(to_phone=sender_phone, mensaje=bloque)


async def _enviar_consulta(
    sender_phone: str,
    consulta: Any,
) -> None:
    """
    Sprint de Valor Visible (6.6) — Responde consultas deterministas por chat.
    Siempre responde en texto (no tarjeta). Nunca tira el pipeline.
    """
    try:
        if hasattr(consulta, "categoria"):
            res_cat = await calcular_consulta_categoria(sender_phone, consulta)
            mensaje = formatear_resultado_categoria(res_cat)
        elif hasattr(consulta, "periodo") and getattr(consulta, "periodo", None) in (
            "semana",
            "mes",
            "semana_pasada",
            "mes_pasada",
            "todo",
        ):
            res_mayor = await calcular_consulta_mayor(sender_phone, consulta)
            mensaje = formatear_resultado_mayor(res_mayor)
        else:
            res_comp = await calcular_consulta_comparacion(sender_phone, consulta)
            mensaje = formatear_resultado_comparacion(res_comp)
    except Exception as exc:  # noqa: BLE001 - no perder el dato
        logger.error("consulta: falló el cálculo (%s).", exc)
        mensaje = "No pude calcular la consulta. Intentá de nuevo."

    await enviar_mensaje_whatsapp(to_phone=sender_phone, mensaje=mensaje)
    logger.info("consulta: respuesta enviada a %s.", sender_phone)


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

    # 2. GATE 6.5.1/6.5.6 — Consentimiento (ADR-0011, Ley 8968): sin aceptación de la
    #    versión vigente no se procesa nada
    consentimiento = await obtener_consentimiento(sender_phone)
    consentido = politica_aceptada_vigente(consentimiento)

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

        if consentimiento is not None and consentimiento.get("estado") == "aceptado":
            # 6.5.6 — Aceptó una versión anterior de la política: debe re-aceptar la vigente
            await enviar_mensaje_whatsapp(
                to_phone=sender_phone,
                mensaje=(
                    f"{TEXTO_RE_CONSENTIMIENTO.format(version=POLITICA_VERSION)}\n\n"
                    f"{TEXTO_POLITICA_PRIVACIDAD}"
                ),
            )
        else:
            await enviar_mensaje_whatsapp(
                to_phone=sender_phone,
                mensaje=TEXTO_POLITICA_PRIVACIDAD,
            )
        return file_path or ""

    # 3. Fase 6.5.3 — Derechos ARCO (Ley 8968): "exporta mis datos" / "darme de baja"
    respuesta_arco = detectar_respuesta_exportacion_baja(transcripcion)

    if respuesta_arco == "exportar":
        filas = await obtener_transacciones_cliente(sender_phone)
        if not filas:
            await enviar_mensaje_whatsapp(
                to_phone=sender_phone,
                mensaje=TEXTO_EXPORTACION_VACIA,
            )
            return file_path or ""

        movimientos = "\n".join(_formatear_movimiento(fila) for fila in filas)
        for bloque in dividir_mensaje_largo(f"{TEXTO_EXPORTACION_ENCABEZADO}\n{movimientos}"):
            await enviar_mensaje_whatsapp(to_phone=sender_phone, mensaje=bloque)
        return file_path or ""

    if respuesta_arco == "baja":
        await registrar_consentimiento(sender_phone, "cancelado")
        await enviar_mensaje_whatsapp(
            to_phone=sender_phone,
            mensaje=TEXTO_BAJA_CONFIRMADA,
        )
        return file_path or ""

    # 4. Fase 7.2.1 — Gate comercial (ADR-0013): el consentimiento legal ya está, pero
    #    además la suscripción debe tener acceso (activo/gratis/de_prueba). Va después
    #    de ARCO (exportar/darse de baja siempre funcionan: son derechos legales) y
    #    antes del dedupe y del parse: un teléfono vencido no consume OpenAI ni Sheets.
    suscripcion = await obtener_suscripcion(sender_phone)
    if not suscripcion_permite_uso(suscripcion):
        logger.info("suscripcion: acceso bloqueado (sin registro o estado sin acceso).")
        await enviar_mensaje_whatsapp(
            to_phone=sender_phone,
            mensaje=mensaje_suscripcion_no_activa(suscripcion),
        )
        return file_path or ""

    # 5. Sprint de Valor Visible — Reportes de caja (S4/S4b V1): pedido determinista
    #    (sin GPT) de "resumen de la semana" / "reporte del mes". Va después del gate
    #    comercial (el reporte es una función de valor, no un derecho legal como ARCO)
    #    y antes del dedupe: un pedido de reporte no es una transacción.
    periodo_reporte = detectar_solicitud_reporte(transcripcion)
    if periodo_reporte is not None:
        await _enviar_reporte_caja(sender_phone, periodo_reporte)
        return file_path or ""

    # 6. Sprint de Valor Visible — Consultas completas (6.6 V1): detección determinista
    #    de "cuanto gaste en X", "mayor gasto", "comparación". Va después del reporte
    #    y antes del dedupe/parse: una consulta no es una transacción.
    consulta = await detectar_consulta(sender_phone, transcripcion)
    if consulta is not None:
        await _enviar_consulta(sender_phone, consulta)
        return file_path or ""

    # 7. 8.6.2 — Confirmación de duplicado (va ANTES del parse: "sí" no trae monto)
    pendiente = await _leer_pendiente(sender_phone)
    if pendiente is not None:
        decision = detectar_confirmacion_duplicado(transcripcion)
        if decision == "otro":
            await _borrar_pendiente(sender_phone)
            await append_transaction_to_sheet(pendiente, sender_phone)
            await _marcar_ultimo_registro(sender_phone, pendiente, None)
            await enviar_mensaje_whatsapp(
                to_phone=sender_phone,
                mensaje=TEXTO_DUPLICADO_CONFIRMADO,
            )
            return file_path or ""
        if decision == "mismo":
            await _borrar_pendiente(sender_phone)
            await enviar_mensaje_whatsapp(
                to_phone=sender_phone,
                mensaje=TEXTO_DUPLICADO_DESCARTADO,
            )
            return file_path or ""

    # 7. Flujo financiero normal (solo con consentimiento aceptado y suscripción al día)
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

    if accion == "no_transaccion":
        # 8.6.3 — Presupuesto, tope, límite o consulta: no es dinero que entró o
        # salió, así que no se guarda nada (0 filas). Retorno temprano: sin Sheets
        # ni llamadas extra a OpenAI.
        logger.info("no_transaccion: 0 filas (presupuesto/consulta, sin guardar).")
        await enviar_mensaje_whatsapp(
            to_phone=sender_phone,
            mensaje=(
                "Eso todavía no lo llevo: presupuestos, topes y consultas no se "
                "guardan como gastos. Mandame el gasto real con monto y categoría "
                "y lo apunto."
            ),
        )
        return file_path or ""

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

    if not transaction_data.get("monto"):
        await enviar_mensaje_whatsapp(
            to_phone=sender_phone,
            mensaje=(
                "No encontré un monto en tu mensaje. Intentá de nuevo "
                "indicando monto, categoría y si es gasto o ingreso."
            ),
        )
        return file_path or ""

    if accion == "registrar":
        media_id = _media_id_de(file_path)

        if await _es_duplicado(transaction_data, sender_phone, media_id):
            await _guardar_pendiente(sender_phone, transaction_data)
            logger.info("dedupe: posible duplicado detectado, se pregunta antes de guardar.")
            await enviar_mensaje_whatsapp(
                to_phone=sender_phone,
                mensaje=TEXTO_CONFIRMACION_DUPLICADO,
            )
            return file_path or ""

        await append_transaction_to_sheet(transaction_data, sender_phone)
        await _marcar_ultimo_registro(sender_phone, transaction_data, media_id)
    else:
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


@celery_app.task(name="workers.tasks.crear_backup_task")  # type: ignore[untyped-decorator]
def crear_backup_task() -> str:
    """
    Fase 6.5.5 — Backup diario del sheet (ADR-0014). Programada por Celery beat
    (ver celery_app.py); genera la copia local completa del spreadsheet y purga los
    backups más viejos que la retención configurada (90 días por defecto).
    Devuelve la ruta del .zip generado o "ERROR" si falló.
    """
    ruta = asyncio.run(crear_backup())
    if ruta is None:
        logger.error("crear_backup_task: el backup del sheet falló.")
        return "ERROR"
    logger.info(f"crear_backup_task: backup generado en {ruta}.")
    return str(ruta)
