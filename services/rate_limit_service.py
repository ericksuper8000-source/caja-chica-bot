"""
Límite de mensajes por teléfono (Seguridad #10 / P2-1).

El límite por IP del webhook no protege el costo por usuario: varios clientes pueden
compartir IP (NAT) y un solo teléfono puede spamear desde IPs distintas. Este límite
se aplica en el pipeline con Redis, antes de llamar a OpenAI o Sheets.

Regla: ventana fija de 60 segundos, contador atómico (`INCR`) por teléfono. Si Redis
falla, **se permite** el mensaje: la seguridad no debe tumbar el registro legítimo.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

VENTANA_SEGUNDOS = 60


def clave_rate_limit(telefono: str) -> str:
    return f"rate:telefono:{telefono}"


async def permitir_mensaje(
    redis_client: Any,
    telefono: str,
    limite: int | None = None,
    ventana_segundos: int = VENTANA_SEGUNDOS,
) -> bool:
    """
    True si el teléfono no superó el límite en la ventana actual.

    `limite <= 0` desactiva el control. Un fallo de Redis devuelve True (degradación
    segura: preferimos aceptar un mensaje de más antes que bloquear a un cliente).
    """
    limite_efectivo = settings.RATE_LIMIT_MENSAJES_POR_MINUTO if limite is None else limite
    if limite_efectivo <= 0:
        return True

    clave = clave_rate_limit(telefono)
    try:
        cantidad = await redis_client.incr(clave)
        if int(cantidad) == 1:
            await redis_client.expire(clave, ventana_segundos)
        return int(cantidad) <= limite_efectivo
    except Exception as error:  # noqa: BLE001 - Redis no debe bloquear el flujo
        logger.warning("rate_limit: no se pudo evaluar (%s); se permite", error)
        return True
