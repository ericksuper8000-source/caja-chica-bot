"""
Corrección, borrado, deshacer e historial (A08) — detección y formato puros.

Este módulo NO toca Google Sheets ni Redis: recibe texto o movimientos y devuelve
intenciones o mensajes listos para WhatsApp. Así las reglas de D23/D24/D25 se pueden
probar sin red y el pipeline queda como orquestador.

Reglas ratificadas:
- D23: la ventana de deshacer dura hasta el siguiente mensaje o 10 minutos.
- D24: borrar exige confirmación explícita con el movimiento completo a la vista.
- D25: corregir/borrar/deshacer se permiten aunque el plan esté vencido.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from services.politica_service import _normalizar

ZONA_CR = ZoneInfo("America/Costa_Rica")
TTL_A08_SEGUNDOS = 600
MAX_HISTORIAL = 5

TEXTO_BORRADO_SIN_MOVIMIENTOS = "No encontré movimientos activos para borrar."
TEXTO_BORRADO_NO_ENCONTRADO = (
    "No encontré un movimiento activo que coincida con lo que pediste. No borré nada."
)
TEXTO_BORRADO_CANCELADO = "Listo, no borré nada. El movimiento sigue contando."
TEXTO_BORRADO_OK = 'Borro: ya no cuenta en tus reportes. Si fue un error, decime "deshacé".'
TEXTO_BORRADO_ERROR = "No pude borrar el movimiento. No se cambió nada; intentá de nuevo."
TEXTO_BORRADO_DUDA = (
    "No borré nada. Si querés borrarlo, mandame de nuevo el pedido y confirmá con " '"sí, borrar".'
)
TEXTO_SELECCION_INVALIDA = (
    'No borré nada. No entendí cuál. Probá de nuevo con "borrá el último gasto".'
)
TEXTO_NADA_QUE_DESHACER = (
    "No tengo una acción reciente para deshacer. Solo puedo deshacer la última "
    "acción dentro de los 10 minutos siguientes y antes de otro mensaje."
)
TEXTO_DESHECHO_CREACION = "Deshecho: el movimiento ya no cuenta en tus reportes."
TEXTO_DESHECHO_CORRECCION = "Deshecho: el movimiento volvió a como estaba antes de la corrección."
TEXTO_DESHECHO_BORRADO = "Deshecho: el movimiento vuelve a contar en tus reportes."
TEXTO_DESHECHO_REACTIVACION = "Deshecho: el movimiento vuelve a quedar anulado."
TEXTO_DESHECHO_ERROR = (
    "No pude deshacer el cambio. No se modificó nada; podés revisar el historial."
)
TEXTO_REACTIVADO = "Reactivado: el movimiento vuelve a contar en tus reportes."
TEXTO_REACTIVAR_ERROR = "No pude reactivar el movimiento. No se cambió nada; intentá de nuevo."
TEXTO_REACTIVAR_SIN_ANULADOS = "No hay movimientos anulados para reactivar."
TEXTO_HISTORIAL_VACIO = "Todavía no hay cambios registrados en tu cuenta."

_ACCIONES_HISTORIAL = {
    "crear": "registro",
    "corregir": "corrección",
    "anular": "borrado",
    "reactivar": "reactivación",
    "deshacer": "deshecho",
}

_CAMPOS_SNAPSHOT = (
    "fecha_movimiento",
    "monto_centimos",
    "monto",
    "categoria",
    "detalle",
    "telefono",
    "movimiento_id",
    "tipo_movimiento",
    "moneda",
    "contexto_tipo",
    "estado",
    "version",
    "fecha_registro",
    "origen",
)


@dataclass(frozen=True)
class SolicitudBorrado:
    """Pedido de borrado: puede filtrar por tipo, monto y/o posición ordinal."""

    tipo: str | None = None
    monto_centimos: int | None = None
    ordinal: int | None = None


_ORDINALES_SOLICITUD = {
    "primer": 0,
    "primero": 0,
    "primera": 0,
    "segundo": 1,
    "segunda": 1,
    "tercer": 2,
    "tercero": 2,
    "tercera": 2,
    "cuarto": 3,
    "cuarta": 3,
    "quinto": 4,
    "quinta": 4,
}


def _texto_normalizado(texto: str) -> str:
    """
    Minúsculas, sin tildes y sin puntuación; tokens separados por un espacio.

    Los separadores de miles se eliminan antes de borrar la puntuación: "5.000" debe
    leerse como 5000, no como "5 000" (que hacía que un borrado apuntara a ₡5).
    """
    limpio = _normalizar(texto)
    limpio = re.sub(r"(?<=\d)[.,](?=\d)", "", limpio)
    return " ".join(re.sub(r"[^\w\s]", " ", limpio).split())


def _palabras(texto: str) -> list[str]:
    return _texto_normalizado(texto).split()


def _monto_de_palabras(palabras: list[str]) -> int | None:
    """Primer número con multiplicador tico: '5000', '5 mil', '5 rojos', '2 tucanes'."""
    multiplicadores = {
        "mil": 1000,
        "rojo": 1000,
        "rojos": 1000,
        "tucan": 5000,
        "tucanes": 5000,
        "teja": 100,
        "tejas": 100,
    }
    for indice, palabra in enumerate(palabras):
        limpio = palabra.replace(".", "").replace(",", "")
        if not limpio.isdigit():
            continue
        valor = int(limpio)
        siguiente = palabras[indice + 1] if indice + 1 < len(palabras) else ""
        return valor * multiplicadores.get(siguiente, 1)
    return None


def detectar_solicitud_borrado(texto: str) -> SolicitudBorrado | None:
    """
    Detecta "borrá el último gasto", "borra el gasto de 5000", "anulá el último".

    No intercepta presupuestos: "borrar presupuesto" lo maneja el flujo de presupuestos.
    """
    texto_norm = _texto_normalizado(texto)
    if not texto_norm or "presupuesto" in texto_norm:
        return None

    palabras = texto_norm.split()
    verbos = {
        "borra",
        "borrar",
        "borrame",
        "borren",
        "borralo",
        "borrala",
        "elimina",
        "eliminar",
        "eliminalo",
        "eliminala",
        "anula",
        "anular",
        "anulalo",
        "anulala",
    }
    if not any(palabra in verbos for palabra in palabras):
        return None

    tipo: str | None = None
    if any(palabra in {"gasto", "gastos"} for palabra in palabras):
        tipo = "gasto"
    elif any(palabra in {"ingreso", "ingresos"} for palabra in palabras):
        tipo = "ingreso"

    monto = _monto_de_palabras(palabras)
    ordinal = next(
        (_ORDINALES_SOLICITUD[palabra] for palabra in palabras if palabra in _ORDINALES_SOLICITUD),
        None,
    )
    return SolicitudBorrado(
        tipo=tipo,
        monto_centimos=None if monto is None else monto * 100,
        ordinal=ordinal,
    )


def detectar_confirmacion_borrado(texto: str) -> Literal["si", "no"] | None:
    """
    Respuesta a "¿Borro este movimiento?". D24 exige confirmación explícita.

    "Sí" pelado NO alcanza: en una conversación financiera puede ser la respuesta a
    otra cosa. Se aceptan frases con verbo de borrado o un "confirmo" inequívoco.
    """
    texto_norm = _texto_normalizado(texto)
    if not texto_norm:
        return None
    palabras = texto_norm.split()

    frases_no = (
        "no",
        "no gracias",
        "no borres",
        "no lo borres",
        "no borrar",
        "mejor no",
        "cancelar",
        "cancela",
        "cancelalo",
        "dejalo",
        "dejala",
        "dejalo asi",
        "nada",
    )
    if texto_norm in frases_no:
        return "no"

    frases_si = (
        "confirmo",
        "confirmado",
        "si borrar",
        "si borra",
        "si borralo",
        "si borrala",
        "claro borralo",
        "dale borralo",
        "borralo",
        "borrala",
        "si confirmo",
        "correcto borrar",
    )
    if texto_norm in frases_si:
        return "si"

    # Frases algo más largas ("sí, borrá el último") pero todavía inequívocas.
    if len(palabras) <= 8:
        tiene_si = any(
            palabra in {"si", "confirmo", "confirmado", "dale", "claro"} for palabra in palabras
        )
        tiene_borrar = any(palabra.startswith("borra") for palabra in palabras)
        if tiene_si and tiene_borrar:
            return "si"
    return None


def detectar_deshacer(texto: str) -> bool:
    """Detecta el pedido explícito de deshacer (D23: nunca automático)."""
    palabras = _palabras(texto)
    if not palabras:
        return False
    if (
        any(
            palabra in {"deshace", "deshacer", "deshacelo", "deshacela", "revertir", "revertilo"}
            for palabra in palabras
        )
        or "undo" in palabras
    ):
        return True
    texto_norm = " ".join(palabras)
    return any(
        frase in texto_norm for frase in ("volver atras", "volve atras", "volver para atras")
    )


def detectar_historial(texto: str) -> bool:
    """Detecta "historial de cambios" o "¿quién cambió esto?" sin confundir registros."""
    palabras = _palabras(texto)
    if "historial" in palabras:
        return True
    texto_norm = " ".join(palabras)
    return any(
        frase in texto_norm
        for frase in (
            "que cambio",
            "que cambios",
            "quien cambio",
            "quien lo cambio",
            "quien modifico",
            "ultimos cambios",
            "mis cambios",
            "cambios recientes",
        )
    )


def detectar_reactivar(texto: str) -> bool:
    """Detecta "reactivá el último" / "restaurá el anulado"."""
    palabras = _palabras(texto)
    if any(
        palabra
        in {
            "reactiva",
            "reactivar",
            "reactivalo",
            "reactivala",
            "restaura",
            "restaurar",
            "restauralo",
            "restaurala",
        }
        for palabra in palabras
    ):
        return True
    texto_norm = " ".join(palabras)
    return any(
        frase in texto_norm for frase in ("volve a activar", "volver a activar", "activa de nuevo")
    )


def detectar_intencion_correccion(texto: str) -> bool:
    """
    Señal barata de corrección para el bypass D25 (plan vencido).

    Solo decide si vale la pena llamar al parser con la suscripción vencida. Si el
    parser luego devuelve `registrar`, el pipeline vuelve a bloquear el alta: un falso
    positivo aquí no puede crear un movimiento con el plan vencido.
    """
    palabras = _palabras(texto)
    if any(
        palabra
        in {
            "corrige",
            "corregi",
            "corregir",
            "corregime",
            "corregiste",
            "corrija",
            "correccion",
            "corrijas",
        }
        for palabra in palabras
    ):
        return True
    texto_norm = " ".join(palabras)
    return any(
        frase in texto_norm
        for frase in (
            "no era",
            "no eran",
            "en vez de",
            "me equivoque",
            "cambia",
            "cambiar",
            "cambiame",
            "actualiza",
            "actualizar",
            "ponelo en",
            "ponle",
        )
    )


def formatear_monto(monto_centimos: int) -> str:
    """Monto en colones con separador de miles, como el resto de los mensajes del bot."""
    return f"₡{abs(int(monto_centimos)) // 100:,}"


def _etiqueta_tipo(tipo: Any) -> str:
    valor = str(tipo or "gasto").strip().lower()
    if valor == "gasto":
        return "Gasto"
    if valor == "ingreso":
        return "Ingreso"
    return valor.capitalize() or "Movimiento"


def _formatear_fecha(valor: Any) -> str:
    """Fecha UTC de la hoja → fecha/hora de Costa Rica; si no parsea, se muestra cruda."""
    texto = str(valor or "").strip()
    if not texto:
        return "sin fecha"
    for formato in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            momento = datetime.strptime(texto, formato)
            if formato == "%Y-%m-%d":
                return momento.strftime("%d/%m/%Y")
            return momento.replace(tzinfo=UTC).astimezone(ZONA_CR).strftime("%d/%m/%Y %H:%M")
        except ValueError:
            continue
    return texto


def snapshot_movimiento(movimiento: dict[str, Any]) -> dict[str, Any]:
    """Copia JSON-safe de los campos del movimiento (sin `_fila` ni datos de mensajes)."""
    return {campo: movimiento.get(campo) for campo in _CAMPOS_SNAPSHOT}


def resumen_movimiento(movimiento: dict[str, Any]) -> str:
    """Una línea con tipo, signo, monto, categoría, fecha y contexto (D24)."""
    tipo = str(movimiento.get("tipo_movimiento") or "gasto").lower()
    signo = "-" if tipo == "gasto" else "+"
    monto = formatear_monto(int(movimiento.get("monto_centimos") or 0))
    categoria = str(movimiento.get("categoria") or "Otros")
    fecha = _formatear_fecha(movimiento.get("fecha_movimiento"))
    contexto = str(movimiento.get("contexto_tipo") or "personal")
    detalle = str(movimiento.get("detalle") or "").strip()
    linea = f"{_etiqueta_tipo(tipo)}: {signo}{monto} · {categoria} · {fecha} · {contexto}"
    return f"{linea} · {detalle}" if detalle else linea


def formatear_confirmacion_movimiento(movimiento: dict[str, Any], *, verbo: str = "Guardé") -> str:
    """
    Confirmación completa (A08 §5.1): tipo, signo, monto, categoría, fecha y contexto.
    """
    return (
        f"{verbo}: {resumen_movimiento(movimiento)}\n"
        '¿Está bien? Si algo no cuadra, decime "corregí..." o "borrá el último".'
    )


def formatear_prompt_borrado(movimiento: dict[str, Any]) -> str:
    """Muestra el movimiento completo y pide la frase explícita de D24."""
    return (
        "¿Borro este movimiento?\n\n"
        f"{resumen_movimiento(movimiento)}\n\n"
        'Respondé "sí, borrar" para confirmar, o "no" para dejarlo como está.'
    )


def formatear_lista_borrado(candidatos: list[dict[str, Any]]) -> str:
    """Lista numerada para el caso de dos movimientos iguales."""
    lineas = [
        f"{indice}. {resumen_movimiento(movimiento)}"
        for indice, movimiento in enumerate(candidatos, start=1)
    ]
    return (
        "Encontré varios movimientos que coinciden:\n\n"
        + "\n".join(lineas)
        + "\n\n¿Cuál borro? Respondé con el número."
    )


def indice_seleccionado(texto: str, candidatos: list[dict[str, Any]]) -> int | None:
    """Interpreta '1', 'primero', 'el segundo' o el monto de la lista."""
    palabras = _palabras(texto)
    if not palabras:
        return None
    ordinales = {
        "1": 0,
        "uno": 0,
        "primero": 0,
        "primer": 0,
        "2": 1,
        "dos": 1,
        "segundo": 1,
        "3": 2,
        "tres": 2,
        "tercero": 2,
        "4": 3,
        "cuatro": 3,
        "cuarto": 3,
        "5": 4,
        "cinco": 4,
        "quinto": 4,
    }
    for palabra in palabras:
        if palabra in ordinales and ordinales[palabra] < len(candidatos):
            return ordinales[palabra]
    monto = _monto_de_palabras(palabras)
    if monto is not None:
        for indice, movimiento in enumerate(candidatos):
            if int(movimiento.get("monto_centimos") or 0) == monto * 100:
                return indice
    return None


def _describir_correccion(antes: dict[str, Any], despues: dict[str, Any]) -> str:
    """Resumen legible del delta de una corrección: monto, tipo, categoría, etc."""
    cambios: list[str] = []
    monto_antes = int(antes.get("monto_centimos") or 0)
    monto_despues = int(despues.get("monto_centimos") or 0)
    if monto_antes != monto_despues:
        cambios.append(f"monto {formatear_monto(monto_antes)} → {formatear_monto(monto_despues)}")
    tipo_antes = str(antes.get("tipo_movimiento") or "")
    tipo_despues = str(despues.get("tipo_movimiento") or "")
    if tipo_antes != tipo_despues:
        cambios.append(f"tipo {_etiqueta_tipo(tipo_antes)} → {_etiqueta_tipo(tipo_despues)}")
    categoria_antes = str(antes.get("categoria") or "Otros")
    categoria_despues = str(despues.get("categoria") or "Otros")
    if categoria_antes != categoria_despues:
        cambios.append(f"categoría {categoria_antes} → {categoria_despues}")
    detalle_antes = str(antes.get("detalle") or "")
    detalle_despues = str(despues.get("detalle") or "")
    if detalle_antes != detalle_despues:
        cambios.append(f"detalle «{detalle_antes}» → «{detalle_despues}»")
    contexto_antes = str(antes.get("contexto_tipo") or "personal")
    contexto_despues = str(despues.get("contexto_tipo") or "personal")
    if contexto_antes != contexto_despues:
        cambios.append(f"contexto {contexto_antes} → {contexto_despues}")
    fecha_antes = str(antes.get("fecha_movimiento") or "")
    fecha_despues = str(despues.get("fecha_movimiento") or "")
    if fecha_antes != fecha_despues:
        cambios.append(f"fecha {_formatear_fecha(fecha_antes)} → {_formatear_fecha(fecha_despues)}")
    return "; ".join(cambios)


def formatear_historial(entradas: list[dict[str, Any]], actor_id: str) -> str:
    """
    Historial reciente del propio usuario (A08 §5.5): qué cambió, cuándo y quién.

    No incluye el mensaje original ni datos de terceros; solo los campos financieros
    del antes/después que ya viven en la auditoría.
    """
    if not entradas:
        return TEXTO_HISTORIAL_VACIO

    lineas: list[str] = []
    for entrada in entradas:
        accion = _ACCIONES_HISTORIAL.get(str(entrada.get("accion")), str(entrada.get("accion")))
        antes = entrada.get("antes")
        despues = entrada.get("despues")
        if (
            str(entrada.get("accion")) == "corregir"
            and isinstance(antes, dict)
            and isinstance(despues, dict)
        ):
            resumen = _describir_correccion(antes, despues) or "cambio registrado"
        else:
            movimiento = despues or antes or {}
            if not isinstance(movimiento, dict):
                movimiento = {}
            resumen = (
                resumen_movimiento(movimiento)
                if movimiento.get("monto_centimos")
                else "cambio registrado"
            )
        momento = _formatear_fecha(entrada.get("fecha"))
        quien = "vos" if str(entrada.get("actor_id")) == actor_id else "sistema"
        lineas.append(f"• {momento} · {accion} · {resumen} ({quien})")

    return "Últimos cambios de tu cuenta:\n" + "\n".join(lineas)
