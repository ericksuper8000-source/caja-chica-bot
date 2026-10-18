"""
Sprint de Valor Visible — Reportes de caja por chat (S4/S4b, V1).

El bot hoy registra movimientos, pero devuelve poco: este módulo le da "salida" de
valor. Cuando el usuario pide `"resumen de la semana"` o `"reporte del mes"` (pedido
determinista, sin GPT), se agregan sus transacciones y se responde con una tarjeta
visual (PNG) más un texto corto; si la imagen falla, cae automáticamente a texto.

Decisiones de alcance (V1, `docs/plan-sprint-valor-visible.md`):
- Solo período actual: semana en curso = últimos 7 días (incluye hoy); mes = del 1
  a hoy. "Semana pasada"/"mes anterior" NO se detectan todavía (caen al flujo normal).
- Comparación vs período anterior equivalente: 7 días previos, o mismo tramo de días
  del mes pasado (para que la comparación a mitad de mes sea justa).
- Sin llamadas a OpenAI: la detección es por palabras clave y el cálculo es local.
- Las fechas de la hoja se guardan en UTC (`append_transaction_to_sheet`); acá se
  convierten a hora de Costa Rica para agrupar por "día" como lo piensa el usuario.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

from services.politica_service import _normalizar

ZONA_CR = ZoneInfo("America/Costa_Rica")

_MESES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)
_MESES_ABREVIADOS = (
    "ene",
    "feb",
    "mar",
    "abr",
    "may",
    "jun",
    "jul",
    "ago",
    "sep",
    "oct",
    "nov",
    "dic",
)

# ---------------------------------------------------------------
# DETECCIÓN DEL PEDIDO DE REPORTE (determinista, sin GPT)
# ---------------------------------------------------------------
MAX_PALABRAS_CONSULTA_REPORTE = 12
"""
Techo de palabras para que un mensaje cuente como pedido de reporte. Un texto más
largo es un gasto descrito con detalle o una conversación, no un pedido de resumen.
"""

_PALABRAS_PEDIDO_REPORTE = frozenset({"resumen", "reporte", "balance"})
_FRASES_ESTADO = ("como va", "como voy", "como vamos", "como me fue", "que tal va", "que tal voy")
_PALABRAS_BLOQUEO_REPORTE = frozenset(
    {
        "tarjeta",
        "tarjetas",
        "pague",
        "pago",
        "pagar",
        "pagare",
        "abone",
        "abonar",
        "deposite",
        "depositar",
        "cobre",
        "cobrar",
        "deuda",
        "debo",
        "prestamo",
    }
)
"""
Palabras que delatan OTRA intención aunque el mensaje diga "resumen" o "balance":
p. ej. `"pagué el resumen de la tarjeta"` es un gasto (o una frase sin monto), no un
pedido de reporte. Ante la duda se deja pasar al flujo normal: un reporte enviado por
error confunde; un gasto NO registrado por un falso reporte es una pérdida real.
"""

_MARCAS_PERIODO_PASADO = frozenset({"pasada", "pasado", "anterior", "anteriores"})
_MESES_PALABRAS = frozenset(_MESES) | frozenset(_MESES_ABREVIADOS)
_PUNTUACION = re.compile(r"[¿?¡!.,;:()\"'«»]")


def _limpiar(texto: str) -> str:
    """Normaliza (minúsculas, sin tildes) y quita puntuación para comparar palabras."""
    return " ".join(_PUNTUACION.sub(" ", _normalizar(texto)).split())


def detectar_solicitud_reporte(texto: str) -> Literal["semana", "mes"] | None:
    """
    Detecta si el mensaje pide un reporte de caja ("resumen de la semana",
    "reporte del mes", "cómo va el mes", "balance", ...). Retorna "semana", "mes"
    o None si no es un pedido de reporte.

    Reglas de seguridad (ante la duda, None — nunca un reporte equivocado):
    - Con dígitos (un monto) NO es pedido de reporte.
    - Con verbos de pago, "tarjeta", "deuda" o nombre de mes ("resumen de la tarjeta",
      "resumen de setiembre") NO se detecta: es otra cosa o un período que no cubrimos.
    - Períodos pasados ("semana pasada", "mes anterior") NO se detectan en V1.
    - Un pedido sin período ("resumen", "balance") asume la semana.
    """
    limpio = _limpiar(texto)
    if not limpio:
        return None

    palabras = limpio.split()
    if len(palabras) > MAX_PALABRAS_CONSULTA_REPORTE:
        return None
    if any(caracter.isdigit() for caracter in limpio):
        return None

    conjunto = set(palabras)
    if conjunto & _PALABRAS_BLOQUEO_REPORTE:
        return None
    if conjunto & _MARCAS_PERIODO_PASADO:
        return None
    if conjunto & _MESES_PALABRAS:
        return None

    pedido = bool(conjunto & _PALABRAS_PEDIDO_REPORTE)
    estado = any(frase in limpio for frase in _FRASES_ESTADO)
    if not pedido and not estado:
        return None

    if "mes" in conjunto or "mensual" in conjunto:
        return "mes"
    if "semana" in conjunto or "semanal" in conjunto:
        return "semana"
    # Pedido sin período explícito ("resumen", "balance", "cómo va todo"): la semana.
    return "semana" if pedido else None


# ---------------------------------------------------------------
# AGREGACIÓN
# ---------------------------------------------------------------
_FORMATO_FECHA_HOJA = "%Y-%m-%d %H:%M:%S"


@dataclass(frozen=True)
class CategoriaGasto:
    """Total gastado en una categoría dentro del período y su % del gasto total."""

    nombre: str
    monto: int
    porcentaje: int


@dataclass(frozen=True)
class ResumenCaja:
    """Cifras del período listas para formatear (texto) o dibujar (tarjeta PNG)."""

    periodo: Literal["semana", "mes"]
    etiqueta: str
    ingresos: int
    gastos: int
    balance: int
    n_movimientos: int
    categorias: list[CategoriaGasto]
    mayor_gasto: tuple[int, str] | None
    comparacion_pct: int | None
    tiene_datos: bool


def _parsear_fecha(valor: Any) -> datetime | None:
    """
    Convierte la fecha de la hoja ('YYYY-MM-DD HH:MM:SS', guardada en UTC por el
    pipeline) a hora de Costa Rica. None si la celda no es una fecha válida.
    """
    try:
        fecha_utc = datetime.strptime(str(valor), _FORMATO_FECHA_HOJA).replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None
    return fecha_utc.astimezone(ZONA_CR)


def _parsear_monto(valor: Any) -> int | None:
    """Lee el monto de la hoja (número entero; negativo = gasto). None si no es número."""
    try:
        return int(float(str(valor).strip()))
    except (TypeError, ValueError):
        return None


def _extraer_movimientos(filas: list[list[Any]]) -> list[tuple[datetime, int, str, str]]:
    """Filas de la pestaña → (fecha en hora CR, monto, categoría, detalle); ignora basura."""
    movimientos: list[tuple[datetime, int, str, str]] = []
    for fila in filas:
        if len(fila) < 2:
            continue
        fecha = _parsear_fecha(fila[0])
        monto = _parsear_monto(fila[1])
        if fecha is None or monto is None or monto == 0:
            continue
        categoria = str(fila[2]).strip() if len(fila) > 2 and fila[2] else "Otros"
        detalle = str(fila[3]).strip() if len(fila) > 3 and fila[3] else categoria
        movimientos.append((fecha, monto, categoria, detalle))
    return movimientos


def _ventanas_semana(ahora: datetime) -> tuple[datetime, datetime, datetime]:
    """Ventana de la semana en curso (últimos 7 días, incluido hoy) y su previa."""
    inicio = (ahora - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
    return inicio, ahora, inicio - timedelta(days=7)


def _ventanas_mes(ahora: datetime) -> tuple[datetime, datetime, datetime, datetime]:
    """
    Ventana del mes en curso (día 1 → hoy) y del mismo tramo del mes pasado
    (día 1 → mismo día, tope al último día del mes anterior).
    """
    inicio = ahora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    ultimo_dia_previo = inicio - timedelta(seconds=1)
    inicio_previo = ultimo_dia_previo.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    dia_tope = min(ahora.day, ultimo_dia_previo.day)
    fin_previo = ahora.replace(year=inicio_previo.year, month=inicio_previo.month, day=dia_tope)
    return inicio, ahora, inicio_previo, fin_previo


def _etiqueta_semana(inicio: datetime, fin: datetime) -> str:
    """P. ej. '12–18 oct' o '28 sep–4 oct' cuando cruza de mes."""
    mes_inicio = _MESES_ABREVIADOS[inicio.month - 1]
    mes_fin = _MESES_ABREVIADOS[fin.month - 1]
    if inicio.month == fin.month:
        return f"{inicio.day}–{fin.day} {mes_fin}"
    return f"{inicio.day} {mes_inicio}–{fin.day} {mes_fin}"


def calcular_resumen(
    filas: list[list[Any]], periodo: Literal["semana", "mes"], ahora: datetime
) -> ResumenCaja:
    """
    Agrega las transacciones del cliente para el período pedido (semana o mes en
    curso, `ahora` en hora de Costa Rica) y calcula la comparación de gastos contra
    el período anterior equivalente. Nunca lanza: filas raras se ignoran.
    """
    movimientos = _extraer_movimientos(filas)

    if periodo == "semana":
        inicio, fin, inicio_previo = _ventanas_semana(ahora)
        fin_previo = inicio
        etiqueta = _etiqueta_semana(inicio, fin)
    else:
        inicio, fin, inicio_previo, fin_previo = _ventanas_mes(ahora)
        etiqueta = f"{_MESES[fin.month - 1]} {fin.year}"

    del_periodo = [mov for mov in movimientos if inicio <= mov[0] <= fin]
    ingresos = sum(monto for _, monto, _, _ in del_periodo if monto > 0)
    gastos = sum(-monto for _, monto, _, _ in del_periodo if monto < 0)
    balance = ingresos - gastos

    gastos_por_categoria: dict[str, int] = {}
    for _, monto, categoria, _ in del_periodo:
        if monto < 0:
            gastos_por_categoria[categoria] = gastos_por_categoria.get(categoria, 0) - monto
    ordenadas = sorted(gastos_por_categoria.items(), key=lambda item: (-item[1], item[0]))
    categorias = [
        CategoriaGasto(
            nombre=nombre,
            monto=monto,
            porcentaje=round(monto * 100 / gastos) if gastos > 0 else 0,
        )
        for nombre, monto in ordenadas[:3]
    ]

    mayor_gasto: tuple[int, str] | None = None
    negativos = [(monto, detalle) for _, monto, _, detalle in del_periodo if monto < 0]
    if negativos:
        monto_mayor, detalle_mayor = min(negativos, key=lambda par: par[0])
        mayor_gasto = (-monto_mayor, detalle_mayor)

    gastos_previos = sum(
        -monto
        for fecha, monto, _, _ in movimientos
        if inicio_previo <= fecha <= fin_previo and monto < 0
    )
    comparacion_pct = (
        round((gastos - gastos_previos) * 100 / gastos_previos) if gastos_previos > 0 else None
    )

    return ResumenCaja(
        periodo=periodo,
        etiqueta=etiqueta,
        ingresos=ingresos,
        gastos=gastos,
        balance=balance,
        n_movimientos=len(del_periodo),
        categorias=categorias,
        mayor_gasto=mayor_gasto,
        comparacion_pct=comparacion_pct,
        tiene_datos=bool(del_periodo),
    )


# ---------------------------------------------------------------
# FORMATEO (texto y caption; WhatsApp renderiza emojis y *negrita*)
# ---------------------------------------------------------------
def formatear_monto(monto: int) -> str:
    """₡ con separador de miles costarricense: 120000 → '₡120.000'."""
    return f"₡{abs(monto):,}".replace(",", ".")


def formatear_con_signo(monto: int) -> str:
    """Balance con signo explícito: +₡35.000 / -₡12.500."""
    return f"{'+' if monto >= 0 else '-'}{formatear_monto(monto)}"


def _nombre_periodo(periodo: Literal["semana", "mes"]) -> str:
    return "la semana" if periodo == "semana" else "lo que va del mes"


def _nombre_periodo_previo(periodo: Literal["semana", "mes"]) -> str:
    return "la semana pasada" if periodo == "semana" else "el mismo tramo del mes pasado"


def _frase_comparacion(resumen: ResumenCaja) -> str | None:
    """Frase de comparación de gastos vs período anterior; None si no hay base."""
    pct = resumen.comparacion_pct
    if pct is None:
        return None
    base = _nombre_periodo_previo(resumen.periodo)
    if pct == 0:
        return f"Gastaste casi lo mismo que {base}."
    if pct > 0:
        return f"Gastaste {pct}% más que {base}."
    return f"Gastaste {abs(pct)}% menos que {base}."


def _titulo_periodo(resumen: ResumenCaja) -> str:
    return "Tu semana" if resumen.periodo == "semana" else "Tu mes"


def texto_sin_movimientos(periodo: Literal["semana", "mes"]) -> str:
    """Respuesta cuando el período pedido aún no tiene movimientos (no se manda tarjeta)."""
    return (
        f"Todavía no registré movimientos en {_nombre_periodo(periodo)}. "
        "Anotá un gasto o ingreso y pedime el resumen de nuevo. 📊"
    )


def formatear_caption(resumen: ResumenCaja) -> str:
    """Pie de la tarjeta (límite de WhatsApp: 1.024 caracteres; acá sobra)."""
    lineas = [
        f"📊 {_titulo_periodo(resumen)} en caja chica · {resumen.etiqueta}",
        "",
        f"Ingresos: {formatear_monto(resumen.ingresos)}",
        f"Gastos: {formatear_monto(resumen.gastos)}",
        f"Balance: {formatear_con_signo(resumen.balance)}",
    ]
    frase = _frase_comparacion(resumen)
    if frase:
        lineas += ["", frase]
    return "\n".join(lineas)


def formatear_texto(resumen: ResumenCaja) -> str:
    """Versión de texto completa del reporte (plan B si la tarjeta no se pudo enviar)."""
    lineas = [
        f"📊 {_titulo_periodo(resumen)} en caja chica · {resumen.etiqueta}",
        "",
        f"Ingresos: {formatear_monto(resumen.ingresos)}",
        f"Gastos: {formatear_monto(resumen.gastos)}",
        f"Balance: {formatear_con_signo(resumen.balance)}",
    ]
    if resumen.categorias:
        lineas += ["", "En qué se fue:"]
        lineas += [
            f"• {categoria.nombre}: {formatear_monto(categoria.monto)} "
            f"({categoria.porcentaje}%)"
            for categoria in resumen.categorias
        ]
    if resumen.mayor_gasto:
        monto, detalle = resumen.mayor_gasto
        lineas += ["", f"Mayor gasto: {formatear_monto(monto)} ({detalle})"]
    frase = _frase_comparacion(resumen)
    if frase:
        lineas.append(frase)
    lineas.append(f"{resumen.n_movimientos} movimientos registrados.")
    return "\n".join(lineas)


# ---------------------------------------------------------------
# TARJETA PNG (Pillow + fuente DejaVu embebida en assets/fonts, licencia libre)
# ---------------------------------------------------------------
_RUTA_FUENTES = Path(__file__).resolve().parent.parent / "assets" / "fonts"
_FUENTE_ESTANDAR = "DejaVuSans.ttf"
_FUENTE_NEGRITA = "DejaVuSans-Bold.ttf"

ANCHO_TARJETA = 1080
_MARGEN = 64

_COLOR_FONDO = "#FFFFFF"
_COLOR_TINTA = "#111827"
_COLOR_GRIS = "#6B7280"
_COLOR_LINEA = "#E5E7EB"
_COLOR_INGRESO = "#0B7A3B"
_COLOR_GASTO = "#B3261E"
_COLOR_BALANCE_POSITIVO = "#0F4C81"
_COLOR_COMPARACION_MAS = "#B45309"
_COLOR_COMPARACION_MENOS = "#0B7A3B"
_COLORES_BARRAS = ("#2563EB", "#D97706", "#059669")


@lru_cache(maxsize=32)
def _fuente(negrita: bool, tamano: int) -> ImageFont.FreeTypeFont:
    """Carga (y cachea) la fuente embebida en el repo, para no depender del sistema."""
    archivo = _FUENTE_NEGRITA if negrita else _FUENTE_ESTANDAR
    return ImageFont.truetype(str(_RUTA_FUENTES / archivo), tamano)


def _recortar(texto: str, limite: int) -> str:
    """Una línea, sin saltos, con elipsis si supera el límite."""
    limpio = " ".join(str(texto).split())
    return limpio if len(limpio) <= limite else limpio[: limite - 1].rstrip() + "…"


def _alto_tarjeta(categorias: int, tiene_mayor: bool, tiene_frase: bool) -> int:
    """Alto total en píxeles; espeja exactamente los avances de `_dibujar_tarjeta`."""
    alto = 56 + 48 + 90 + 32 + 1 + 33  # encabezado + separador
    alto += 3 * 96 + 8 + 33 + 1 + 33  # totales + separador
    if categorias:
        alto += 56 + categorias * 128
    if tiene_mayor:
        alto += 72
    if tiene_frase:
        alto += 60
    alto += 64  # pie
    return alto


def _dibujar_tarjeta(resumen: ResumenCaja, alto: int) -> Image.Image:
    """Dibuja la tarjeta blanca: totales, barras por categoría y pie de contexto."""
    imagen = Image.new("RGB", (ANCHO_TARJETA, alto), _COLOR_FONDO)
    dibujo = ImageDraw.Draw(imagen)
    derecha = ANCHO_TARJETA - _MARGEN

    y = 56
    dibujo.text(
        (_MARGEN, y),
        "CAJA CHICA · RESUMEN",
        font=_fuente(True, 30),
        fill=_COLOR_GRIS,
    )
    y += 48
    dibujo.text(
        (_MARGEN, y),
        f"{_titulo_periodo(resumen)} · {resumen.etiqueta}",
        font=_fuente(True, 62),
        fill=_COLOR_TINTA,
    )
    y += 90
    dibujo.line((_MARGEN, y, derecha, y), fill=_COLOR_LINEA, width=2)
    y += 33

    fuente_etiqueta = _fuente(False, 42)
    fuente_monto = _fuente(True, 54)
    color_balance = _COLOR_BALANCE_POSITIVO if resumen.balance >= 0 else _COLOR_GASTO
    filas_totales = (
        ("Ingresos", formatear_monto(resumen.ingresos), _COLOR_INGRESO),
        ("Gastos", formatear_monto(resumen.gastos), _COLOR_GASTO),
        ("Balance", formatear_con_signo(resumen.balance), color_balance),
    )
    for etiqueta, monto_texto, color in filas_totales:
        dibujo.text((_MARGEN, y), etiqueta, font=fuente_etiqueta, fill=_COLOR_GRIS)
        ancho_texto = dibujo.textlength(monto_texto, font=fuente_monto)
        dibujo.text((derecha - ancho_texto, y - 8), monto_texto, font=fuente_monto, fill=color)
        y += 96

    y += 8
    dibujo.line((_MARGEN, y, derecha, y), fill=_COLOR_LINEA, width=2)
    y += 33

    if resumen.categorias:
        dibujo.text((_MARGEN, y), "EN QUÉ SE FUE", font=_fuente(True, 30), fill=_COLOR_GRIS)
        y += 56
        fuente_categoria = _fuente(True, 42)
        fuente_detalle = _fuente(False, 38)
        ancho_pista = ANCHO_TARJETA - 2 * _MARGEN
        for indice, categoria in enumerate(resumen.categorias):
            color = _COLORES_BARRAS[indice % len(_COLORES_BARRAS)]
            dibujo.text((_MARGEN, y), categoria.nombre, font=fuente_categoria, fill=_COLOR_TINTA)
            detalle = f"{formatear_monto(categoria.monto)} · {categoria.porcentaje}%"
            ancho_detalle = dibujo.textlength(detalle, font=fuente_detalle)
            dibujo.text(
                (derecha - ancho_detalle, y + 4), detalle, font=fuente_detalle, fill=_COLOR_GRIS
            )
            y += 58
            dibujo.rounded_rectangle(
                (_MARGEN, y, _MARGEN + ancho_pista, y + 24),
                radius=12,
                fill=_COLOR_LINEA,
            )
            if categoria.porcentaje > 0:
                ancho_relleno = max(28, round(ancho_pista * categoria.porcentaje / 100))
                dibujo.rounded_rectangle(
                    (_MARGEN, y, _MARGEN + ancho_relleno, y + 24),
                    radius=12,
                    fill=color,
                )
            y += 70

    if resumen.mayor_gasto:
        monto_mayor, detalle_mayor = resumen.mayor_gasto
        dibujo.text(
            (_MARGEN, y),
            f"Mayor gasto: {formatear_monto(monto_mayor)} · {_recortar(detalle_mayor, 28)}",
            font=_fuente(False, 32),
            fill=_COLOR_TINTA,
        )
        y += 72

    frase = _frase_comparacion(resumen)
    if frase:
        color_frase = _COLOR_GRIS
        if resumen.comparacion_pct:
            color_frase = (
                _COLOR_COMPARACION_MAS if resumen.comparacion_pct > 0 else _COLOR_COMPARACION_MENOS
            )
        dibujo.text((_MARGEN, y), frase, font=_fuente(True, 32), fill=color_frase)
        y += 60

    dibujo.text(
        (_MARGEN, y + 20),
        f"{resumen.n_movimientos} movimientos registrados",
        font=_fuente(False, 24),
        fill=_COLOR_GRIS,
    )
    return imagen


def render_reporte_png(resumen: ResumenCaja) -> bytes:
    """
    Genera la tarjeta del reporte como PNG en memoria (bytes) para enviarla por
    WhatsApp. Puede lanzar excepción ante un problema de dibujo: el llamador decide
    (el pipeline degrada a texto, nunca pierde el dato).
    """
    frase = _frase_comparacion(resumen)
    alto = _alto_tarjeta(
        len(resumen.categorias), resumen.mayor_gasto is not None, frase is not None
    )
    imagen = _dibujar_tarjeta(resumen, alto)
    buffer = BytesIO()
    imagen.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
