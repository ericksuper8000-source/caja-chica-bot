"""
Tests de corrección, borrado, deshacer e historial (A08).

Cubren las reglas ratificadas D23 (ventana de deshacer), D24 (confirmación explícita
del borrado) y D25 (auto-reparación con plan vencido), además del formato de la
confirmación completa y del aislamiento del historial por teléfono.

La primera parte prueba el servicio puro `a08_service` sin red. La segunda ejercita el
pipeline real (`workers.tasks`) con dobles de Sheets/WhatsApp y el Redis en memoria de
`conftest.py`, de modo que cada test verifica el mensaje que recibiría el usuario.
"""

from contextlib import ExitStack
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from services.a08_service import (
    MAX_HISTORIAL,
    TEXTO_BORRADO_CANCELADO,
    TEXTO_BORRADO_OK,
    TEXTO_DESHECHO_CORRECCION,
    TEXTO_DESHECHO_CREACION,
    TEXTO_NADA_QUE_DESHACER,
    TEXTO_REACTIVADO,
    TEXTO_SELECCION_INVALIDA,
    TTL_A08_SEGUNDOS,
    SolicitudBorrado,
    detectar_confirmacion_borrado,
    detectar_deshacer,
    detectar_historial,
    detectar_intencion_correccion,
    detectar_reactivar,
    detectar_solicitud_borrado,
    formatear_confirmacion_movimiento,
    formatear_historial,
    formatear_lista_borrado,
    formatear_prompt_borrado,
    indice_seleccionado,
    resumen_movimiento,
    snapshot_movimiento,
)
from services.politica_service import POLITICA_VERSION
from services.sheets_service import MovimientoAnuladoError
from services.suscripcion_service import TEXTO_SUSCRIPCION_VENCIDA
from workers.tasks import (
    CLAVE_A08_BORRADO,
    CLAVE_A08_ULTIMA,
    _recordar_ultima_accion,
    procesar_mensaje_texto_task,
)

TELEFONO = "50688888888"
MOVIMIENTO_ID = "mov-1"


def _movimiento(
    movimiento_id: str = MOVIMIENTO_ID,
    *,
    monto_centimos: int = 150000,
    tipo: str = "gasto",
    estado: str = "confirmado",
    categoria: str = "Alimentación",
    detalle: str = "almuerzo",
    fecha: str = "2026-11-08 18:00:00",
    version: int = 1,
) -> dict[str, Any]:
    monto = monto_centimos // 100
    return {
        "fecha_movimiento": fecha,
        "monto_centimos": monto_centimos,
        "categoria": categoria,
        "detalle": detalle,
        "telefono": TELEFONO,
        "movimiento_id": movimiento_id,
        "tipo_movimiento": tipo,
        "moneda": "CRC",
        "contexto_tipo": "personal",
        "estado": estado,
        "version": version,
        "fecha_registro": fecha,
        "origen": "chat",
        "monto": -monto if tipo == "gasto" else monto,
    }


# ==========================================
# Servicio puro: detección y formato
# ==========================================
def test_detecta_borrado_por_tipo_y_monto() -> None:
    ultimo = detectar_solicitud_borrado("borrá el último gasto")
    con_monto = detectar_solicitud_borrado("borra el gasto de 5 mil")

    assert ultimo == SolicitudBorrado(tipo="gasto", monto_centimos=None)
    assert con_monto == SolicitudBorrado(tipo="gasto", monto_centimos=500000)


def test_borrado_no_intercepta_presupuestos() -> None:
    assert detectar_solicitud_borrado("borrá el presupuesto de transporte") is None
    assert detectar_solicitud_borrado("hola") is None


def test_borrado_entiende_miles_y_ordinales() -> None:
    # "5.000" no debe leerse como ₡5: el separador de miles se elimina antes de parsear.
    assert detectar_solicitud_borrado("borrá el gasto de 5.000") == SolicitudBorrado(
        tipo="gasto", monto_centimos=500000
    )
    assert detectar_solicitud_borrado("borrá el gasto de 5,000") == SolicitudBorrado(
        tipo="gasto", monto_centimos=500000
    )
    assert detectar_solicitud_borrado("borrá el primer gasto") == SolicitudBorrado(
        tipo="gasto", ordinal=0
    )
    assert detectar_solicitud_borrado("borrá el segundo gasto de 5 mil") == SolicitudBorrado(
        tipo="gasto", monto_centimos=500000, ordinal=1
    )


