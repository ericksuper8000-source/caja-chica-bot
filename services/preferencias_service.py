"""
Paso 4 del Sprint — preferencias y notificaciones automáticas.

- `STOP` / `activar` controlan el resumen semanal automático (opt-out; default sí).
- Horario silencioso: no se envían mensajes automáticos entre 22:00 y 06:59 CR.
- La persistencia vive en la pestaña `Preferencias` (ver `sheets_service`).
"""

import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from services.politica_service import _normalizar
from services.sheets_service import guardar_preferencia_resumen, leer_preferencia_resumen

logger = logging.getLogger(__name__)

ZONA_CR = ZoneInfo("America/Costa_Rica")
HORA_INICIO_SILENCIO = 22
HORA_FIN_SILENCIO = 7

TEXTO_STOP_CONFIRMADO = (
    "Listo: no te voy a enviar mensajes automáticos (resumen semanal). "
    "Tus datos y tus registros siguen igual. Si querés activarlos de nuevo, "
    "escribime 'activar mensajes'."
)
TEXTO_ACTIVAR_CONFIRMADO = (
    "Listo: volviste a recibir el resumen semanal automático. "
    "Si querés pausarlo, escribime 'stop'."
)


def _limpiar(texto: str) -> str:
    """Normaliza y quita puntuación para comparar comandos cortos."""
    limpio = _normalizar(texto)
    limpio = re.sub(r"[¿?¡!.,;:()\"'«»]", "", limpio)
    return " ".join(limpio.split())


def detectar_stop_preferencias(texto: str) -> bool:
    """Detecta 'stop' y variantes simples de opt-out de mensajes automáticos."""
    t = _limpiar(texto)
    return t in {
        "stop",
        "stop mensajes",
        "no me mandes mensajes",
        "no me mandes mas mensajes",
        "no me escribas mas",
        "detener mensajes",
    }


def detectar_activar_preferencias(texto: str) -> bool:
    """Detecta 'activar' y variantes para volver a recibir automáticos."""
    t = _limpiar(texto)
    return t in {
        "activar",
        "activar mensajes",
        "activa mensajes",
        "quiero mis mensajes",
        "reanudar mensajes",
    }


def en_horario_silencio(ahora: datetime | None = None) -> bool:
    """True si estamos en horario de silencio (22:00–06:59 hora de Costa Rica)."""
    referencia = ahora or datetime.now(ZONA_CR)
    if referencia.tzinfo is None:
        referencia = referencia.replace(tzinfo=ZONA_CR)
    hora = referencia.astimezone(ZONA_CR).hour
    return hora >= HORA_INICIO_SILENCIO or hora < HORA_FIN_SILENCIO


async def resumen_semanal_habilitado(telefono: str) -> bool:
    """True si el cliente recibe el resumen semanal (default sí)."""
    return await leer_preferencia_resumen(telefono)


async def guardar_preferencia_automaticos(telefono: str, habilitado: bool) -> bool:
    """Persiste STOP/activar del resumen semanal."""
    return await guardar_preferencia_resumen(telefono, habilitado)
