"""
Tests del modelo canónico mínimo (A02, `docs/producto/modelo-datos.md`).

Son pruebas puras: no tocan Google Sheets ni la red. Cubren el contrato de la fila
canónica de 13 columnas, la conversión de filas históricas, el monto con signo y la
migración con conciliación de conteos y totales.
"""

from services.modelo_service import (
    ESTADOS_ACTIVOS,
    LEGACY_TRANSACTION_HEADERS,
    TRANSACTION_HEADERS,
    es_fila_canonica,
    es_fila_vacia,
    fila_a_movimiento,
    migrar_filas_legacy,
    monto_con_signo,
    movimiento_a_fila,
    tipo_encabezado,
)

TELEFONO = "50688888888"


def _movimiento(**cambios: object) -> dict[str, object]:
    base: dict[str, object] = {
        "fecha_movimiento": "2026-11-01 10:00:00",
        "monto_centimos": 450000,
        "categoria": "Alimentación",
        "detalle": "Almuerzo",
        "telefono": TELEFONO,
        "movimiento_id": "mov-1",
        "tipo_movimiento": "gasto",
        "moneda": "CRC",
        "contexto_tipo": "personal",
        "estado": "confirmado",
        "version": 1,
        "fecha_registro": "2026-11-01 10:00:05",
        "origen": "chat",
    }
    base.update(cambios)
    return base


def test_encabezado_canonico_tiene_trece_columnas() -> None:
    assert len(TRANSACTION_HEADERS) == 13
    assert TRANSACTION_HEADERS[1] == "monto_centimos"
    assert TRANSACTION_HEADERS[5] == "movimiento_id"
    assert TRANSACTION_HEADERS[9] == "estado"


def test_tipo_encabezado_detecta_canonico_legacy_y_desconocido() -> None:
    assert tipo_encabezado(TRANSACTION_HEADERS) == "canonico"
    assert tipo_encabezado(LEGACY_TRANSACTION_HEADERS) == "legacy"
    assert tipo_encabezado(["cualquier", "cosa"]) == "desconocido"
    assert tipo_encabezado([]) == "desconocido"


def test_es_fila_vacia_ignora_espacios_y_none() -> None:
    assert es_fila_vacia([])
    assert es_fila_vacia(["", None, "   "])
    assert not es_fila_vacia(["", 0])


def test_fila_legacy_gasto_se_convierte_a_centimos_positivos() -> None:
    movimiento = fila_a_movimiento(
        ["2026-08-20 19:29:13", "-3000", "Alimentación", "Tres perros", TELEFONO]
    )

    assert movimiento["monto_centimos"] == 300000
    assert movimiento["tipo_movimiento"] == "gasto"
    assert movimiento["monto"] == -3000
    assert movimiento["estado"] == "confirmado"
    assert movimiento["moneda"] == "CRC"
    assert movimiento["contexto_tipo"] == "personal"
    assert movimiento["movimiento_id"] == ""
    assert movimiento["origen"] == "importacion"


def test_fila_legacy_ingreso_se_convierte_a_centimos_positivos() -> None:
    movimiento = fila_a_movimiento(["2026-08-20 19:30:00", "2500", "Ventas", "camisetas", TELEFONO])

    assert movimiento["monto_centimos"] == 250000
    assert movimiento["tipo_movimiento"] == "ingreso"
    assert movimiento["monto"] == 2500


def test_fila_canonica_respeta_tipo_y_estado() -> None:
    fila = [
        "2026-11-01 10:00:00",
        "450000",
        "Alimentación",
        "Almuerzo",
        TELEFONO,
        "mov-1",
        "gasto",
        "CRC",
        "personal",
        "anulado",
        "3",
        "2026-11-01 10:00:05",
        "chat",
    ]

    movimiento = fila_a_movimiento(fila)

    assert movimiento["monto_centimos"] == 450000
    assert movimiento["tipo_movimiento"] == "gasto"
    assert movimiento["estado"] == "anulado"
    assert movimiento["version"] == 3
    assert movimiento["movimiento_id"] == "mov-1"
    assert movimiento["monto"] == -4500


def test_es_fila_canonica_tolera_celdas_finales_recortadas_por_sheets() -> None:
    fila = ["2026-11-01 10:00:00", "450000", "Alimentación", "Almuerzo", TELEFONO, "mov-1", "gasto"]
    assert len(fila) < len(TRANSACTION_HEADERS)
    assert es_fila_canonica(fila)

    # Una fila histórica de 5 columnas NO se confunde con una canónica.
    assert not es_fila_canonica(LEGACY_TRANSACTION_HEADERS)


def test_ida_y_vuelta_canonica_conserva_identidad_y_estado() -> None:
    original = _movimiento()

    fila = movimiento_a_fila(original)
    vuelta = fila_a_movimiento(fila)

    assert fila[1] == 450000
    assert vuelta["movimiento_id"] == "mov-1"
    assert vuelta["monto_centimos"] == 450000
    assert vuelta["tipo_movimiento"] == "gasto"
    assert vuelta["estado"] == "confirmado"
    assert vuelta["version"] == 1
    assert vuelta["fecha_registro"] == "2026-11-01 10:00:05"
    assert vuelta["origen"] == "chat"
    assert vuelta["monto"] == -4500


