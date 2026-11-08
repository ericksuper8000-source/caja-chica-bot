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
from services.a08_service import (
    MAX_HISTORIAL,
    TEXTO_BORRADO_CANCELADO,
    TEXTO_BORRADO_DUDA,
    TEXTO_BORRADO_ERROR,
    TEXTO_BORRADO_NO_ENCONTRADO,
    TEXTO_BORRADO_OK,
    TEXTO_BORRADO_SIN_MOVIMIENTOS,
    TEXTO_DESHECHO_BORRADO,
    TEXTO_DESHECHO_CORRECCION,
    TEXTO_DESHECHO_CREACION,
    TEXTO_DESHECHO_ERROR,
    TEXTO_DESHECHO_REACTIVACION,
    TEXTO_NADA_QUE_DESHACER,
    TEXTO_REACTIVADO,
    TEXTO_REACTIVAR_ERROR,
    TEXTO_REACTIVAR_SIN_ANULADOS,
    TEXTO_SELECCION_INVALIDA,
    TTL_A08_SEGUNDOS,
    SolicitudBorrado,
    detectar_confirmacion_borrado,
    detectar_deshacer,
    detectar_historial,
    detectar_intencion_correccion,
    detectar_reactivar,
    detectar_solicitud_borrado,
    formatear_confirmacion_movimiento,
    formatear_historial,
    formatear_lista_borrado,
    formatear_prompt_borrado,
    indice_seleccionado,
    snapshot_movimiento,
)
from services.backup_service import crear_backup
from services.consulta_service import (
    ConsultaCategoria,
    ConsultaComparacion,
    ConsultaMayor,
    ConsultaPresupuestoRestante,
    calcular_consulta_categoria,
    calcular_consulta_comparacion,
    calcular_consulta_mayor,
    calcular_consulta_presupuesto_restante,
    detectar_consulta,
    formatear_resultado_categoria,
    formatear_resultado_comparacion,
    formatear_resultado_mayor,
    formatear_resultado_presupuesto_restante,
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
from services.export_service import (
    MIME_CSV,
    MIME_XLSX,
    TEXTO_EXPORTACION_DOCUMENTO,
    FormatoExport,
    generar_exportacion,
    nombre_exportacion,
)
from services.modelo_service import monto_con_signo
from services.monitoreo_service import (
    CLAVE_ESTADO_SALUD,
    TEXTO_SIN_ADMIN,
    TTL_ESTADO_SALUD,
    consultar_salud,
    decidir_accion,
    formatear_mensaje_monitoreo,
)
from services.numero_service import (
    TEXTO_CAMBIO_NUMERO_CONFIRMADO,
    TEXTO_CAMBIO_NUMERO_CONFLICTO,
    TEXTO_CAMBIO_NUMERO_ERROR,
    TEXTO_CAMBIO_NUMERO_INICIO,
    TEXTO_CAMBIO_NUMERO_INVALIDO,
    TEXTO_CAMBIO_NUMERO_SIN_ACCESO,
    crear_codigo_cambio,
    detectar_confirmacion_cambio_numero,
    detectar_inicio_cambio_numero,
    detectar_recuperacion_manual,
    verificar_codigo_cambio,
)
from services.onboarding_service import (
    PASO_CATEGORIAS,
    PASO_COMPLETADO,
    PASO_CONTEXTO,
    PASO_ESPACIO,
    PASO_PRIMER_MOVIMIENTO,
    PASO_TIPO_USO,
    TEXTO_ONBOARDING_CATEGORIAS_CONFIRMADO,
    TEXTO_ONBOARDING_CATEGORIAS_REINTENTO,
    TEXTO_ONBOARDING_CONTEXTO,
    TEXTO_ONBOARDING_CONTEXTO_CONFIRMADO,
    TEXTO_ONBOARDING_CONTEXTO_REINTENTO,
    TEXTO_ONBOARDING_ESPACIO,
    TEXTO_ONBOARDING_ESPACIO_REINTENTO,
    TEXTO_ONBOARDING_PRIMER_MOVIMIENTO,
    TEXTO_ONBOARDING_TIPO_USO,
    TEXTO_ONBOARDING_TIPO_USO_REINTENTO,
    detectar_contexto,
    detectar_nombre_espacio,
    detectar_saltar_primer_movimiento,
    detectar_tipo_uso,
    formatear_pregunta_categorias,
    guardar_paso,
    obtener_paso,
    parece_movimiento,
    procesar_categorias,
    texto_resumen_onboarding,
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
from services.preferencias_service import (
    TEXTO_ACTIVAR_CONFIRMADO,
    TEXTO_STOP_CONFIRMADO,
    detectar_activar_preferencias,
    detectar_stop_preferencias,
    en_horario_silencio,
    guardar_preferencia_automaticos,
    resumen_semanal_habilitado,
)
from services.presupuesto_service import (
    calcular_gastado_mes,
    detectar_eliminar_presupuesto,
    detectar_presupuesto,
    eliminar_presupuesto,
    establecer_presupuesto,
    verificar_y_alertar_presupuesto,
)
from services.rate_limit_service import permitir_mensaje
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
    MovimientoAnuladoError,
    actualizar_telefono_usuario,
    anular_movimiento,
    append_transaction_to_sheet,
    migrar_suscripcion,
    obtener_consentimiento,
    obtener_historial,
    obtener_movimientos_cliente,
    obtener_suscripcion,
    obtener_telefonos_con_acceso,
    obtener_transacciones_cliente,
    reactivar_movimiento,
    registrar_consentimiento,
    renombrar_pestana_cliente,
    restaurar_movimiento,
    revertir_movimiento,
    update_last_transaction_to_sheet,
    upsert_usuario,
)
from services.suscripcion_service import (
    mensaje_suscripcion_no_activa,
    suscripcion_permite_uso,
)
from services.whatsapp_service import (
    dividir_mensaje_largo,
    enviar_documento_whatsapp,
    enviar_imagen_whatsapp,
    enviar_mensaje_whatsapp,
)
from workers.celery_app import celery_app

logger = logging.getLogger(__name__)

TEXTO_ERROR_GUARDADO = (
    "No pude guardar el movimiento en tu hoja. No quedó registrado. "
    "Intentá de nuevo en unos segundos."
)
TEXTO_RATE_LIMIT = "Estás mandando muchos mensajes seguidos. Esperá un minuto y volvé a intentar."


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


async def _rate_limit_ok(sender_phone: str) -> bool:
    """Límite por teléfono (Seguridad #10): si Redis falla, no bloquea al usuario."""
    try:
        r = await _dedupe_redis()
        try:
            return await permitir_mensaje(r, sender_phone)
        finally:
            await r.aclose()
    except Exception as exc:  # noqa: BLE001
        logger.warning("rate_limit: no se pudo evaluar (%s); se permite", exc)
        return True


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


async def _guardar_transaccion_o_avisar(
    transaction_data: dict[str, Any], sender_phone: str
) -> dict[str, Any] | None:
    """
    Guarda el movimiento y devuelve el snapshot canónico (con ID) o None si falló.

    Los dobles de prueba antiguos que devuelven `True` se normalizan a `{}`: el flujo
    sigue funcionando, pero sin datos para A08 (no hay ID que deshacer).
    """
    guardado = await append_transaction_to_sheet(transaction_data, sender_phone)
    if not guardado:
        logger.error(
            "Sheets: no se pudo guardar la transacción de %s; no se confirma ni se marca dedupe.",
            sender_phone,
        )
        await enviar_mensaje_whatsapp(to_phone=sender_phone, mensaje=TEXTO_ERROR_GUARDADO)
        return None
    if isinstance(guardado, dict):
        return guardado
    return {}


# ==========================================
# A08 — BORRADO LÓGICO, DESHACER E HISTORIAL (D23/D24/D25)
# ==========================================
CLAVE_A08_ULTIMA = "a08:last:{}"
CLAVE_A08_BORRADO = "a08:borrado:{}"


async def _a08_leer(clave: str) -> dict[str, Any] | None:
    """Lee un estado A08 de Redis; ante cualquier fallo degrada a "sin estado"."""
    try:
        r = await _dedupe_redis()
        try:
            crudo = await r.get(clave)
        finally:
            await r.aclose()
        if not crudo:
            return None
        if isinstance(crudo, bytes):
            crudo = crudo.decode("utf-8")
        return json.loads(crudo)  # type: ignore[no-any-return]
    except Exception as exc:  # noqa: BLE001 - perder el estado A08 no bloquea el flujo
        logger.warning("a08: no se pudo leer %s (%s)", clave, exc)
        return None


async def _a08_guardar(clave: str, valor: dict[str, Any]) -> None:
    """Guarda un estado A08 con la ventana de 10 minutos (D23)."""
    try:
        r = await _dedupe_redis()
        try:
            await r.set(clave, json.dumps(valor, default=str), ex=TTL_A08_SEGUNDOS)
        finally:
            await r.aclose()
    except Exception as exc:  # noqa: BLE001
        logger.warning("a08: no se pudo guardar %s (%s)", clave, exc)


async def _a08_borrar(clave: str) -> None:
    try:
        r = await _dedupe_redis()
        try:
            await r.delete(clave)
        finally:
            await r.aclose()
    except Exception as exc:  # noqa: BLE001
        logger.warning("a08: no se pudo borrar %s (%s)", clave, exc)


async def _recordar_ultima_accion(
    sender_phone: str,
    accion: str,
    movimiento_id: str,
    antes: dict[str, Any] | None,
    despues: dict[str, Any] | None,
) -> None:
    """Snapshot mínimo de la última acción para el deshacer de un solo paso (D23)."""
    if not movimiento_id:
        return
    await _a08_guardar(
        CLAVE_A08_ULTIMA.format(sender_phone),
        {
            "accion": accion,
            "movimiento_id": movimiento_id,
            "antes": snapshot_movimiento(antes) if isinstance(antes, dict) else None,
            "despues": snapshot_movimiento(despues) if isinstance(despues, dict) else None,
            "ts": int(time.time()),
        },
    )


async def _a08_deshacer(sender_phone: str, ultima: dict[str, Any] | None) -> None:
    """Deshace la última acción registrada; si falla, conserva el estado para reintentar."""
    clave = CLAVE_A08_ULTIMA.format(sender_phone)
    if not ultima:
        await enviar_mensaje_whatsapp(to_phone=sender_phone, mensaje=TEXTO_NADA_QUE_DESHACER)
        return

    accion = str(ultima.get("accion") or "")
    movimiento_id = str(ultima.get("movimiento_id") or "")
    antes_crudo = ultima.get("antes")
    antes: dict[str, Any] = antes_crudo if isinstance(antes_crudo, dict) else {}

    resultado: dict[str, Any] | None = None
    mensaje = TEXTO_DESHECHO_ERROR
    if accion == "crear" and movimiento_id:
        resultado = await anular_movimiento(
            sender_phone, movimiento_id, "deshacer registro", accion="deshacer"
        )
        mensaje = TEXTO_DESHECHO_CREACION
    elif accion == "corregir" and movimiento_id and antes:
        resultado = await revertir_movimiento(sender_phone, movimiento_id, antes)
        mensaje = TEXTO_DESHECHO_CORRECCION
    elif accion in {"anular", "reactivar"} and movimiento_id:
        estado_previo = str(antes.get("estado") or "confirmado")
        resultado = await restaurar_movimiento(sender_phone, movimiento_id, estado_previo)
        mensaje = TEXTO_DESHECHO_BORRADO if accion == "anular" else TEXTO_DESHECHO_REACTIVACION

    if resultado is None:
        await enviar_mensaje_whatsapp(to_phone=sender_phone, mensaje=TEXTO_DESHECHO_ERROR)
        return

    # Deshacer no salta más de un paso: se consume para que no se pueda re-deshacer.
    await _a08_borrar(clave)
    await enviar_mensaje_whatsapp(to_phone=sender_phone, mensaje=mensaje)


async def _a08_reactivar(sender_phone: str) -> None:
    """Reactiva el último movimiento anulado (A08 §5.5, acción `reactivar`)."""
    movimientos = await obtener_movimientos_cliente(sender_phone, incluir_inactivos=True)
    anulados = [m for m in movimientos if str(m.get("estado")) == "anulado"]
    if not anulados:
        await enviar_mensaje_whatsapp(to_phone=sender_phone, mensaje=TEXTO_REACTIVAR_SIN_ANULADOS)
        return

    objetivo = anulados[-1]
    movimiento_id = str(objetivo.get("movimiento_id") or "")
    resultado = await reactivar_movimiento(sender_phone, movimiento_id)
    if resultado is None:
        await enviar_mensaje_whatsapp(to_phone=sender_phone, mensaje=TEXTO_REACTIVAR_ERROR)
        return

    await _recordar_ultima_accion(
        sender_phone,
        "reactivar",
        movimiento_id,
        resultado.get("antes"),
        resultado.get("despues"),
    )
    await enviar_mensaje_whatsapp(to_phone=sender_phone, mensaje=TEXTO_REACTIVADO)


async def _a08_pedir_confirmacion_borrado(sender_phone: str, movimiento: dict[str, Any]) -> None:
    """D24: muestra el movimiento completo y espera una frase explícita."""
    await _a08_guardar(
        CLAVE_A08_BORRADO.format(sender_phone),
        {
            "fase": "confirmacion",
            "candidato": snapshot_movimiento(movimiento),
            "candidatos": [],
            "ts": int(time.time()),
        },
    )
    await enviar_mensaje_whatsapp(
        to_phone=sender_phone, mensaje=formatear_prompt_borrado(movimiento)
    )


async def _a08_iniciar_borrado(sender_phone: str, solicitud: SolicitudBorrado) -> None:
    """Resuelve el movimiento pedido y arranca la confirmación explícita de D24."""
    movimientos = await obtener_movimientos_cliente(sender_phone, incluir_inactivos=False)
    if not movimientos:
        await enviar_mensaje_whatsapp(to_phone=sender_phone, mensaje=TEXTO_BORRADO_SIN_MOVIMIENTOS)
        return

    candidatos = movimientos
    if solicitud.tipo:
        candidatos = [
            m for m in candidatos if str(m.get("tipo_movimiento") or "").lower() == solicitud.tipo
        ]
    if solicitud.monto_centimos is not None:
        candidatos = [
            m for m in candidatos if int(m.get("monto_centimos") or 0) == solicitud.monto_centimos
        ]

    if not candidatos:
        await enviar_mensaje_whatsapp(to_phone=sender_phone, mensaje=TEXTO_BORRADO_NO_ENCONTRADO)
        return

    # "el primero", "el segundo": se respeta el ordinal explícito del usuario.
    if solicitud.ordinal is not None:
        if solicitud.ordinal >= len(candidatos):
            await enviar_mensaje_whatsapp(
                to_phone=sender_phone, mensaje=TEXTO_BORRADO_NO_ENCONTRADO
            )
            return
        await _a08_pedir_confirmacion_borrado(sender_phone, candidatos[solicitud.ordinal])
        return

    # Dos montos iguales: se muestran ambos con fecha/hora y se pide el número.
    if solicitud.monto_centimos is not None and len(candidatos) > 1:
        mostrados = candidatos[-5:]
        await _a08_guardar(
            CLAVE_A08_BORRADO.format(sender_phone),
            {
                "fase": "seleccion",
                "candidato": None,
                "candidatos": [snapshot_movimiento(m) for m in mostrados],
                "ts": int(time.time()),
            },
        )
        await enviar_mensaje_whatsapp(
            to_phone=sender_phone, mensaje=formatear_lista_borrado(mostrados)
        )
        return

    await _a08_pedir_confirmacion_borrado(sender_phone, candidatos[-1])


async def _a08_responder_borrado_pendiente(
    sender_phone: str, texto: str, pendiente: dict[str, Any]
) -> bool:
    """
    Responde al flujo de borrado ya iniciado. True si consumió el mensaje.

    Si la fase es de selección, acepta número/ordinal/monto. En confirmación, solo
    una frase explícita borra; cualquier otra cosa no borra (D24).
    """
    clave = CLAVE_A08_BORRADO.format(sender_phone)
    fase = str(pendiente.get("fase") or "confirmacion")

    if fase == "seleccion":
        candidatos = pendiente.get("candidatos")
        lista = candidatos if isinstance(candidatos, list) else []
        if detectar_confirmacion_borrado(texto) == "no":
            await _a08_borrar(clave)
            await enviar_mensaje_whatsapp(to_phone=sender_phone, mensaje=TEXTO_BORRADO_CANCELADO)
            return True
        indice = indice_seleccionado(texto, lista)
        if indice is not None:
            objetivo = lista[indice]
            await _a08_pedir_confirmacion_borrado(sender_phone, objetivo)
            return True
        if parece_movimiento(texto):
            # El usuario siguió con otra cosa: no se borra y se procesa normal.
            await _a08_borrar(clave)
            return False
        await enviar_mensaje_whatsapp(to_phone=sender_phone, mensaje=TEXTO_SELECCION_INVALIDA)
        return True

    decision = detectar_confirmacion_borrado(texto)
    if decision == "no":
        await _a08_borrar(clave)
        await enviar_mensaje_whatsapp(to_phone=sender_phone, mensaje=TEXTO_BORRADO_CANCELADO)
        return True
    if decision != "si":
        if parece_movimiento(texto):
            await _a08_borrar(clave)
            return False
        await enviar_mensaje_whatsapp(to_phone=sender_phone, mensaje=TEXTO_BORRADO_DUDA)
        return True

    candidato = pendiente.get("candidato")
    movimiento = candidato if isinstance(candidato, dict) else {}
    movimiento_id = str(movimiento.get("movimiento_id") or "")
    resultado = await anular_movimiento(sender_phone, movimiento_id, "solicitud del usuario")
    await _a08_borrar(clave)
    if resultado is None:
        await enviar_mensaje_whatsapp(to_phone=sender_phone, mensaje=TEXTO_BORRADO_ERROR)
        return True

    await _recordar_ultima_accion(
        sender_phone,
        "anular",
        movimiento_id,
        resultado.get("antes"),
        resultado.get("despues"),
    )
    await enviar_mensaje_whatsapp(to_phone=sender_phone, mensaje=TEXTO_BORRADO_OK)
    return True


async def _procesar_a08(sender_phone: str, texto: str) -> bool:
    """
    Puerta A08 antes del gate comercial (D25). Devuelve True si el mensaje se manejó.

    Orden: deshacer explícito (no cierra la ventana) → borrado pendiente → historial →
    reactivar → nuevo borrado. Cualquier otro mensaje cierra la ventana de D23.
    """
    clave_ultima = CLAVE_A08_ULTIMA.format(sender_phone)
    clave_borrado = CLAVE_A08_BORRADO.format(sender_phone)
    ultima = await _a08_leer(clave_ultima)
    pendiente = await _a08_leer(clave_borrado)

    if detectar_deshacer(texto):
        if pendiente is not None:
            await _a08_borrar(clave_borrado)
        # El usuario cambió de tema: una pregunta de duplicado pendiente ya no aplica.
        await _borrar_pendiente(sender_phone)
        await _a08_deshacer(sender_phone, ultima)
        return True

    # D23: el siguiente mensaje procesado cierra la ventana, aunque no sea de A08.
    if ultima is not None:
        await _a08_borrar(clave_ultima)

    if pendiente is not None:
        if await _a08_responder_borrado_pendiente(sender_phone, texto, pendiente):
            await _borrar_pendiente(sender_phone)
            return True
        # Si no consumió el mensaje, ya se canceló el borrado pendiente.

    if detectar_historial(texto):
        await _borrar_pendiente(sender_phone)
        entradas = await obtener_historial(sender_phone, limite=MAX_HISTORIAL)
        for bloque in dividir_mensaje_largo(formatear_historial(entradas, sender_phone)):
            await enviar_mensaje_whatsapp(to_phone=sender_phone, mensaje=bloque)
        return True

    if detectar_reactivar(texto):
        await _borrar_pendiente(sender_phone)
        await _a08_reactivar(sender_phone)
        return True

    solicitud = detectar_solicitud_borrado(texto)
    if solicitud is not None:
        await _borrar_pendiente(sender_phone)
        await _a08_iniciar_borrado(sender_phone, solicitud)
        return True

    return False


async def _evaluar_alerta_presupuesto(
    transaction_data: dict[str, Any], sender_phone: str
) -> str | None:
    """
    Paso 4 (P1-1): evalúa la alerta 80/100% del presupuesto tras guardar un gasto.
    Devuelve el mensaje listo para enviar o None. Nunca rompe el flujo financiero.
    """
    if str(transaction_data.get("tipo_movimiento") or "").lower() != "gasto":
        return None
    categoria = str(transaction_data.get("categoria") or "").strip()
    if not categoria:
        return None
    try:
        filas = await obtener_transacciones_cliente(sender_phone)
        total_mes = calcular_gastado_mes(filas, categoria)
        return await verificar_y_alertar_presupuesto(
            sender_phone,
            categoria,
            int(transaction_data.get("monto") or 0),
            total_mes,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("presupuesto: no se pudo evaluar la alerta (%s)", exc)
        return None


def _formatear_movimiento(fila: list[str]) -> str:
    """Formatea una fila de la pestaña del cliente para el mensaje de exportación (6.5.3)."""
    fecha = fila[0] if len(fila) > 0 else ""
    valor = monto_con_signo(fila)
    monto_formateado = f"-₡{abs(valor)}" if valor < 0 else f"₡{valor}"
    categoria = fila[2] if len(fila) > 2 else ""
    detalle = fila[3] if len(fila) > 3 else ""
    estado = str(fila[9]) if len(fila) > 9 else ""
    sufijo = f" · {estado}" if estado in {"anulado", "pendiente"} else ""
    return f"{fecha} · {monto_formateado} · {categoria} · {detalle}{sufijo}"


# ==========================================
# Sprint de Valor Visible — Reportes (S4/S4b, V1)
# ==========================================
async def _enviar_reporte_caja(sender_phone: str, periodo: Literal["semana", "mes"]) -> None:
    filas = await obtener_transacciones_cliente(sender_phone)
    if not filas:
        await enviar_mensaje_whatsapp(
            to_phone=sender_phone,
            mensaje=texto_sin_movimientos(periodo),
        )
        return

    desde = datetime.now(ZONA_CR)
    resumen = calcular_resumen(filas, periodo, desde)
    png = render_reporte_png(resumen)
    caption = formatear_caption(resumen)
    enviada = await enviar_imagen_whatsapp(to_phone=sender_phone, imagen=png, caption=caption)
    if not enviada:
        bloques = dividir_mensaje_largo(formatear_texto(resumen))
        for bloque in bloques:
            await enviar_mensaje_whatsapp(to_phone=sender_phone, mensaje=bloque)


# ==========================================
# Consultas de caja (Step 2)
# ==========================================
async def _enviar_consulta(
    sender_phone: str,
    consulta: ConsultaCategoria | ConsultaMayor | ConsultaComparacion | ConsultaPresupuestoRestante,
) -> None:
    mensaje: str
    if isinstance(consulta, ConsultaCategoria):
        res_cat = await calcular_consulta_categoria(sender_phone, consulta)
        mensaje = formatear_resultado_categoria(res_cat)
    elif isinstance(consulta, ConsultaMayor):
        res_mayor = await calcular_consulta_mayor(sender_phone, consulta)
        mensaje = formatear_resultado_mayor(res_mayor)
    elif isinstance(consulta, ConsultaComparacion):
        res_comp = await calcular_consulta_comparacion(sender_phone, consulta)
        mensaje = formatear_resultado_comparacion(res_comp)
    elif isinstance(consulta, ConsultaPresupuestoRestante):
        res_presup = await calcular_consulta_presupuesto_restante(sender_phone, consulta)
        mensaje = formatear_resultado_presupuesto_restante(res_presup)
    else:
        return

    bloques = dividir_mensaje_largo(mensaje)
    for bloque in bloques:
        await enviar_mensaje_whatsapp(to_phone=sender_phone, mensaje=bloque)


# ==========================================
# Presupuestos (Step 2)
# ==========================================
async def _procesar_presupuesto(sender_phone: str, transcripcion: str) -> bool:
    presupuesto = detectar_presupuesto(transcripcion)
    if presupuesto:
        cat_nueva, limite = presupuesto
        guardado = await establecer_presupuesto(sender_phone, cat_nueva, limite)
        mensaje = (
            f"Presupuesto {cat_nueva}: ₡{limite:,}/mes guardado."
            if guardado
            else "No pude guardar el presupuesto ahora. Intentá de nuevo en unos segundos."
        )
        await enviar_mensaje_whatsapp(to_phone=sender_phone, mensaje=mensaje)
        return True

    cat_eliminar = detectar_eliminar_presupuesto(transcripcion)
    if cat_eliminar:
        eliminado = await eliminar_presupuesto(sender_phone, cat_eliminar)
        mensaje = (
            f"Presupuesto eliminado: {cat_eliminar}."
            if eliminado
            else f"No encontré un presupuesto de {cat_eliminar} para borrar."
        )
        await enviar_mensaje_whatsapp(to_phone=sender_phone, mensaje=mensaje)
        return True

    # Si claramente quiso fijar un presupuesto pero no se pudo leer el monto
    # (típico de transcripciones), no caemos al mensaje genérico de "no es un gasto".
    if " ".join(transcripcion.lower().split()).startswith("presupuesto"):
        logger.info("presupuesto: intención detectada pero monto ilegible.")
        await enviar_mensaje_whatsapp(
            to_phone=sender_phone,
            mensaje=(
                "Entendí que querés fijar un presupuesto, pero no pude leer el monto. "
                "Mandalo así: presupuesto transporte 20000."
            ),
        )
        return True

    return False


# ==========================================
# Fase 6.1 - Onboarding guiado (ADR-0019 / especificacion A04-A05)
# ==========================================
async def _iniciar_onboarding(sender_phone: str) -> None:
    # Fase 6.1 - Onboarding guiado: tras aceptar la politica arranca el alta guiada.
    await guardar_paso(sender_phone, PASO_TIPO_USO)
    await enviar_mensaje_whatsapp(to_phone=sender_phone, mensaje=TEXTO_ONBOARDING_TIPO_USO)


async def _responder_paso_onboarding(sender_phone: str, texto: str) -> str | None:
    # Fase 6.1 - Onboarding guiado: responde al paso actual del alta. None si no aplica.
    estado = await obtener_paso(sender_phone)
    paso = estado.get("paso") if estado else None
    if paso == PASO_TIPO_USO:
        tipo_uso = detectar_tipo_uso(texto)
        if tipo_uso is None:
            if detectar_respuesta_exportacion_baja(texto) is not None:
                return None
            if parece_movimiento(texto):
                return None
            return TEXTO_ONBOARDING_TIPO_USO_REINTENTO
        await guardar_paso(sender_phone, PASO_ESPACIO, tipo_uso=tipo_uso)
        return TEXTO_ONBOARDING_ESPACIO

    if paso == PASO_ESPACIO:
        if detectar_respuesta_exportacion_baja(texto) is not None:
            return None
        if parece_movimiento(texto):
            return None
        nombre = detectar_nombre_espacio(texto)
        if nombre is None:
            return TEXTO_ONBOARDING_ESPACIO_REINTENTO
        datos_previos = {k: v for k, v in (estado or {}).items() if k != "paso"}
        await guardar_paso(sender_phone, PASO_CONTEXTO, espacio=nombre, **datos_previos)
        return TEXTO_ONBOARDING_CONTEXTO.format(espacio=nombre)

    if paso == PASO_CONTEXTO:
        if detectar_respuesta_exportacion_baja(texto) is not None:
            return None
        if parece_movimiento(texto):
            return None
        contexto = detectar_contexto(texto)
        if contexto is None:
            return TEXTO_ONBOARDING_CONTEXTO_REINTENTO
        datos_previos = {k: v for k, v in (estado or {}).items() if k != "paso"}
        await guardar_paso(sender_phone, PASO_CATEGORIAS, **contexto, **datos_previos)
        tipo_uso = str((estado or {}).get("tipo_uso", "personal"))
        return (
            TEXTO_ONBOARDING_CONTEXTO_CONFIRMADO.format(**contexto)
            + "\n\n"
            + formatear_pregunta_categorias(tipo_uso)
        )

    if paso == PASO_CATEGORIAS:
        if detectar_respuesta_exportacion_baja(texto) is not None:
            return None
        if parece_movimiento(texto):
            return None
        tipo_uso = str((estado or {}).get("tipo_uso", "personal"))
        categorias = procesar_categorias(texto, tipo_uso)
        if categorias is None:
            return TEXTO_ONBOARDING_CATEGORIAS_REINTENTO
        datos_previos = {k: v for k, v in (estado or {}).items() if k != "paso"}
        texto_categorias = ", ".join(categorias)
        await guardar_paso(
            sender_phone, PASO_PRIMER_MOVIMIENTO, categorias=texto_categorias, **datos_previos
        )
        return (
            TEXTO_ONBOARDING_CATEGORIAS_CONFIRMADO.format(categorias=texto_categorias)
            + "\n\n"
            + TEXTO_ONBOARDING_PRIMER_MOVIMIENTO
        )

    if paso == PASO_PRIMER_MOVIMIENTO:
        if detectar_respuesta_exportacion_baja(texto) is not None:
            return None
        if not detectar_saltar_primer_movimiento(texto):
            return None
        datos_previos = {k: v for k, v in (estado or {}).items() if k != "paso"}
        await guardar_paso(sender_phone, PASO_COMPLETADO, **datos_previos)
        await _persistir_usuario(sender_phone, estado or {})
        return texto_resumen_onboarding(estado or {})

    return None


async def _persistir_usuario(sender_phone: str, estado: dict[str, Any]) -> None:
    # Fase 6.1 - persistencia real del perfil al cerrar el alta (pestaña Usuarios).
    await upsert_usuario(
        {
            "telefono": sender_phone,
            "tipo_uso": str(estado.get("tipo_uso", "")),
            "espacio": str(estado.get("espacio", "")),
            "pais": str(estado.get("pais", "Costa Rica")),
            "moneda": str(estado.get("moneda", "CRC")),
            "zona": str(estado.get("zona", "America/Costa_Rica")),
            "categorias": str(estado.get("categorias", "")),
        }
    )


async def _finalizar_onboarding_si_corresponde(
    sender_phone: str, transaction_data: dict[str, Any]
) -> str | None:
    estado = await obtener_paso(sender_phone)
    if not estado or estado.get("paso") != PASO_PRIMER_MOVIMIENTO:
        return None
    datos_previos = {k: v for k, v in estado.items() if k != "paso"}
    await guardar_paso(sender_phone, PASO_COMPLETADO, **datos_previos)
    await _persistir_usuario(sender_phone, estado)
    return texto_resumen_onboarding(estado, transaction_data)


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

    # Seguridad #10 — límite por teléfono antes de gastar OpenAI/Sheets.
    if not await _rate_limit_ok(sender_phone):
        await enviar_mensaje_whatsapp(to_phone=sender_phone, mensaje=TEXTO_RATE_LIMIT)
        return file_path or ""

    # D23 — el siguiente mensaje procesado cierra la ventana de deshacer, incluso si
    # es administrativo (consentimiento, STOP, cambio de número). El propio "deshacé"
    # no la cierra: A08 lo consume después para poder revertir la última acción.
    if not detectar_deshacer(transcripcion):
        await _a08_borrar(CLAVE_A08_ULTIMA.format(sender_phone))

    # 1.5 Fase 6.1 - Cambio de número (spec 5.6): la confirmación llega desde el número
    #     nuevo, que todavía no tiene consentimiento, por eso va antes del gate legal.
    #     Orden endurecido (deuda #17): primero el chequeo de pestaña (si el número
    #     nuevo ya tiene historial se aborta sin tocar nada), luego la migración de
    #     consentimiento/perfil, y por último el control comercial (Suscripciones).
    confirmacion_cambio = detectar_confirmacion_cambio_numero(transcripcion)
    if confirmacion_cambio is not None:
        telefono_anterior, codigo_cambio = confirmacion_cambio
        if telefono_anterior != sender_phone and await verificar_codigo_cambio(
            telefono_anterior, codigo_cambio
        ):
            pestana_ok = await renombrar_pestana_cliente(telefono_anterior, sender_phone)
            if not pestana_ok:
                logger.warning(
                    "cambio_numero: conflicto de pestaña %s -> %s (historial existente o error)",
                    telefono_anterior,
                    sender_phone,
                )
                await enviar_mensaje_whatsapp(
                    to_phone=sender_phone, mensaje=TEXTO_CAMBIO_NUMERO_CONFLICTO
                )
                return file_path or ""
            consentimiento_previo = await obtener_consentimiento(telefono_anterior)
            if consentimiento_previo and consentimiento_previo.get("estado"):
                await registrar_consentimiento(sender_phone, str(consentimiento_previo["estado"]))
            await actualizar_telefono_usuario(telefono_anterior, sender_phone)
            estado_suscripcion = await migrar_suscripcion(telefono_anterior, sender_phone)
            if estado_suscripcion is None:
                logger.error(
                    "cambio_numero: fallo al migrar Suscripciones %s -> %s; revisar a mano",
                    telefono_anterior,
                    sender_phone,
                )
            elif estado_suscripcion == "sin_suscripcion":
                logger.info(
                    "cambio_numero: el número viejo %s no tenía suscripción; nada que migrar",
                    telefono_anterior,
                )
            elif estado_suscripcion == "nuevo_ya_tiene":
                logger.info(
                    "cambio_numero: el número nuevo %s ya tenía suscripción; no se duplicó",
                    sender_phone,
                )
            elif estado_suscripcion == "reactivada":
                logger.info(
                    "cambio_numero: fila cancelada del número nuevo %s reactivada desde %s",
                    sender_phone,
                    telefono_anterior,
                )
            await enviar_mensaje_whatsapp(
                to_phone=sender_phone, mensaje=TEXTO_CAMBIO_NUMERO_CONFIRMADO
            )
        else:
            await enviar_mensaje_whatsapp(
                to_phone=sender_phone, mensaje=TEXTO_CAMBIO_NUMERO_INVALIDO
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
            await _iniciar_onboarding(sender_phone)
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

    # 2.2 Paso 4 Sprint — preferencias de mensajes automáticos (STOP/activar).
    #     Va antes de onboarding/ARCO para que el cliente pueda pausar los
    #     automáticos en cualquier momento (los datos no se tocan).
    if detectar_stop_preferencias(transcripcion):
        await guardar_preferencia_automaticos(sender_phone, False)
        await enviar_mensaje_whatsapp(to_phone=sender_phone, mensaje=TEXTO_STOP_CONFIRMADO)
        return file_path or ""

    if detectar_activar_preferencias(transcripcion):
        await guardar_preferencia_automaticos(sender_phone, True)
        await enviar_mensaje_whatsapp(to_phone=sender_phone, mensaje=TEXTO_ACTIVAR_CONFIRMADO)
        return file_path or ""

    # 2.5 Fase 6.1 - Cambio de número (spec 5.6): inicio desde el número actual
    if detectar_recuperacion_manual(transcripcion):
        logger.warning("cambio_numero: recuperación manual solicitada por %s", sender_phone)
        await enviar_mensaje_whatsapp(to_phone=sender_phone, mensaje=TEXTO_CAMBIO_NUMERO_SIN_ACCESO)
        return file_path or ""

    if detectar_inicio_cambio_numero(transcripcion):
        codigo_nuevo = await crear_codigo_cambio(sender_phone)
        mensaje_cambio = (
            TEXTO_CAMBIO_NUMERO_INICIO.format(telefono=sender_phone, codigo=codigo_nuevo)
            if codigo_nuevo
            else TEXTO_CAMBIO_NUMERO_ERROR
        )
        await enviar_mensaje_whatsapp(to_phone=sender_phone, mensaje=mensaje_cambio)
        return file_path or ""

    # 2.7 A08 — Corrección, borrado, deshacer e historial (D23/D24/D25). Va antes
    #     del gate comercial para que corregir/borrar/deshacer funcione con plan
    #     vencido; el alta de movimientos nuevos sigue bloqueada en el gate.
    if await _procesar_a08(sender_phone, transcripcion):
        return file_path or ""

    # 3. Fase 6.5.3 — Derechos ARCO (Ley 8968): "exporta mis datos" / "darme de baja"
    # Fase 6.1 - Onboarding guiado: respuesta al paso actual del alta
    mensaje_onboarding = await _responder_paso_onboarding(sender_phone, transcripcion)
    if mensaje_onboarding is not None:
        await enviar_mensaje_whatsapp(to_phone=sender_phone, mensaje=mensaje_onboarding)
        return file_path or ""

    respuesta_arco = detectar_respuesta_exportacion_baja(transcripcion)

    if respuesta_arco == "exportar":
        # ARCO: el usuario tiene derecho a TODOS sus datos, incluidos los anulados.
        filas = await obtener_transacciones_cliente(sender_phone, incluir_inactivos=True)
        if not filas:
            await enviar_mensaje_whatsapp(
                to_phone=sender_phone,
                mensaje=TEXTO_EXPORTACION_VACIA,
            )
            return file_path or ""

        formatos: tuple[tuple[FormatoExport, str], ...] = (
            ("csv", MIME_CSV),
            ("xlsx", MIME_XLSX),
        )
        enviados = 0
        for formato, mime_type in formatos:
            try:
                contenido = generar_exportacion(filas, formato)
                nombre = nombre_exportacion(filas, formato)
            except Exception as error:  # noqa: BLE001 - se intenta el otro formato
                logger.error("export: no se pudo generar %s (%s)", formato, error)
                continue
            if await enviar_documento_whatsapp(
                to_phone=sender_phone,
                contenido=contenido,
                nombre=nombre,
                mime_type=mime_type,
                caption=TEXTO_EXPORTACION_DOCUMENTO,
            ):
                enviados += 1

        if enviados:
            return file_path or ""

        # Plan B: si Meta rechaza los documentos, se manda el texto de siempre.
        movimientos = "\n".join(_formatear_movimiento(fila) for fila in filas)
        texto_completo = f"{TEXTO_EXPORTACION_ENCABEZADO}\n{movimientos}"
        bloques = dividir_mensaje_largo(texto_completo)
        for bloque in bloques:
            await enviar_mensaje_whatsapp(to_phone=sender_phone, mensaje=bloque)
        return file_path or ""

    if respuesta_arco == "baja":
        await registrar_consentimiento(sender_phone, "cancelado")
        await enviar_mensaje_whatsapp(
            to_phone=sender_phone,
            mensaje=TEXTO_BAJA_CONFIRMADA,
        )
        return file_path or ""

    # 3.5 Gate comercial (Fase 7.2.1, ADR-0013): suscripción vigente. D25 permite
    #     corregir/borrar/deshacer con plan vencido; el alta nueva sigue bloqueada.
    suscripcion = await obtener_suscripcion(sender_phone)
    plan_permite = suscripcion_permite_uso(suscripcion)
    if not plan_permite and not detectar_intencion_correccion(transcripcion):
        await enviar_mensaje_whatsapp(
            to_phone=sender_phone,
            mensaje=mensaje_suscripcion_no_activa(suscripcion),
        )
        return file_path or ""

    # 3.6 Sprint Valor Visible — Reportes de caja (S4/S4b, V1)
    periodo_reporte = detectar_solicitud_reporte(transcripcion)
    if periodo_reporte:
        await _enviar_reporte_caja(sender_phone, periodo_reporte)
        return file_path or ""

    # 3.7 Consultas de caja (cuánto gasté, comparaciones, presupuesto restante)
    consulta = await detectar_consulta(sender_phone, transcripcion)
    if consulta:
        await _enviar_consulta(sender_phone, consulta)
        return file_path or ""

    # 3.8 Presupuestos: "presupuesto <categoría> <monto>" / "borrar presupuesto <categoría>"
    if await _procesar_presupuesto(sender_phone, transcripcion):
        return file_path or ""

    # 4. 8.6.2 — Confirmación de duplicado (va ANTES del parse: "sí" no trae monto)
    pendiente = await _leer_pendiente(sender_phone)
    if pendiente is not None:
        decision = detectar_confirmacion_duplicado(transcripcion)
        if decision == "otro":
            guardado_dup = await _guardar_transaccion_o_avisar(pendiente, sender_phone)
            if guardado_dup is None:
                return file_path or ""
            await _borrar_pendiente(sender_phone)
            await _marcar_ultimo_registro(sender_phone, pendiente, None)
            if guardado_dup.get("movimiento_id"):
                await _recordar_ultima_accion(
                    sender_phone,
                    "crear",
                    str(guardado_dup["movimiento_id"]),
                    None,
                    guardado_dup,
                )
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

    # 5. Flujo financiero normal (solo con consentimiento aceptado)
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

    # D25 — el bypass del gate solo sirve si el parser confirma una corrección. Un
    # falso positivo de la heurística no puede crear un movimiento con plan vencido.
    if not plan_permite and accion != "corregir":
        await enviar_mensaje_whatsapp(
            to_phone=sender_phone,
            mensaje=mensaje_suscripcion_no_activa(suscripcion),
        )
        return file_path or ""

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
        try:
            corregido: Any = await update_last_transaction_to_sheet(transaction_data, sender_phone)
        except MovimientoAnuladoError:
            await enviar_mensaje_whatsapp(
                to_phone=sender_phone,
                mensaje=(
                    "Ese movimiento está anulado. Para corregirlo, primero "
                    'decime "reactivá el último".'
                ),
            )
            return file_path or ""

        if corregido:
            despues = corregido.get("despues") if isinstance(corregido, dict) else None
            if isinstance(corregido, dict) and isinstance(despues, dict):
                await _recordar_ultima_accion(
                    sender_phone,
                    "corregir",
                    str(corregido.get("movimiento_id") or ""),
                    corregido.get("antes"),
                    despues,
                )
                await enviar_mensaje_whatsapp(
                    to_phone=sender_phone,
                    mensaje=formatear_confirmacion_movimiento(despues, verbo="Corregí"),
                )
            else:  # compatibilidad con dobles de prueba que aún devuelven la fila
                monto_aplicado = (
                    corregido.get("monto", 0) if isinstance(corregido, dict) else corregido[0]
                )
                categoria_aplicada = (
                    corregido.get("categoria", "") if isinstance(corregido, dict) else corregido[1]
                )
                await enviar_mensaje_whatsapp(
                    to_phone=sender_phone,
                    mensaje=f"Corregido: {categoria_aplicada} - ₡{abs(monto_aplicado)}",
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

    guardado: dict[str, Any] | None
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

        guardado = await _guardar_transaccion_o_avisar(transaction_data, sender_phone)
        if guardado is None:
            return file_path or ""
        await _marcar_ultimo_registro(sender_phone, transaction_data, media_id)
    else:
        guardado = await _guardar_transaccion_o_avisar(transaction_data, sender_phone)
        if guardado is None:
            return file_path or ""

    if guardado.get("movimiento_id"):
        await _recordar_ultima_accion(
            sender_phone,
            "crear",
            str(guardado["movimiento_id"]),
            None,
            guardado,
        )

    alerta_presupuesto = await _evaluar_alerta_presupuesto(transaction_data, sender_phone)

    resumen = await _finalizar_onboarding_si_corresponde(sender_phone, transaction_data)
    if resumen is not None:
        await enviar_mensaje_whatsapp(to_phone=sender_phone, mensaje=resumen)
        if alerta_presupuesto:
            await enviar_mensaje_whatsapp(to_phone=sender_phone, mensaje=alerta_presupuesto)
        return file_path or ""

    if guardado.get("movimiento_id"):
        mensaje_registro = formatear_confirmacion_movimiento(guardado)
    else:
        mensaje_registro = (
            f"Transacción registrada: {transaction_data['categoria']} - "
            f"₡{transaction_data['monto']}"
        )
    await enviar_mensaje_whatsapp(to_phone=sender_phone, mensaje=mensaje_registro)
    if alerta_presupuesto:
        await enviar_mensaje_whatsapp(to_phone=sender_phone, mensaje=alerta_presupuesto)
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


# ==========================================
# Paso 4 Sprint — Resumen semanal automático (notificaciones)
# ==========================================
async def _enviar_resumenes_semanales() -> dict[str, int]:
    """
    Envía el resumen de la última semana a cada cliente con suscripción vigente y
    preferencia activa. Respeta el horario de silencio (22:00–06:59 CR) y no envía
    si el cliente no tiene movimientos en la ventana. Un fallo no frena al resto.
    """
    resultado = {"enviados": 0, "omitidos": 0, "errores": 0}
    if en_horario_silencio():
        logger.info("resumen semanal: omitido por horario de silencio (22:00–07:00 CR).")
        return resultado

    telefonos = await obtener_telefonos_con_acceso()
    ahora = datetime.now(ZONA_CR)
    for telefono in telefonos:
        try:
            if not await resumen_semanal_habilitado(telefono):
                resultado["omitidos"] += 1
                continue
            filas = await obtener_transacciones_cliente(telefono)
            if not filas:
                resultado["omitidos"] += 1
                continue
            resumen = calcular_resumen(filas, "semana", ahora)
            for bloque in dividir_mensaje_largo(formatear_texto(resumen)):
                await enviar_mensaje_whatsapp(to_phone=telefono, mensaje=bloque)
            resultado["enviados"] += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("resumen semanal: error con %s (%s)", telefono, exc)
            resultado["errores"] += 1
    logger.info(
        "resumen semanal: enviados=%d omitidos=%d errores=%d",
        resultado["enviados"],
        resultado["omitidos"],
        resultado["errores"],
    )
    return resultado


@celery_app.task(name="workers.tasks.enviar_resumenes_semanales_task")  # type: ignore[untyped-decorator]
def enviar_resumenes_semanales_task() -> str:
    """
    Paso 4 Sprint — resumen semanal automático programado por Celery beat
    (lunes 08:00 CR por defecto, configurable). Usa el mismo formateador del
    reporte por chat; si WhatsApp falla, el error se registra y no frena al resto.
    """
    resultado = asyncio.run(_enviar_resumenes_semanales())
    return (
        f"enviados={resultado['enviados']} "
        f"omitidos={resultado['omitidos']} "
        f"errores={resultado['errores']}"
    )


# ==========================================
# Paso 1 de operación — monitoreo de salud
# ==========================================
async def _leer_estado_salud() -> str | None:
    """Lee el último estado de salud de Redis; ante fallo degrada a desconocido."""
    try:
        r = await _dedupe_redis()
        try:
            valor = await r.get(CLAVE_ESTADO_SALUD)
        finally:
            await r.aclose()
        if isinstance(valor, bytes):
            valor = valor.decode("utf-8")
        return str(valor) if valor else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("monitoreo: no se pudo leer el estado (%s)", exc)
        return None


async def _guardar_estado_salud(estado: str) -> None:
    """Guarda `ok`/`caido` con TTL para no repetir alertas indefinidamente."""
    try:
        r = await _dedupe_redis()
        try:
            await r.set(CLAVE_ESTADO_SALUD, estado, ex=TTL_ESTADO_SALUD)
        finally:
            await r.aclose()
    except Exception as exc:  # noqa: BLE001
        logger.warning("monitoreo: no se pudo guardar el estado (%s)", exc)


async def _verificar_salud() -> dict[str, Any]:
    """Consulta /health, alerta solo en la transición a caído y avisa la recuperación."""
    salud = await consultar_salud()
    estado_previo = await _leer_estado_salud()
    accion = decidir_accion(estado_previo, bool(salud.get("ok")))

    if accion in ("alertar", "recuperar"):
        if settings.ADMIN_PHONE:
            mensaje = formatear_mensaje_monitoreo(accion, salud)
            await enviar_mensaje_whatsapp(to_phone=settings.ADMIN_PHONE, mensaje=mensaje)
        else:
            logger.warning(TEXTO_SIN_ADMIN)

    await _guardar_estado_salud("ok" if salud.get("ok") else "caido")
    return {
        "ok": bool(salud.get("ok")),
        "accion": accion,
        "estado_previo": estado_previo,
        "detalle": salud.get("detalle"),
    }


@celery_app.task(name="workers.tasks.verificar_salud_task")  # type: ignore[untyped-decorator]
def verificar_salud_task() -> str:
    """
    Paso 1 de operación — chequeo de salud programado cada 5 minutos por Celery beat.
    No reinicia nada ni toca el sheet: solo observa y avisa.
    """
    resultado = asyncio.run(_verificar_salud())
    return f"ok={resultado['ok']} accion={resultado['accion']}"