def test_confirmacion_de_borrado_exige_frase_explicita() -> None:
    assert detectar_confirmacion_borrado("sí, borrar") == "si"
    assert detectar_confirmacion_borrado("confirmo") == "si"
    assert detectar_confirmacion_borrado("no") == "no"
    assert detectar_confirmacion_borrado("mejor no") == "no"
    # Un "sí" pelado no alcanza: puede responder a otra cosa (D24).
    assert detectar_confirmacion_borrado("sí") is None
    assert detectar_confirmacion_borrado("tal vez") is None


def test_detecta_deshacer_historial_reactivar_y_correccion() -> None:
    assert detectar_deshacer("deshacé eso")
    assert detectar_deshacer("volver atrás")
    assert not detectar_deshacer("gasté 1000")

    assert detectar_historial("historial de cambios")
    assert detectar_historial("¿quién cambió esto?")
    assert not detectar_historial("gasté 1000")

    assert detectar_reactivar("reactivá el último")
    assert detectar_reactivar("restaurá el anulado")
    assert not detectar_reactivar("gasté 1000")

    assert detectar_intencion_correccion("corregí, eran 5000")
    assert detectar_intencion_correccion("no era alimentación, era transporte")
    assert not detectar_intencion_correccion("gasté 1500 en almuerzo")


def test_prompt_de_borrado_muestra_tipo_signo_monto_fecha_y_contexto() -> None:
    texto = formatear_prompt_borrado(_movimiento())

    assert "Gasto" in texto
    assert "-₡1,500" in texto
    assert "Alimentación" in texto
    assert "08/11/2026" in texto
    assert "personal" in texto
    assert '"sí, borrar"' in texto


def test_lista_de_borrado_numera_y_permite_elegir_por_numero_o_monto() -> None:
    candidatos = [
        _movimiento("mov-1", monto_centimos=500000),
        _movimiento("mov-2", monto_centimos=500000, fecha="2026-11-08 19:00:00"),
    ]

    texto = formatear_lista_borrado(candidatos)

    assert "1." in texto and "2." in texto
    assert indice_seleccionado("el segundo", candidatos) == 1
    assert indice_seleccionado("2", candidatos) == 1
    assert indice_seleccionado("5000", candidatos) == 0
    assert indice_seleccionado("no sé", candidatos) is None


def test_historial_formatea_el_delta_y_no_expone_campos_internos() -> None:
    entradas = [
        {
            "accion": "corregir",
            "actor_id": TELEFONO,
            "fecha": "2026-11-08 18:00:00",
            "antes": _movimiento(monto_centimos=100000, categoria="Alimentación"),
            "despues": _movimiento(
                monto_centimos=120000,
                categoria="Transporte",
                detalle="taxi",
                estado="corregido",
            ),
        }
    ]

    texto = formatear_historial(entradas, TELEFONO)

    assert "corrección" in texto
    assert "monto ₡1,000 → ₡1,200" in texto
    assert "categoría Alimentación → Transporte" in texto
    assert "detalle «almuerzo» → «taxi»" in texto
    assert "(vos)" in texto
    assert "mov-1" not in texto


def test_historial_de_borrado_muestra_el_movimiento_final() -> None:
    entradas = [
        {
            "accion": "anular",
            "actor_id": TELEFONO,
            "fecha": "2026-11-08 18:00:00",
            "antes": _movimiento(),
            "despues": _movimiento(estado="anulado", version=2),
        }
    ]

    texto = formatear_historial(entradas, TELEFONO)

    assert "borrado" in texto
    assert "Gasto: -₡1,500" in texto
    assert "Alimentación" in texto


def test_snapshot_excluye_la_fila_interna_y_formatea_resumen() -> None:
    movimiento = _movimiento()
    movimiento["_fila"] = 7

    instantanea = snapshot_movimiento(movimiento)

    assert "_fila" not in instantanea
    assert instantanea["movimiento_id"] == MOVIMIENTO_ID
    assert "Gasto: -₡1,500" in resumen_movimiento(movimiento)


