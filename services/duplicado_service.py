"""
Idempotencia anti-doble-tap (Fase 8.6.2) — evita filas duplicadas por reenvío.

Contexto: con red de familia el reenvío por mala señal es el caso **normal**, no el raro.
El bot guardaba cada reenvío como transacción nueva (3 audios iguales → 3 filas
`-1500`), dejando la caja mal y cobrando OpenAI de más, sin avisar. Le pasó al dueño 2
veces en 1 día de pruebas (filas `-50000 Transporte` y `-1000 Servicios Reactivacion`).

Principio de diseño (`plan-mejoras-pre-8A.md`, Oleada 2): **preguntar, no adivinar.** El
reintento vuelve al usuario como pregunta y solo se guarda si confirma.

Estado en Redis (ya es broker, ADR-0005): **0 llamadas extra a Sheets, 0 schema nuevo, no
toca el prompt** (protegiendo el fix 8.6.3) y no toca las columnas B:F.
- `dup:last:{telefono}` → `{"hash", "media_id", "ts"}` (TTL 10 min)
- `dup:pendiente:{telefono}` → transaction_data (TTL 10 min)

Criterio de duplicado, lo más estrecho posible para no juntar compras reales:
- mismo `media_id` (reenvío del mismo audio), **o**
- mismo hash (monto+categoría+detalle) dentro de 2 min (duda de triple toque).

Nunca por coincidencia de monto solamente, y nunca con TTL permanente (rompe-si a).
"""

import hashlib
from typing import Any, Literal

from services.politica_service import _normalizar

TTL_DEDUPE_SEGUNDOS = 600
VENTANA_MISMO_HASH_SEGUNDOS = 120

TEXTO_CONFIRMACION_DUPLICADO = (
    "Ese gasto ya lo apunté hace un momento. ¿Querés que lo registre otra vez " "o era el mismo?"
)
TEXTO_DUPLICADO_DESCARTADO = "Listo, no lo registro de nuevo. Queda una sola vez."
TEXTO_DUPLICADO_CONFIRMADO = "Ok, lo registré otra vez."


def clave_ultimo(sender_phone: str) -> str:
    return f"dup:last:{sender_phone}"


def clave_pendiente(sender_phone: str) -> str:
    return f"dup:pendiente:{sender_phone}"


def hash_transaccion(transaction_data: dict[str, Any]) -> str:
    """
    Huella estable de (monto, categoría, detalle). No incluye fecha ni teléfono: solo
    sirve para detectar que dos mensajes describen el mismo movimiento.
    """
    monto = transaction_data.get("monto")
    categoria = _normalizar(str(transaction_data.get("categoria") or ""))
    detalle = _normalizar(str(transaction_data.get("detalle") or ""))
    crudo = f"{monto}|{categoria}|{detalle}".encode()
    return hashlib.sha256(crudo).hexdigest()[:32]


def es_mismo_reenvio(media_id_actual: str | None, media_id_previo: str | None) -> bool:
    """Reenvío del mismo audio: mismo `media_id`."""
    return bool(media_id_actual) and media_id_actual == media_id_previo


def es_mismo_mismo_momento(
    hash_previo: str | None, ts_previo: int | None, hash_actual: str, ahora: int
) -> bool:
    """Duda de triple toque: misma huella dentro de la ventana de 2 minutos."""
    if not hash_previo or ts_previo is None:
        return False
    if hash_previo != hash_actual:
        return False
    return (ahora - ts_previo) <= VENTANA_MISMO_HASH_SEGUNDOS


def detectar_confirmacion_duplicado(texto: str) -> Literal["otro", "mismo"] | None:
    """
    Detecta la respuesta a `TEXTO_CONFIRMACION_DUPLICADO`. Retorna 'otro' (registrar de
    nuevo), 'mismo' (no duplicar) o None si el mensaje no es una confirmación.

    Deliberadamente conservador (rompe-si c): frases cortas y específicas, nunca un "no"
    suelto que podría ser otra cosa. Un mensaje largo (>6 palabras) nunca cuenta como
    confirmación — así la pregunta no se cuela en el flujo normal.
    """
    normalizado = _normalizar(texto)
    if not normalizado:
        return None
    if len(normalizado.split()) > 6:
        return None

    if any(
        marca in normalizado
        for marca in (
            "es el mismo",
            "era el mismo",
            "no lo registres",
            "no repitas",
            "no lo repitas",
            "ya lo registraste",
            "no gracias",
            "dejalo asi",
            "dejalo",
        )
    ):
        return "mismo"

    if any(
        marca in normalizado
        for marca in (
            "si registralo",
            "registralo otra vez",
            "registrar otra vez",
            "si otra vez",
            "son dos",
            "otro gasto",
            "de nuevo",
            "registralo",
        )
    ):
        return "otro"

    return None
