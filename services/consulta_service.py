import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from services.sheets_service import obtener_transacciones_cliente

MESES_ES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}


@dataclass
class ConsultaCategoria:
    categoria: str
    periodo: Literal["semana", "mes", "mes_pasado", "semana_pasada", "mes_especifico"]
    mes_especifico: int | None = None


@dataclass
class ConsultaMayor:
    periodo: Literal["semana", "mes", "mes_pasado", "semana_pasada", "todo"]
    mes_especifico: int | None = None


@dataclass
class ConsultaComparacion:
    periodo_base: Literal["mes", "semana"]


@dataclass
class ResultadoCategoria:
    total: int
    count: int
    categoria: str
    periodo_desc: str


@dataclass
class ResultadoMayor:
    monto: int
    detalle: str
    fecha: str
    periodo_desc: str


@dataclass
class ResultadoComparacion:
    actual_total: int
    anterior_total: int
    diferencia: int
    pct_cambio: float
    periodo_desc: str


def _limpiar_texto(texto: str) -> str:
    texto = texto.lower().strip()
    texto = re.sub(r"[¿?¡!.,;:()\"'«»]", "", texto)
    return texto


def _normalizar_categoria(cat: str) -> str:
    cat = cat.lower().strip()
    cat = (
        cat.replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
    )
    return cat


def _coincide_categoria(cat_hoja: str, cat_buscada: str) -> bool:
    c1 = _normalizar_categoria(cat_hoja)
    c2 = _normalizar_categoria(cat_buscada)
    return c1 == c2 or c2 in c1 or c1 in c2


async def _categorias_reales(sender_phone: str) -> set[str]:
    """Lee las categorías que el usuario YA usa en sus gastos (desde Sheets)."""
    rows = await obtener_transacciones_cliente(sender_phone)
    return {_normalizar_categoria(r[2]) for r in rows if len(r) > 2 and r[2].strip()}


async def detectar_consulta(
    sender_phone: str, texto: str
) -> ConsultaCategoria | ConsultaMayor | ConsultaComparacion | None:
    t = _limpiar_texto(texto)
    if not t:
        return None

    palabras = t.split()
    if len(palabras) > 15:
        return None

    # Guardas: si tiene monto o "tarjeta" -> no es consulta (flujo transaccional)
    if re.search(r"\d", t):
        return None
    if "tarjeta" in t:
        return None

    # Categorías reales del usuario
    cats = await _categorias_reales(sender_phone)

    # 1. Consultas de comparación mes a mes
    if any(
        kw in t
        for kw in [
            "comparacion",
            "comparación",
            "comparar",
            "vs",
            "versus",
            "como voy",
            "cómo voy",
        ]
    ):
        if "semana" in t:
            return ConsultaComparacion(periodo_base="semana")
        return ConsultaComparacion(periodo_base="mes")

    # 2. Gasto mayor
    if any(
        kw in t
        for kw in [
            "mayor gasto",
            "mas grande",
            "más grande",
            "maximo",
            "máximo",
            "top gasto",
            "gasto mayor",
        ]
    ):
        from typing import Literal

        periodo: Literal["semana", "mes", "mes_pasado", "semana_pasada", "todo"] = "todo"
        if "semana" in t:
            if "pasada" in t or "anterior" in t:
                periodo = "semana_pasada"
            else:
                periodo = "semana"
        elif "mes" in t:
            if "pasado" in t or "anterior" in t:
                periodo = "mes_pasado"
            else:
                periodo = "mes"
        return ConsultaMayor(periodo=periodo)

    # 3. Consulta por categoría + período (usa SUS categorías reales)
    for mes_nombre, mes_num in MESES_ES.items():
        if mes_nombre in t:
            categoria = None
            for cat in cats:
                if cat in t:
                    categoria = cat
                    break
            if categoria:
                return ConsultaCategoria(
                    categoria=categoria, periodo="mes_especifico", mes_especifico=mes_num
                )

    categoria = None
    for cat in cats:
        if cat in t:
            categoria = cat
            break

    if categoria:
        if "semana" in t:
            if "pasada" in t or "anterior" in t:
                return ConsultaCategoria(categoria=categoria, periodo="semana_pasada")
            return ConsultaCategoria(categoria=categoria, periodo="semana")
        if "mes" in t:
            if "pasado" in t or "anterior" in t:
                return ConsultaCategoria(categoria=categoria, periodo="mes_pasado")
            return ConsultaCategoria(categoria=categoria, periodo="mes")

    # Guardas verbos de pago (solo si la frase EMPIEZA con verbo: "gaste 5000...")
    verbos_pago = {"pague", "pagué", "pago", "gaste", "gasté", "compre", "compré", "pagu"}
    if any(t.startswith(v) for v in verbos_pago):
        return None

    return None