async def test_ultima_accion_se_guarda_con_ttl_de_diez_minutos() -> None:
    """D23: la ventana es de 10 minutos; el TTL se pasa explícitamente a Redis."""
    fake_redis = AsyncMock()
    fake_redis.set = AsyncMock()
    fake_redis.aclose = AsyncMock()

    with patch("workers.tasks._dedupe_redis", new=AsyncMock(return_value=fake_redis)):
        await _recordar_ultima_accion(TELEFONO, "crear", MOVIMIENTO_ID, None, _movimiento())

    fake_redis.set.assert_awaited_once()
    assert fake_redis.set.await_args.kwargs["ex"] == TTL_A08_SEGUNDOS


# ==========================================
# Pipeline: dobles de Sheets/WhatsApp/Redis
# ==========================================
@pytest.fixture
def a08(redis_aislado: Any):
    """Patch del pipeline con servicios externos simulados y Redis en memoria."""
    stack = ExitStack()
    mocks = {
        "wa": stack.enter_context(patch("workers.tasks.enviar_mensaje_whatsapp")),
        "consent": stack.enter_context(
            patch(
                "workers.tasks.obtener_consentimiento",
                return_value={"estado": "aceptado", "version_politica": POLITICA_VERSION},
            )
        ),
        "paso": stack.enter_context(
            patch("workers.tasks.obtener_paso", new=AsyncMock(return_value=None))
        ),
        "consulta": stack.enter_context(
            patch("workers.tasks.detectar_consulta", new=AsyncMock(return_value=None))
        ),
        "parse": stack.enter_context(
            patch("workers.tasks.parse_financial_text", new=AsyncMock(return_value=None))
        ),
        "append": stack.enter_context(
            patch(
                "workers.tasks.append_transaction_to_sheet",
                new=AsyncMock(return_value=None),
            )
        ),
        "update": stack.enter_context(
            patch(
                "workers.tasks.update_last_transaction_to_sheet",
                new=AsyncMock(return_value=None),
            )
        ),
        "movimientos": stack.enter_context(
            patch(
                "workers.tasks.obtener_movimientos_cliente",
                new=AsyncMock(return_value=[]),
            )
        ),
        "anular": stack.enter_context(
            patch("workers.tasks.anular_movimiento", new=AsyncMock(return_value=None))
        ),
        "reactivar": stack.enter_context(
            patch("workers.tasks.reactivar_movimiento", new=AsyncMock(return_value=None))
        ),
        "restaurar": stack.enter_context(
            patch("workers.tasks.restaurar_movimiento", new=AsyncMock(return_value=None))
        ),
        "revertir": stack.enter_context(
            patch("workers.tasks.revertir_movimiento", new=AsyncMock(return_value=None))
        ),
        "historial": stack.enter_context(
            patch("workers.tasks.obtener_historial", new=AsyncMock(return_value=[]))
        ),
        "suscripcion": stack.enter_context(
            patch("workers.tasks.obtener_suscripcion", return_value={"estado": "activo"})
        ),
        "alerta": stack.enter_context(
            patch("workers.tasks._evaluar_alerta_presupuesto", new=AsyncMock(return_value=None))
        ),
        "onboarding": stack.enter_context(
            patch(
                "workers.tasks._finalizar_onboarding_si_corresponde",
                new=AsyncMock(return_value=None),
            )
        ),
        "preferencias": stack.enter_context(
            patch(
                "workers.tasks.guardar_preferencia_automaticos",
                new=AsyncMock(return_value=True),
            )
        ),
    }
    with stack:
        yield mocks


def _ultimo_mensaje(mocks: dict[str, Any]) -> str:
    return str(mocks["wa"].call_args_list[-1].kwargs["mensaje"])


def _registrar(mocks: dict[str, Any], movimiento: dict[str, Any] | None = None) -> dict[str, Any]:
    movimiento = movimiento or _movimiento()
    mocks["append"].return_value = movimiento
    mocks["parse"].return_value = {
        "accion": "registrar",
        "monto": 1500,
        "categoria": "Alimentación",
        "tipo_movimiento": "Gasto",
        "detalle": "almuerzo",
    }
    procesar_mensaje_texto_task(TELEFONO, "gasté 1500 en un almuerzo")
    return movimiento