def test_ida_y_vuelta_de_ingreso_es_positiva() -> None:
    original = _movimiento(monto_centimos=250000, tipo_movimiento="ingreso", categoria="Ventas")
    vuelta = fila_a_movimiento(movimiento_a_fila(original))

    assert vuelta["monto"] == 2500
    assert vuelta["tipo_movimiento"] == "ingreso"


def test_monto_con_signo_acepta_fila_legacy_y_canonica() -> None:
    assert monto_con_signo(["2026-08-20 19:29:13", "-3000", "x", "y", TELEFONO]) == -3000
    assert monto_con_signo(["2026-08-20 19:30:00", "2500", "x", "y", TELEFONO]) == 2500
    assert monto_con_signo(movimiento_a_fila(_movimiento())) == -4500
    assert monto_con_signo(movimiento_a_fila(_movimiento(tipo_movimiento="ingreso"))) == 4500


def test_movimiento_a_fila_sin_generar_id_no_inventa_identidad() -> None:
    fila = movimiento_a_fila(_movimiento(movimiento_id=""), generar_id=False)
    assert fila[5] == ""

    fila_con_id = movimiento_a_fila(_movimiento(movimiento_id=""))
    assert fila_con_id[5]


def test_migracion_legacy_convierte_todo_y_concilia() -> None:
    filas = [
        LEGACY_TRANSACTION_HEADERS,
        ["2026-08-20 19:29:13", "-3000", "Alimentación", "Tres perros", TELEFONO],
        ["2026-08-20 19:30:00", "2500", "Ventas", "camisetas", TELEFONO],
        ["", "", "", "", ""],
    ]

    canonicas, reporte = migrar_filas_legacy(
        filas[1:], TELEFONO, fecha_registro="2026-11-08 00:00:00"
    )

    assert len(canonicas) == 2
    assert all(len(fila) == 13 for fila in canonicas)
    assert all(fila[5] for fila in canonicas)  # cada fila obtiene ID
    assert canonicas[0][1] == 300000
    assert canonicas[0][6] == "gasto"
    assert canonicas[1][1] == 250000
    assert canonicas[1][6] == "ingreso"
    assert canonicas[0][9] == "confirmado"
    assert canonicas[0][11] == "2026-11-08 00:00:00"
    assert canonicas[0][12] == "importacion"
    assert reporte["filas_antes"] == 2
    assert reporte["filas_despues"] == 2
    assert reporte["gastos_antes_centimos"] == 300000
    assert reporte["gastos_despues_centimos"] == 300000
    assert reporte["ingresos_antes_centimos"] == 250000
    assert reporte["ingresos_despues_centimos"] == 250000
    assert reporte["cuadra"] is True


def test_migracion_es_idempotente_sobre_filas_canonicas() -> None:
    filas = [
        ["2026-08-20 19:29:13", "-3000", "Alimentación", "Tres perros", TELEFONO],
        ["2026-08-20 19:30:00", "2500", "Ventas", "camisetas", TELEFONO],
    ]
    primera, reporte_1 = migrar_filas_legacy(filas, TELEFONO, fecha_registro="2026-11-08 00:00:00")
    ids_1 = [fila[5] for fila in primera]

    segunda, reporte_2 = migrar_filas_legacy(
        primera, TELEFONO, fecha_registro="2026-11-09 00:00:00"
    )

    assert [fila[5] for fila in segunda] == ids_1  # los IDs no se regeneran
    assert reporte_1["cuadra"] is True
    assert reporte_2["cuadra"] is True
    assert reporte_1["gastos_despues_centimos"] == reporte_2["gastos_despues_centimos"]
    assert reporte_1["ingresos_despues_centimos"] == reporte_2["ingresos_despues_centimos"]


def test_migracion_marca_pendiente_la_fila_sin_monto_valido() -> None:
    filas = [
        ["2026-08-20 19:29:13", "0", "Alimentación", "sin monto", TELEFONO],
        ["", "-3000", "Alimentación", "sin fecha", TELEFONO],
    ]

    canonicas, reporte = migrar_filas_legacy(filas, TELEFONO, fecha_registro="2026-11-08 00:00:00")

    assert [fila[9] for fila in canonicas] == ["pendiente", "pendiente"]
    assert reporte["cuadra"] is True


def test_migracion_conserva_ids_unicos_aunque_la_hoja_los_repita() -> None:
    fila_repetida = movimiento_a_fila(_movimiento(movimiento_id="mov-1"))
    canonicas, reporte = migrar_filas_legacy(
        [fila_repetida, fila_repetida], TELEFONO, fecha_registro="2026-11-08 00:00:00"
    )

    assert canonicas[0][5] == "mov-1"
    assert canonicas[1][5] != "mov-1"
    assert reporte["cuadra"] is True


def test_estados_activos_no_incluyen_anulado_ni_pendiente() -> None:
    assert set(ESTADOS_ACTIVOS) == {"confirmado", "corregido"}