def _parse_fecha(fecha_str: str) -> datetime | None:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(fecha_str.strip(), fmt)
        except ValueError:
            pass
    return None


def _filtrar_por_periodo(
    rows: list[list[Any]], periodo: str, mes_especifico: int | None = None
) -> list[list[Any]]:
    hoy = datetime.now()
    filtradas = []

    for row in rows:
        if len(row) < 3:
            continue
        fecha_str = row[0]
        dt = _parse_fecha(fecha_str)
        if not dt:
            continue

        if periodo == "semana":
            inicio = hoy - timedelta(days=hoy.weekday())
            inicio = inicio.replace(hour=0, minute=0, second=0, microsecond=0)
            if dt >= inicio:
                filtradas.append(row)
        elif periodo == "mes":
            inicio = hoy.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            if dt >= inicio:
                filtradas.append(row)
        elif periodo == "semana_pasada":
            fin = hoy - timedelta(days=hoy.weekday())
            fin = fin.replace(hour=0, minute=0, second=0, microsecond=0)
            inicio = fin - timedelta(days=7)
            if inicio <= dt < fin:
                filtradas.append(row)
        elif periodo == "mes_pasado":
            inicio_mes_actual = hoy.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            fin = inicio_mes_actual
            if fin.month == 1:
                inicio = fin.replace(year=fin.year - 1, month=12)
            else:
                inicio = fin.replace(month=fin.month - 1)
            if inicio <= dt < fin:
                filtradas.append(row)
        elif periodo == "mes_especifico" and mes_especifico:
            if dt.month == mes_especifico and dt.year == hoy.year:
                filtradas.append(row)
        elif periodo == "todo":
            filtradas.append(row)

    return filtradas


async def calcular_consulta_categoria(
    sender_phone: str, consulta: ConsultaCategoria
) -> ResultadoCategoria:
    rows = await obtener_transacciones_cliente(sender_phone)
    if not rows:
        return ResultadoCategoria(total=0, count=0, categoria=consulta.categoria, periodo_desc="")

    filas = _filtrar_por_periodo(rows, consulta.periodo, consulta.mes_especifico)

    total = 0
    count = 0
    for row in filas:
        if len(row) < 3:
            continue
        if not _coincide_categoria(row[2], consulta.categoria):
            continue
        try:
            monto = int(row[1])
        except (ValueError, TypeError):
            continue
        if monto < 0:
            total += abs(monto)
            count += 1

    if consulta.periodo == "semana":
        periodo_desc = "esta semana"
    elif consulta.periodo == "mes":
        periodo_desc = "este mes"
    elif consulta.periodo == "semana_pasada":
        periodo_desc = "la semana pasada"
    elif consulta.periodo == "mes_pasado":
        periodo_desc = "el mes pasado"
    elif consulta.periodo == "mes_especifico":
        nombres = {v: k for k, v in MESES_ES.items()}
        mes = consulta.mes_especifico
        if mes is not None:
            periodo_desc = nombres.get(mes, str(mes))
        else:
            periodo_desc = ""
    else:
        periodo_desc = ""

    return ResultadoCategoria(
        total=total, count=count, categoria=consulta.categoria, periodo_desc=periodo_desc
    )