def test_borrado_pide_confirmacion_y_no_borra_sin_ella(
    a08: dict[str, Any], redis_aislado: Any
) -> None:
    movimiento = _movimiento()
    a08["movimientos"].return_value = [movimiento]

    procesar_mensaje_texto_task(TELEFONO, "borrá el último gasto")

    assert a08["anular"].await_count == 0
    assert _ultimo_mensaje(a08) == formatear_prompt_borrado(movimiento)
    assert CLAVE_A08_BORRADO.format(TELEFONO) in redis_aislado.store

    procesar_mensaje_texto_task(TELEFONO, "no")

    assert a08["anular"].await_count == 0
    assert _ultimo_mensaje(a08) == TEXTO_BORRADO_CANCELADO
    assert CLAVE_A08_BORRADO.format(TELEFONO) not in redis_aislado.store

    procesar_mensaje_texto_task(TELEFONO, "borrá el último gasto")
    a08["anular"].return_value = {
        "movimiento_id": MOVIMIENTO_ID,
        "antes": movimiento,
        "despues": {**movimiento, "estado": "anulado", "version": 2},
    }
    procesar_mensaje_texto_task(TELEFONO, "sí, borrar")

    a08["anular"].assert_awaited_once_with(TELEFONO, MOVIMIENTO_ID, "solicitud del usuario")
    assert _ultimo_mensaje(a08) == TEXTO_BORRADO_OK
    ultima = redis_aislado.store[CLAVE_A08_ULTIMA.format(TELEFONO)]
    assert '"accion": "anular"' in ultima


def test_borrado_con_dos_montos_iguales_pide_seleccion(a08: dict[str, Any]) -> None:
    primero = _movimiento("mov-1", monto_centimos=500000)
    segundo = _movimiento("mov-2", monto_centimos=500000, fecha="2026-11-08 19:00:00")
    a08["movimientos"].return_value = [primero, segundo]

    procesar_mensaje_texto_task(TELEFONO, "borrá el gasto de 5000")

    assert "1." in _ultimo_mensaje(a08)
    assert a08["anular"].await_count == 0

    procesar_mensaje_texto_task(TELEFONO, "dos")

    assert "¿Borro este movimiento?" in _ultimo_mensaje(a08)
    # La hoja guarda UTC; la confirmación muestra la hora de Costa Rica (UTC-6).
    assert "08/11/2026 13:00" in _ultimo_mensaje(a08)

    procesar_mensaje_texto_task(TELEFONO, "quizás")

    assert _ultimo_mensaje(a08).startswith("No borré nada")

    procesar_mensaje_texto_task(TELEFONO, "no")

    assert _ultimo_mensaje(a08) == TEXTO_BORRADO_CANCELADO


def test_borrado_del_primero_no_elige_el_ultimo(a08: dict[str, Any]) -> None:
    primero = _movimiento("mov-1", monto_centimos=100000, detalle="primero")
    segundo = _movimiento("mov-2", monto_centimos=200000, detalle="segundo")
    a08["movimientos"].return_value = [primero, segundo]

    procesar_mensaje_texto_task(TELEFONO, "borrá el primer gasto")

    assert _ultimo_mensaje(a08) == formatear_prompt_borrado(primero)
    assert "-₡1,000" in _ultimo_mensaje(a08)
    assert a08["anular"].await_count == 0


def test_registro_muestra_confirmacion_completa_y_guarda_ultima_accion(
    a08: dict[str, Any], redis_aislado: Any
) -> None:
    movimiento = _registrar(a08)

    mensaje = _ultimo_mensaje(a08)
    assert mensaje == formatear_confirmacion_movimiento(movimiento)
    assert "Gasto" in mensaje
    assert "-₡1,500" in mensaje
    assert "Alimentación" in mensaje
    assert "personal" in mensaje
    assert "¿Está bien?" in mensaje

    ultima = redis_aislado.store[CLAVE_A08_ULTIMA.format(TELEFONO)]
    assert '"accion": "crear"' in ultima


def test_deshacer_creacion_anula_y_consume_la_ventana(
    a08: dict[str, Any], redis_aislado: Any
) -> None:
    movimiento = _registrar(a08)
    a08["anular"].return_value = {
        "movimiento_id": MOVIMIENTO_ID,
        "antes": movimiento,
        "despues": {**movimiento, "estado": "anulado", "version": 2},
    }

    procesar_mensaje_texto_task(TELEFONO, "deshacé")

    assert a08["anular"].await_args.kwargs["accion"] == "deshacer"
    assert a08["anular"].await_args.args == (
        TELEFONO,
        MOVIMIENTO_ID,
        "deshacer registro",
    )
    assert _ultimo_mensaje(a08) == TEXTO_DESHECHO_CREACION
    assert CLAVE_A08_ULTIMA.format(TELEFONO) not in redis_aislado.store


