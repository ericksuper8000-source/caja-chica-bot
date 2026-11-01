"""
Cambio de número con verificación (Fase 6.1, spec 5.6).

Flujo: desde el número actual el cliente pide el cambio; el bot genera un código de
6 dígitos y lo muestra en ese chat (número anterior). Desde el número NUEVO el
cliente envía "cambiar numero <anterior> <codigo>" y el bot verifica el código antes de
mover la cuenta. El código vive en Redis (TTL 10 min, máximo 5 intentos).
"""

import json
import logging
import re
import secrets
from typing import Any

import redis.asyncio as aioredis

from app.config import settings
from services.politica_service import _normalizar

logger = logging.getLogger(__name__)

KEY_PREFIX = "cambio_numero"
TTL_SEGUNDOS = 600
MAX_INTENTOS = 5

TEXTO_CAMBIO_NUMERO_INICIO = (
    "Para cambiar de número, desde tu número NUEVO enviame:\n"
    "cambiar numero {telefono} {codigo}\n"
    "El código vence en 10 minutos. Si no tenés acceso al número anterior, "
    "escribime 'no tengo acceso a mi número'."
)

TEXTO_CAMBIO_NUMERO_CONFIRMADO = (
    "¡Listo! Tu cuenta quedó asociada a este número. Tus datos y tu espacio " "siguen igual."
)

TEXTO_CAMBIO_NUMERO_INVALIDO = (
    "No pude verificar el cambio. Revisá que el número anterior y el código sean "
    "correctos (el código vence en 10 minutos)."
)

TEXTO_CAMBIO_NUMERO_SIN_ACCESO = (
    "Entendido. Para cambiar de número sin acceso al anterior necesitamos verificar "
    "tu identidad. Tu solicitud quedó registrada y te contactaremos."
)

TEXTO_CAMBIO_NUMERO_ERROR = "No pude generar el código ahora. Intentá de nuevo en unos minutos."


def clave_cambio_numero(telefono: str) -> str:
    return f"{KEY_PREFIX}:{telefono}"


async def _redis() -> "aioredis.Redis":
    cliente = aioredis.from_url(  # type: ignore[no-untyped-call]
        settings.REDIS_URL, socket_connect_timeout=3
    )
    return cliente  # type: ignore[no-any-return]


def detectar_confirmacion_cambio_numero(texto: str) -> tuple[str, str] | None:
    """Detecta 'cambiar numero <anterior> <codigo>' y devuelve (telefono, codigo)."""
    normalizado = _normalizar(texto)
    coincidencia = re.search(r"cambiar\s+numero\s+(\d+)\s+(\d+)\b", normalizado)
    if not coincidencia:
        return None
    return coincidencia.group(1), coincidencia.group(2)


def detectar_inicio_cambio_numero(texto: str) -> bool:
    normalizado = _normalizar(texto)
    return any(
        frase in normalizado
        for frase in (
            "cambiar mi numero",
            "cambiar de numero",
            "cambiar numero",
            "cambio de numero",
        )
    )


def detectar_recuperacion_manual(texto: str) -> bool:
    normalizado = _normalizar(texto)
    sin_acceso = "no tengo acceso" in normalizado or "perdi el numero" in normalizado
    return sin_acceso and ("numero" in normalizado or "telefono" in normalizado)


async def crear_codigo_cambio(telefono: str) -> str | None:
    codigo = f"{secrets.randbelow(1_000_000):06d}"
    try:
        cliente = await _redis()
        try:
            payload = json.dumps({"codigo": codigo, "intentos": 0})
            await cliente.set(clave_cambio_numero(telefono), payload, ex=TTL_SEGUNDOS)
        finally:
            await cliente.aclose()
        return codigo
    except Exception as exc:
        logger.warning("cambio_numero: no se pudo guardar el código (%s)", exc)
        return None


async def verificar_codigo_cambio(telefono_anterior: str, codigo: str) -> bool:
    try:
        cliente = await _redis()
        try:
            clave = clave_cambio_numero(telefono_anterior)
            crudo = await cliente.get(clave)
            if not crudo:
                return False
            if isinstance(crudo, bytes):
                crudo = crudo.decode("utf-8")
            datos: dict[str, Any] = json.loads(crudo)
            if not secrets.compare_digest(str(datos.get("codigo", "")), str(codigo)):
                intentos = int(datos.get("intentos", 0)) + 1
                if intentos >= MAX_INTENTOS:
                    await cliente.delete(clave)
                else:
                    datos["intentos"] = intentos
                    await cliente.set(clave, json.dumps(datos), ex=TTL_SEGUNDOS)
                return False
            await cliente.delete(clave)
            return True
        finally:
            await cliente.aclose()
    except Exception as exc:
        logger.warning("cambio_numero: no se pudo verificar el código (%s)", exc)
        return False