async def calcular_consulta_mayor(
    sender_phone: str, consulta: ConsultaMayor
) -> ResultadoMayor | None:
    rows = await obtener_transacciones_cliente(sender_phone)
    if not rows:
        return None

    filas = _filtrar_por_periodo(rows, consulta.periodo, consulta.mes_especifico)

    mayor = None
    mayor_detalle = ""
    mayor_fecha = ""
    for row in filas:
        if len(row) < 4:
            continue
        try:
            monto = int(row[1])
        except (ValueError, TypeError):
            continue
        if monto >= 0:
            continue
        monto_abs = abs(monto)
        if mayor is None or monto_abs > mayor:
            mayor = monto_abs
            mayor_detalle = row[3]
            mayor_fecha = row[0]

    if mayor is None:
        return None

    if consulta.periodo == "semana":
        periodo_desc = "esta semana"
    elif consulta.periodo == "mes":
        periodo_desc = "este mes"
    elif consulta.periodo == "semana_pasada":
        periodo_desc = "la semana pasada"
    elif consulta.periodo == "mes_pasado":
        periodo_desc = "el mes pasado"
    else:
        periodo_desc = "todo el historial"

    return ResultadoMayor(
        monto=mayor, detalle=mayor_detalle, fecha=mayor_fecha, periodo_desc=periodo_desc
    )


async def calcular_consulta_comparacion(
    sender_phone: str, consulta: ConsultaComparacion
) -> ResultadoComparacion | None:
    rows = await obtener_transacciones_cliente(sender_phone)
    if not rows:
        return None

    hoy = datetime.now()
    if consulta.periodo_base == "mes":
        inicio_actual = hoy.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if inicio_actual.month == 1:
            inicio_anterior = inicio_actual.replace(year=inicio_actual.year - 1, month=12)
        else:
            inicio_anterior = inicio_actual.replace(month=inicio_actual.month - 1)
        fin_anterior = inicio_actual
        periodo_desc = "mes actual vs anterior"
    else:
        inicio_actual = hoy - timedelta(days=hoy.weekday())
        inicio_actual = inicio_actual.replace(hour=0, minute=0, second=0, microsecond=0)
        inicio_anterior = inicio_actual - timedelta(days=7)
        fin_anterior = inicio_actual
        periodo_desc = "esta semana vs anterior"

    actual = 0
    anterior = 0

    for row in rows:
        if len(row) < 2:
            continue
        dt = _parse_fecha(row[0])
        if not dt:
            continue
        try:
            monto = int(row[1])
        except (ValueError, TypeError):
            continue

        if inicio_anterior <= dt < fin_anterior + (fin_anterior - inicio_anterior):
            if monto < 0:
                if dt >= inicio_actual:
                    actual += abs(monto)
                elif dt >= inicio_anterior:
                    anterior += abs(monto)

    if anterior == 0:
        pct = 0.0
    else:
        pct = round((actual - anterior) * 100.0 / anterior, 1)

    return ResultadoComparacion(
        actual_total=actual,
        anterior_total=anterior,
        diferencia=actual - anterior,
        pct_cambio=pct,
        periodo_desc=periodo_desc,
    )


def formatear_resultado_categoria(res: ResultadoCategoria) -> str:
    if res.total == 0:
        return f"No hay gastos en {res.categoria} {res.periodo_desc}."
    return (
        f"En {res.periodo_desc} gastaste ₡{res.total:,} en {res.categoria} "
        f"({res.count} movimientos)."
    )


def formatear_resultado_mayor(res: ResultadoMayor | None) -> str:
    if not res:
        return "No hay gastos en ese período."
    return f"Tu mayor gasto {res.periodo_desc} fue ₡{res.monto:,} ({res.detalle}) el {res.fecha}."


def formatear_resultado_comparacion(res: ResultadoComparacion | None) -> str:
    if not res:
        return "No hay datos para comparar."
    signo = "+" if res.diferencia > 0 else ""
    return (
        f"Gastaste ₡{res.actual_total:,} {res.periodo_desc.split(' vs ')[0]} "
        f"vs ₡{res.anterior_total:,} anterior ({signo}{res.pct_cambio}%)."
    )