def test_el_siguiente_mensaje_cierra_la_ventana_de_deshacer(
    a08: dict[str, Any], redis_aislado: Any
) -> None:
    _registrar(a08)
    assert CLAVE_A08_ULTIMA.format(TELEFONO) in redis_aislado.store

    # "historial" es un mensaje procesado: consume la ventana (D23) y no crea acción.
    procesar_mensaje_texto_task(TELEFONO, "historial de cambios")
    assert CLAVE_A08_ULTIMA.format(TELEFONO) not in redis_aislado.store

    procesar_mensaje_texto_task(TELEFONO, "deshacé")

    assert a08["anular"].await_count == 0
    assert _ultimo_mensaje(a08) == TEXTO_NADA_QUE_DESHACER


def test_un_mensaje_administrativo_tambien_cierra_la_ventana(
    a08: dict[str, Any], redis_aislado: Any
) -> None:
    """D23 no distingue tipos de mensaje: STOP consume la ventana antes de A08."""
    _registrar(a08)
    assert CLAVE_A08_ULTIMA.format(TELEFONO) in redis_aislado.store

    procesar_mensaje_texto_task(TELEFONO, "stop")
    assert CLAVE_A08_ULTIMA.format(TELEFONO) not in redis_aislado.store

    procesar_mensaje_texto_task(TELEFONO, "deshacé")

    assert a08["anular"].await_count == 0
    assert _ultimo_mensaje(a08) == TEXTO_NADA_QUE_DESHACER


def test_deshacer_correccion_restaura_el_snapshot_anterior(
    a08: dict[str, Any], redis_aislado: Any
) -> None:
    antes = _movimiento(monto_centimos=150000, categoria="Alimentación")
    despues = {
        **antes,
        "monto_centimos": 600000,
        "monto": -6000,
        "categoria": "Transporte",
        "detalle": "taxi",
        "estado": "corregido",
        "version": 2,
    }
    a08["update"].return_value = {
        "movimiento_id": MOVIMIENTO_ID,
        "antes": antes,
        "despues": despues,
    }
    a08["parse"].return_value = {
        "accion": "corregir",
        "monto": 6000,
        "categoria": "Transporte",
        "tipo_movimiento": "Gasto",
        "detalle": "taxi",
    }

    procesar_mensaje_texto_task(TELEFONO, "corregí, eran 6000 en transporte")

    assert _ultimo_mensaje(a08) == formatear_confirmacion_movimiento(despues, verbo="Corregí")
    ultima = redis_aislado.store[CLAVE_A08_ULTIMA.format(TELEFONO)]
    assert '"accion": "corregir"' in ultima

    a08["revertir"].return_value = {
        "movimiento_id": MOVIMIENTO_ID,
        "antes": despues,
        "despues": antes,
    }
    procesar_mensaje_texto_task(TELEFONO, "deshacé")

    a08["revertir"].assert_awaited_once()
    argumentos = a08["revertir"].await_args.args
    assert argumentos[0] == TELEFONO
    assert argumentos[1] == MOVIMIENTO_ID
    assert argumentos[2]["monto_centimos"] == 150000
    assert argumentos[2]["categoria"] == "Alimentación"
    assert _ultimo_mensaje(a08) == TEXTO_DESHECHO_CORRECCION


def test_correccion_de_anulado_pide_reactivar(a08: dict[str, Any]) -> None:
    a08["update"].side_effect = MovimientoAnuladoError({"movimiento_id": MOVIMIENTO_ID})
    a08["parse"].return_value = {
        "accion": "corregir",
        "monto": 6000,
        "categoria": "Transporte",
        "tipo_movimiento": "Gasto",
        "detalle": "taxi",
    }

    procesar_mensaje_texto_task(TELEFONO, "corregí, eran 6000")

    assert "reactivá el último" in _ultimo_mensaje(a08)
    assert a08["append"].await_count == 0


def test_historial_pide_las_entradas_del_propio_telefono(a08: dict[str, Any]) -> None:
    a08["historial"].return_value = [
        {
            "accion": "anular",
            "actor_id": TELEFONO,
            "fecha": "2026-11-08 18:00:00",
            "antes": _movimiento(),
            "despues": _movimiento(estado="anulado"),
        }
    ]

    procesar_mensaje_texto_task(TELEFONO, "historial de cambios")

    a08["historial"].assert_awaited_once_with(TELEFONO, limite=MAX_HISTORIAL)
    assert _ultimo_mensaje(a08).startswith("Últimos cambios de tu cuenta:")
    assert "borrado" in _ultimo_mensaje(a08)
    assert a08["anular"].await_count == 0


