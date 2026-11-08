"""
Monitoreo de salud y alertas operativas (Paso 1 de operación).

El worker consulta periódicamente el `/health` de la app. Si el servicio deja de
responder, avisa por WhatsApp al teléfono administrativo; cuando vuelve, manda un
mensaje de recuperación. La regla es simple: **una alerta por caída**, no una cada
cinco minutos. El estado se guarda en Redis para sobrevivir entre ejecuciones.

Este módulo es puro salvo `consultar_salud` (HTTP). La decisión y los textos se prueban
sin red ni WhatsApp.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

CLAVE_ESTADO_SALUD = "monitor:salud:estado"
TTL_ESTADO_SALUD = 86400  # 24 h: si el worker estuvo caído, no repetir alertas viejas.

TEXTO_ALERTA_CAIDA = (
    "ALERTA: el bot no responde al chequeo de salud. "
    "Estado: {estado}. Detalle: {detalle}. "
    "Revisá el VPS, los contenedores y los logs."
)
TEXTO_RECUPERACION = "El bot volvió a responder al chequeo de salud. Servicio recuperado."
TEXTO_SIN_ADMIN = "Monitoreo: no hay ADMIN_PHONE configurado; no se pudo enviar la alerta de salud."


async def consultar_salud(url: str | None = None, timeout: float = 5.0) -> dict[str, Any]:
    """Consulta el healthcheck y devuelve `{ok, status_code, detalle}` sin lanzar."""
    destino = url or settings.HEALTHCHECK_URL
    try:
        async with httpx.AsyncClient(timeout=timeout) as cliente:
            respuesta = await cliente.get(destino)
        return {
            "ok": respuesta.status_code == 200,
            "status_code": respuesta.status_code,
            "detalle": respuesta.text[:300],
        }
    except Exception as error:  # noqa: BLE001 - el monitoreo nunca debe tumbar al worker
        return {
            "ok": False,
            "status_code": None,
            "detalle": type(error).__name__,
        }


def decidir_accion(estado_previo: str | None, salud_ok: bool) -> str:
    """
    Decide si hay que alertar, avisar recuperación o no hacer nada.

    - caído -> sigue caído: nada (evita spam).
    - ok/desconocido -> caído: alertar.
    - caído -> ok: recuperar.
    - ok/desconocido -> ok: nada.
    """
    if salud_ok and estado_previo == "caido":
        return "recuperar"
    if not salud_ok and estado_previo != "caido":
        return "alertar"
    return "nada"


def formatear_mensaje_monitoreo(accion: str, salud: dict[str, Any]) -> str:
    """Texto listo para WhatsApp según la acción decidida."""
    if accion == "recuperar":
        return TEXTO_RECUPERACION
    estado = salud.get("status_code") or "sin respuesta"
    detalle = str(salud.get("detalle") or "")[:200]
    return TEXTO_ALERTA_CAIDA.format(estado=estado, detalle=detalle)
