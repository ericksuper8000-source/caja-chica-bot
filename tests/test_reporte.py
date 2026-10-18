"""
Tests del Sprint de Valor Visible — Reportes de caja por chat (S4/S4b V1):
detección determinista del pedido, agregación semana/mes, formato y tarjeta PNG,
más el punto de inserción en el pipeline (después del gate, antes del dedupe/GPT).
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from services.reporte_service import (
    _RUTA_FUENTES,
    ZONA_CR,
    calcular_resumen,
    detectar_solicitud_reporte,
    formatear_caption,
    formatear_con_signo,
    formatear_monto,
    formatear_texto,
    render_reporte_png,
    texto_sin_movimientos,
)
from services.suscripcion_service import mensaje_suscripcion_no_activa

AHORA = datetime(2026, 10, 18, 15, 0, tzinfo=ZONA_CR)


def _fila(momento_cr: datetime, monto: int, categoria: str, detalle: str) -> list[str]:
    """Fila tal como la devuelve gspread: fecha UTC en texto, monto en texto."""
    fecha_utc = momento_cr.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")
    return [fecha_utc, str(monto), categoria, detalle, "50688888888"]


# Rows fijas para la semana del 12–18 oct 2026 (AHORA = dom 18 oct 15:00 CR).
FILAS_SEMANA = [
    _fila(datetime(2026, 10, 1, 10, 0, tzinfo=ZONA_CR), -99999, "Varios", "viejo"),
    _fila(datetime(2026, 10, 6, 10, 0, tzinfo=ZONA_CR), -20000, "Alimentación", "súper"),
    _fila(datetime(2026, 10, 14, 10, 0, tzinfo=ZONA_CR), -10000, "Alimentación", "súper"),
    _fila(datetime(2026, 10, 15, 12, 0, tzinfo=ZONA_CR), -6000, "Transporte", "gasolina"),
    _fila(datetime(2026, 10, 16, 13, 0, tzinfo=ZONA_CR), -4000, "Alimentación", "almuerzo"),
    _fila(datetime(2026, 10, 17, 9, 0, tzinfo=ZONA_CR), 30000, "Ventas", "venta del día"),
    _fila(datetime(2026, 10, 18, 8, 0, tzinfo=ZONA_CR), -5000, "Alimentación", "feria"),
]


# ==========================================
# DETECCIÓN DEL PEDIDO ("resumen", "reporte", "balance", "cómo va...")
# ==========================================
@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("resumen", "semana"),
        ("balance", "semana"),
        ("dame el resumen", "semana"),
        ("reporte de ventas", "semana"),
        ("resumen de la semana", "semana"),
        ("cómo va mi semana?", "semana"),
        ("RESUMEN SEMANAL", "semana"),
        ("reporte del mes", "mes"),
        ("cómo voy este mes", "mes"),
        ("¿Cómo va el mes?", "mes"),
        ("qué tal va el mes", "mes"),
    ],
)
def test_detectar_pedido_positivo(texto: str, esperado: str) -> None:
    assert detectar_solicitud_reporte(texto) == esperado


@pytest.mark.parametrize(
    "texto",
    [
        "",
        "hola, ¿cómo estás?",
        "gasté 5000 en el almuerzo",
        "resumen del súper: 10000",
        "pagué el resumen de la tarjeta",
        "anotá un pago de 5000",
        "resumen de la tarjeta",
        "resumen de la semana pasada",
        "reporte del mes anterior",
        "resumen de octubre",
        "resumen del préstamo",
        "exporta mis datos",
        "cómo va el negocio de mi vecino que vende empanadas y chuletas los domingos",
        "un resumen rápido de lo que compré el otro día en el supermercado con mi tarjeta",
    ],
)
def test_detectar_pedido_negativo(texto: str) -> None:
    """Ante la duda NO se detecta: un reporte por error confunde; un gasto no
    registrado es una pérdida. Todas estas frases deben caer al flujo normal."""
    assert detectar_solicitud_reporte(texto) is None


# ==========================================
# AGREGACIÓN (semana y mes, con comparación vs período anterior)
# ==========================================
def test_resumen_semana_cifras_y_comparacion() -> None:
    resumen = calcular_resumen(FILAS_SEMANA, "semana", AHORA)

    assert resumen.etiqueta == "12–18 oct"
    assert resumen.ingresos == 30000
    assert resumen.gastos == 25000
    assert resumen.balance == 5000
    assert resumen.n_movimientos == 5
    assert resumen.tiene_datos is True
    assert [(c.nombre, c.monto, c.porcentaje) for c in resumen.categorias] == [
        ("Alimentación", 19000, 76),
        ("Transporte", 6000, 24),
    ]
    assert resumen.mayor_gasto == (10000, "súper")
    assert resumen.comparacion_pct == 25  # 25.000 vs 20.000 de la semana previa


def test_resumen_mes_usa_mismo_tramo_del_mes_pasado() -> None:
    """Del 1 al 18 de octubre vs del 1 al 18 de setiembre (no setiembre completo)."""
    filas = [
        _fila(datetime(2026, 9, 18, 10, 0, tzinfo=ZONA_CR), -15000, "Alimentación", "súper"),
        _fila(datetime(2026, 9, 19, 10, 0, tzinfo=ZONA_CR), -5000, "Varios", "fuera del tramo"),
        _fila(datetime(2026, 9, 20, 10, 0, tzinfo=ZONA_CR), -5000, "Varios", "fuera del tramo"),
        _fila(datetime(2026, 10, 1, 10, 0, tzinfo=ZONA_CR), -1000, "Transporte", "bus"),
        _fila(datetime(2026, 10, 18, 10, 0, tzinfo=ZONA_CR), -2000, "Alimentación", "feria"),
    ]

    resumen = calcular_resumen(filas, "mes", AHORA)

    assert resumen.etiqueta == "octubre 2026"
    assert resumen.gastos == 3000
    assert resumen.comparacion_pct == -80  # 3.000 vs 15.000 del mismo tramo
    assert resumen.tiene_datos is True


def test_resumen_sin_movimientos_ni_comparacion() -> None:
    resumen = calcular_resumen([], "semana", AHORA)

    assert resumen.tiene_datos is False
    assert resumen.ingresos == 0
    assert resumen.gastos == 0
    assert resumen.categorias == []
    assert resumen.mayor_gasto is None
    assert resumen.comparacion_pct is None


def test_resumen_ignora_filas_basura() -> None:
    """Filas cortas, fechas inválidas o montos no numéricos no rompen el cálculo."""
    filas = [
        ["basura"],
        ["no es fecha", "tampoco monto", "X", "Y", "506"],
        _fila(datetime(2026, 10, 18, 8, 0, tzinfo=ZONA_CR), -1234, "", ""),
    ]

    resumen = calcular_resumen(filas, "semana", AHORA)

    assert resumen.gastos == 1234
    assert resumen.categorias[0].nombre == "Otros"
    assert resumen.mayor_gasto == (1234, "Otros")


# ==========================================
# FORMATO
# ==========================================
def test_formatear_monto_con_separador_crc() -> None:
    assert formatear_monto(120000) == "₡120.000"
    assert formatear_monto(0) == "₡0"
    assert formatear_con_signo(35000) == "+₡35.000"
    assert formatear_con_signo(-12500) == "-₡12.500"


def test_caption_y_texto_incluyen_cifras_clave() -> None:
    resumen = calcular_resumen(FILAS_SEMANA, "semana", AHORA)

    caption = formatear_caption(resumen)
    assert "📊 Tu semana" in caption
    assert "₡25.000" in caption
    assert "25% más que la semana pasada" in caption
    assert len(caption) <= 1024

    texto = formatear_texto(resumen)
    assert "En qué se fue:" in texto
    assert "Alimentación: ₡19.000 (76%)" in texto
    assert "Mayor gasto: ₡10.000 (súper)" in texto
    assert "5 movimientos registrados." in texto


def test_caption_se_mantiene_bajo_el_limite_con_montos_enormes() -> None:
    filas = [
        _fila(datetime(2026, 10, 18, 8, 0, tzinfo=ZONA_CR), -999_999_999, "Compras", "bodega")
        for _ in range(3)
    ]
    resumen = calcular_resumen(filas, "semana", AHORA)

    assert len(formatear_caption(resumen)) <= 1024


def test_texto_sin_movimientos_menciona_el_periodo() -> None:
    assert "no registré movimientos en la semana" in texto_sin_movimientos("semana")
    assert "no registré movimientos en lo que va del mes" in texto_sin_movimientos("mes")


# ==========================================
# TARJETA PNG
# ==========================================
def test_fuentes_embebidas_existen() -> None:
    """Si falta la fuente, la tarjeta no se puede dibujar en el contenedor."""
    assert (Path(_RUTA_FUENTES) / "DejaVuSans.ttf").is_file()
    assert (Path(_RUTA_FUENTES) / "DejaVuSans-Bold.ttf").is_file()


def test_render_reporte_png_es_png() -> None:
    resumen = calcular_resumen(FILAS_SEMANA, "semana", AHORA)

    png = render_reporte_png(resumen)

    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 5000


@pytest.mark.parametrize("periodo", ["semana", "mes"])
def test_render_reporte_png_sin_gastos_ni_comparacion_no_falla(periodo: str) -> None:
    """Solo ingresos (sin barras) y período vacío (sin nada): la tarjeta no revienta."""
    solo_ingreso = [_fila(datetime(2026, 10, 18, 8, 0, tzinfo=ZONA_CR), 1000, "Ventas", "x")]
    for filas in (solo_ingreso, []):
        png = render_reporte_png(calcular_resumen(filas, periodo, AHORA))
        assert png[:8] == b"\x89PNG\r\n\x1a\n"


# ==========================================
# PIPELINE: inserción después del gate, antes del dedupe/GPT
# ==========================================
def _consentimiento_aceptado() -> dict[str, str]:
    from services.politica_service import POLITICA_VERSION

    return {"estado": "aceptado", "version_politica": POLITICA_VERSION}


def _filas_recientes() -> list[list[str]]:
    ahora = datetime.now(ZONA_CR)
    return [
        _fila(ahora - timedelta(days=1), -2500, "Alimentación", "almuerzo"),
        _fila(ahora - timedelta(days=2), 10000, "Ventas", "venta"),
    ]


@pytest.mark.anyio
async def test_pipeline_reporte_envia_tarjeta_sin_gpt() -> None:
    with (
        patch("workers.tasks.obtener_consentimiento", return_value=_consentimiento_aceptado()),
        patch("workers.tasks.obtener_transacciones_cliente", return_value=_filas_recientes()),
        patch("workers.tasks.enviar_imagen_whatsapp", return_value=True) as mock_imagen,
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
        patch("workers.tasks.parse_financial_text") as mock_parse,
    ):
        from workers.tasks import _procesar_pipeline

        await _procesar_pipeline(None, "50688888888", texto_entrante="resumen de la semana")

    mock_parse.assert_not_called()
    mock_imagen.assert_awaited_once()
    assert mock_imagen.call_args.kwargs["to_phone"] == "50688888888"
    assert mock_imagen.call_args.kwargs["imagen"][:8] == b"\x89PNG\r\n\x1a\n"
    mock_whatsapp.assert_not_awaited()


@pytest.mark.anyio
async def test_pipeline_reporte_cae_a_texto_si_la_tarjeta_falla() -> None:
    """Rompe-si: si la imagen no sale, el dato llega igual (plan B en texto)."""
    with (
        patch("workers.tasks.obtener_consentimiento", return_value=_consentimiento_aceptado()),
        patch("workers.tasks.obtener_transacciones_cliente", return_value=_filas_recientes()),
        patch("workers.tasks.enviar_imagen_whatsapp", return_value=False),
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
        patch("workers.tasks.parse_financial_text") as mock_parse,
    ):
        from workers.tasks import _procesar_pipeline

        await _procesar_pipeline(None, "50688888888", texto_entrante="reporte del mes")

    mock_parse.assert_not_called()
    mensaje = mock_whatsapp.call_args.kwargs["mensaje"]
    assert "Tu mes en caja chica" in mensaje
    assert "Balance:" in mensaje


@pytest.mark.anyio
async def test_pipeline_reporte_sin_movimientos_no_envia_tarjeta() -> None:
    with (
        patch("workers.tasks.obtener_consentimiento", return_value=_consentimiento_aceptado()),
        patch("workers.tasks.obtener_transacciones_cliente", return_value=[]),
        patch("workers.tasks.enviar_imagen_whatsapp") as mock_imagen,
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
        patch("workers.tasks.parse_financial_text") as mock_parse,
    ):
        from workers.tasks import _procesar_pipeline

        await _procesar_pipeline(None, "50688888888", texto_entrante="resumen")

    mock_parse.assert_not_called()
    mock_imagen.assert_not_awaited()
    assert "no registré movimientos" in mock_whatsapp.call_args.kwargs["mensaje"]


@pytest.mark.anyio
async def test_pipeline_frase_con_tarjeta_no_dispara_reporte() -> None:
    """'pagué el resumen de la tarjeta' es un gasto potencial: va al flujo normal."""
    with (
        patch("workers.tasks.obtener_consentimiento", return_value=_consentimiento_aceptado()),
        patch("workers.tasks.enviar_imagen_whatsapp") as mock_imagen,
        patch("workers.tasks.obtener_transacciones_cliente") as mock_filas,
        patch("workers.tasks.parse_financial_text", return_value=None) as mock_parse,
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
    ):
        from workers.tasks import _procesar_pipeline

        await _procesar_pipeline(
            None, "50688888888", texto_entrante="pagué el resumen de la tarjeta"
        )

    mock_imagen.assert_not_awaited()
    mock_filas.assert_not_called()
    mock_parse.assert_called_once()
    mock_whatsapp.assert_awaited_once()


@pytest.mark.anyio
async def test_pipeline_reporte_no_pasa_sin_suscripcion() -> None:
    """El gate comercial va primero: sin acceso no hay reporte (ni Sheets ni tarjeta)."""
    with (
        patch("workers.tasks.obtener_consentimiento", return_value=_consentimiento_aceptado()),
        patch("workers.tasks.obtener_suscripcion", return_value={"estado": "vencido"}),
        patch("workers.tasks.obtener_transacciones_cliente") as mock_filas,
        patch("workers.tasks.enviar_imagen_whatsapp") as mock_imagen,
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
    ):
        from workers.tasks import _procesar_pipeline

        await _procesar_pipeline(None, "50688888888", texto_entrante="cómo va el mes")

    mock_filas.assert_not_called()
    mock_imagen.assert_not_awaited()
    mock_whatsapp.assert_awaited_once_with(
        to_phone="50688888888",
        mensaje=mensaje_suscripcion_no_activa({"estado": "vencido"}),
    )