def test_reactivar_ultimo_anulado(a08: dict[str, Any], redis_aislado: Any) -> None:
    anulado = _movimiento(estado="anulado", version=2)
    reactivado = {**anulado, "estado": "confirmado", "version": 3}
    a08["movimientos"].return_value = [anulado]
    a08["reactivar"].return_value = {
        "movimiento_id": MOVIMIENTO_ID,
        "antes": anulado,
        "despues": reactivado,
    }

    procesar_mensaje_texto_task(TELEFONO, "reactivá el último")

    a08["reactivar"].assert_awaited_once_with(TELEFONO, MOVIMIENTO_ID)
    assert _ultimo_mensaje(a08) == TEXTO_REACTIVADO
    ultima = redis_aislado.store[CLAVE_A08_ULTIMA.format(TELEFONO)]
    assert '"accion": "reactivar"' in ultima


def test_reactivar_sin_anulados_avisa(a08: dict[str, Any]) -> None:
    a08["movimientos"].return_value = [_movimiento()]

    procesar_mensaje_texto_task(TELEFONO, "reactivá el último")

    assert _ultimo_mensaje(a08) == "No hay movimientos anulados para reactivar."
    assert a08["reactivar"].await_count == 0


def test_d25_plan_vencido_permite_corregir_pero_no_registrar(a08: dict[str, Any]) -> None:
    a08["suscripcion"].return_value = {"estado": "vencido"}
    a08["update"].return_value = {
        "movimiento_id": MOVIMIENTO_ID,
        "antes": _movimiento(),
        "despues": _movimiento(estado="corregido", version=2),
    }
    a08["parse"].return_value = {
        "accion": "corregir",
        "monto": 6000,
        "categoria": "Transporte",
        "tipo_movimiento": "Gasto",
        "detalle": "taxi",
    }

    procesar_mensaje_texto_task(TELEFONO, "corregí, eran 6000 en transporte")

    a08["update"].assert_awaited_once()
    assert _ultimo_mensaje(a08) != TEXTO_SUSCRIPCION_VENCIDA

    # Un registro nuevo con plan vencido se bloquea antes de llamar al parser.
    llamadas_parse = a08["parse"].await_count
    a08["parse"].return_value = {
        "accion": "registrar",
        "monto": 1500,
        "categoria": "Alimentación",
        "tipo_movimiento": "Gasto",
        "detalle": "almuerzo",
    }

    procesar_mensaje_texto_task(TELEFONO, "gasté 1500 en un almuerzo")

    assert a08["parse"].await_count == llamadas_parse
    assert _ultimo_mensaje(a08) == TEXTO_SUSCRIPCION_VENCIDA
    assert a08["append"].await_count == 0


def test_d25_falso_positivo_de_correccion_no_crea_movimiento_con_plan_vencido(
    a08: dict[str, Any],
) -> None:
    a08["suscripcion"].return_value = {"estado": "vencido"}
    a08["parse"].return_value = {
        "accion": "registrar",
        "monto": 1500,
        "categoria": "Alimentación",
        "tipo_movimiento": "Gasto",
        "detalle": "almuerzo",
    }

    # "actualiza" dispara la heurística de corrección, pero el parser dice "registrar".
    procesar_mensaje_texto_task(TELEFONO, "actualiza 1500 en un almuerzo")

    assert a08["parse"].await_count == 1
    assert a08["append"].await_count == 0
    assert _ultimo_mensaje(a08) == TEXTO_SUSCRIPCION_VENCIDA


def test_seleccion_invalida_no_borra_y_pide_numero(a08: dict[str, Any]) -> None:
    a08["movimientos"].return_value = [
        _movimiento("mov-1", monto_centimos=500000),
        _movimiento("mov-2", monto_centimos=500000),
    ]

    procesar_mensaje_texto_task(TELEFONO, "borrá el gasto de 5000")
    procesar_mensaje_texto_task(TELEFONO, "el que sea")

    assert _ultimo_mensaje(a08) == TEXTO_SELECCION_INVALIDA
    assert a08["anular"].await_count == 0
