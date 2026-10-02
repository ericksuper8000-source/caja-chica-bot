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
import re
from typing import Any, Literal

from services.politica_service import _normalizar

TTL_DEDUPE_SEGUNDOS = 600
VENTANA_MISMO_HASH_SEGUNDOS = 120

TEXTO_CONFIRMACION_DUPLICADO = (
    "Ese gasto ya lo apunté hace un momento. ¿Querés que lo registre otra vez " "o era el mismo?"
)
TEXTO_DUPLICADO_DESCARTADO = "Listo, no lo registro de nuevo. Queda una sola vez."
TEXTO_DUPLICADO_CONFIRMADO = "Ok, lo registré otra vez."

MAX_PALABRAS_CONFIRMACION = 6
"""
Techo de palabras para que un mensaje pueda contarse como respuesta a la pregunta del
duplicado. Un mensaje más largo es conversación sobre otra cosa, no una respuesta.
"""

CONFIRMACION_CORTAS_MISMO = frozenset(
    {
        "no",
        "nada",
        "mismo",
        "igual",
        "lo mismo",
        "el mismo",
        "dejalo",
        "dejala",
        "dejelo",
        "dejela",
    }
)
"""
Respuestas de 1-2 palabras a "¿es otro o el mismo?".

Se comparan por **coincidencia exacta**, nunca por substring: `si` está contenido en
`sin monto`, `va` en `van` y `ok` en `token`. Con una pendiente activa esa decisión mueve
dinero real (registra una fila o descarta un gasto), así que un falso positivo aquí no
es un error de ortografía.
"""

CONFIRMACION_CORTAS_OTRO = frozenset(
    {
        "si",
        "va",
        "dale",
        "dele",
        "ok",
        "claro",
        "otro",
        "otra",
        "nuevo",
        "nueva",
        "mas",
        "sirve",
        "yes",
    }
)
"""Idem `CONFIRMACION_CORTAS_MISMO`, pero para 'registralo otra vez'."""

CONFIRMACION_FRASES_MISMO = (
    "es el mismo",
    "era el mismo",
    "es lo mismo",
    "era lo mismo",
    "fue el mismo",
    "fue lo mismo",
    "es la misma",
    "era la misma",
    "no es otro",
    "no es otra",
    "no lo registres",
    "no lo registre",
    "no lo guardes",
    "no lo guarde",
    "no lo apuntes",
    "no lo apunte",
    "no lo repitas",
    "no lo repita",
    "ya lo registraste",
    "ya lo habia registrado",
    "no gracias",
    "solo era uno",
    "solo era una",
    "era uno solo",
    "era una sola",
    "dejalo asi",
    "dejalo igual",
)
"""Respuestas de 3+ palabras a 'no registrar otra vez'. Se comparan por substring."""

CONFIRMACION_FRASES_OTRO = (
    "si registralo",
    "registralo otra vez",
    "registrar otra vez",
    "registralo",
    "registra otra vez",
    "guardalo",
    "guardalo otra vez",
    "apuntalo",
    "apuntalo otra vez",
    "anotalo otra vez",
    "son dos",
    "fueron dos",
    "dos veces",
    "otro gasto",
    "es otro",
    "si es otro",
    "otra vez",
    "de nuevo",
    "mas bien",
    "si dale",
)
"""Idem `CONFIRMACION_FRASES_MISMO`, pero para 'registralo otra vez'."""


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


def _sin_puntuacion(texto_normalizado: str) -> str:
    """
    Quita signos de puntuación y colapsa espacios. Se aplica **solo dentro de este
    módulo**, nunca a `_normalizar` de forma global: el gate legal de consentimiento usa
    esa misma función y cambiar su comportamiento alteraría decisiones de Ley 8968.

    Aquí sí hace falta porque en WhatsApp la gente escribe "sí.", "Va!!", "¿es lo mismo?"
    y sin esto la coincidencia exacta de 1-2 palabras se pierde justo en los mensajes más
    cortos, que son los más comunes.
    """
    return " ".join(re.sub(r"[^\w\s]", " ", texto_normalizado).split())


def _coincide(texto: str, cortas: frozenset[str], frases: tuple[str, ...]) -> bool:
    """
    Coincidencia en 2 capas, para aceptar variantes naturales sin abrir falsos positivos:

    - **1-2 palabras → coincidencia EXACTA** contra cortas y frases. Exacta porque en
      substring las marcas cortas colisionan (`si` ⊂ `sin monto`, `va` ⊂ `van`,
      `ok` ⊂ `token`), y con pendiente activa un error decide sobre dinero real.
    - **3 a `MAX_PALABRAS_CONFIRMACION` palabras → substring** contra las frases, que sí
      son marcadores inequívocos.
    """
    if not texto:
        return False
    palabras = texto.split()
    if len(palabras) > MAX_PALABRAS_CONFIRMACION:
        return False
    if len(palabras) <= 2:
        return texto in cortas or texto in frases
    return any(frase in texto for frase in frases)


def detectar_confirmacion_duplicado(texto: str) -> Literal["otro", "mismo"] | None:
    """
    Detecta la respuesta a `TEXTO_CONFIRMACION_DUPLICADO`. Retorna 'otro' (registrar de
    nuevo), 'mismo' (no duplicar) o None si el mensaje no es una confirmación.

    **Por qué "sí" pelado significa "otro":** la única pregunta en pantalla es
    "¿querés que lo registre otra vez o era el mismo?", así que un "sí" aislado solo puede
    querer decir "sí, otra vez". Antes la lista de frases no lo incluía y el bot volvía a
    pedir el monto: el duplicado se evitaba pero la experiencia se rompía justo cuando el
    usuario ya estaba cooperando.

    **Por qué es seguro interceptarlo:** `workers/tasks.py` solo llama a esta función
    cuando existe una pendiente activa. Sin pendiente nunca se intercepta, así que no
    toca el consentimiento, los derechos ARCO ni la aclaración.

    Ante la duda devuelve `None` y el mensaje sigue su camino normal (preguntar, no
    adivinar — el principio de la Fase 8.6.2).
    """
    texto = _sin_puntuacion(_normalizar(texto))
    if not texto:
        return None

    # Se evalúa "mismo" primero: es la salida conservadora (no duplicar), igual que en la
    # versión anterior, y ante un mensaje ambiguo es la que hace menos daño.
    if _coincide(texto, CONFIRMACION_CORTAS_MISMO, CONFIRMACION_FRASES_MISMO):
        return "mismo"
    if _coincide(texto, CONFIRMACION_CORTAS_OTRO, CONFIRMACION_FRASES_OTRO):
        return "otro"
    return None
