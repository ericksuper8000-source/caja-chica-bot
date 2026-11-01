from unittest.mock import patch

from services.onboarding_service import (
    CONTEXTO_DEFECTO,
    PASO_CATEGORIAS,
    PASO_COMPLETADO,
    PASO_CONTEXTO,
    PASO_ESPACIO,
    PASO_PRIMER_MOVIMIENTO,
    PASO_TIPO_USO,
    TEXTO_ONBOARDING_CATEGORIAS_CONFIRMADO,
    TEXTO_ONBOARDING_CATEGORIAS_REINTENTO,
    TEXTO_ONBOARDING_CONTEXTO,
    TEXTO_ONBOARDING_CONTEXTO_CONFIRMADO,
    TEXTO_ONBOARDING_CONTEXTO_REINTENTO,
    TEXTO_ONBOARDING_ESPACIO,
    TEXTO_ONBOARDING_ESPACIO_REINTENTO,
    TEXTO_ONBOARDING_PRIMER_MOVIMIENTO,
    TEXTO_ONBOARDING_RESUMEN_SIN_MOVIMIENTO,
    TEXTO_ONBOARDING_TIPO_USO,
    TEXTO_ONBOARDING_TIPO_USO_REINTENTO,
    categorias_sugeridas,
    detectar_contexto,
    detectar_saltar_primer_movimiento,
    detectar_tipo_uso,
    formatear_pregunta_categorias,
    guardar_paso,
    limpiar_paso,
    obtener_paso,
    procesar_categorias,
    texto_resumen_onboarding,
)
from workers.tasks import (
    _finalizar_onboarding_si_corresponde,
    _procesar_pipeline,
    _responder_paso_onboarding,
)


def test_detectar_tipo_uso() -> None:
    assert detectar_tipo_uso("negocio") == "negocio"
    assert detectar_tipo_uso("Personal") == "personal"
    assert detectar_tipo_uso("trabajo") == "trabajo"
    assert detectar_tipo_uso("Evento") == "evento"
    assert detectar_tipo_uso("ruta") == "ruta"
    assert detectar_tipo_uso("proyecto") == "proyecto"
    assert detectar_tipo_uso("mi negocio") == "negocio"
    assert detectar_tipo_uso("negocios") == "negocio"
    assert detectar_tipo_uso("quiero fruta") is None
    assert detectar_tipo_uso("gaste 5000 en el almuerzo") is None
    assert detectar_tipo_uso("") is None


def test_texto_tipo_uso_incluye_ejemplos() -> None:
    for opcion in ("Personal", "Negocio", "Trabajo", "Evento", "Ruta", "Proyecto"):
        assert opcion in TEXTO_ONBOARDING_TIPO_USO
    assert "tienda" in TEXTO_ONBOARDING_TIPO_USO


async def test_guardar_y_obtener_paso(redis_aislado) -> None:
    assert await guardar_paso("50688888888", PASO_TIPO_USO) is True
    estado = await obtener_paso("50688888888")
    assert estado is not None
    assert estado["paso"] == PASO_TIPO_USO
    assert await limpiar_paso("50688888888") is True
    assert await obtener_paso("50688888888") is None


async def test_responder_paso_onboarding_ignora_otros_pasos() -> None:
    with patch("workers.tasks.obtener_paso", return_value={"paso": "desconocido"}):
        assert await _responder_paso_onboarding("50688888888", "negocio") is None


async def test_responder_paso_onboarding_reintenta_si_no_entiende() -> None:
    with patch("workers.tasks.obtener_paso", return_value={"paso": "tipo_uso"}):
        respuesta = await _responder_paso_onboarding("50688888888", "hola")
    assert respuesta == TEXTO_ONBOARDING_TIPO_USO_REINTENTO


async def test_responder_paso_onboarding_deja_pasar_movimiento() -> None:
    with patch("workers.tasks.obtener_paso", return_value={"paso": "tipo_uso"}):
        assert await _responder_paso_onboarding("50688888888", "gaste 5000 en el almuerzo") is None


async def test_responder_paso_onboarding_no_se_traga_arco() -> None:
    with patch("workers.tasks.obtener_paso", return_value={"paso": "tipo_uso"}):
        assert await _responder_paso_onboarding("50688888888", "darme de baja") is None


async def test_pipeline_con_tipo_uso_continua_onboarding() -> None:
    with (
        patch(
            "workers.tasks.obtener_consentimiento",
            return_value={"estado": "aceptado", "version_politica": "1.0"},
        ),
        patch("workers.tasks.obtener_paso", return_value={"paso": "tipo_uso"}),
        patch("workers.tasks.guardar_paso") as mock_guardar,
        patch("workers.tasks.detectar_tipo_uso", return_value="negocio"),
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
    ):
        result = await _procesar_pipeline(None, "50688888888", texto_entrante="negocio")

    assert result == ""
    mock_guardar.assert_called_once_with("50688888888", PASO_ESPACIO, tipo_uso="negocio")
    mock_whatsapp.assert_called_once_with(to_phone="50688888888", mensaje=TEXTO_ONBOARDING_ESPACIO)


async def test_espacio_guarda_nombre_y_pasa_a_contexto() -> None:
    with (
        patch(
            "workers.tasks.obtener_paso",
            return_value={"paso": "espacio", "tipo_uso": "negocio"},
        ),
        patch("workers.tasks.guardar_paso") as mock_guardar,
    ):
        respuesta = await _responder_paso_onboarding("50688888888", "La Panadería de Ana")

    assert respuesta == TEXTO_ONBOARDING_CONTEXTO.format(espacio="La Panadería de Ana")
    mock_guardar.assert_called_once_with(
        "50688888888",
        PASO_CONTEXTO,
        espacio="La Panadería de Ana",
        tipo_uso="negocio",
    )


async def test_espacio_reintenta_si_nombre_invalido() -> None:
    with patch("workers.tasks.obtener_paso", return_value={"paso": "espacio"}):
        respuesta = await _responder_paso_onboarding("50688888888", "   ")
    assert respuesta == TEXTO_ONBOARDING_ESPACIO_REINTENTO


async def test_espacio_deja_pasar_movimiento() -> None:
    with patch("workers.tasks.obtener_paso", return_value={"paso": "espacio"}):
        assert await _responder_paso_onboarding("50688888888", "gasté 5000 en café") is None


async def test_espacio_no_se_traga_arco() -> None:
    with patch("workers.tasks.obtener_paso", return_value={"paso": "espacio"}):
        assert await _responder_paso_onboarding("50688888888", "darme de baja") is None


async def test_pipeline_espacio_pasa_a_contexto() -> None:
    with (
        patch(
            "workers.tasks.obtener_consentimiento",
            return_value={"estado": "aceptado", "version_politica": "1.0"},
        ),
        patch(
            "workers.tasks.obtener_paso",
            return_value={"paso": "espacio", "tipo_uso": "personal"},
        ),
        patch("workers.tasks.guardar_paso") as mock_guardar,
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
    ):
        result = await _procesar_pipeline(None, "50688888888", texto_entrante="Mi Tienda")

    assert result == ""
    mock_guardar.assert_called_once_with(
        "50688888888", PASO_CONTEXTO, espacio="Mi Tienda", tipo_uso="personal"
    )
    mock_whatsapp.assert_called_once_with(
        to_phone="50688888888",
        mensaje=TEXTO_ONBOARDING_CONTEXTO.format(espacio="Mi Tienda"),
    )


def test_detectar_contexto() -> None:
    assert detectar_contexto("sí") == CONTEXTO_DEFECTO
    assert detectar_contexto("OK") == CONTEXTO_DEFECTO
    assert detectar_contexto("Costa Rica") == CONTEXTO_DEFECTO
    panama = detectar_contexto("estoy en Panamá")
    assert panama is not None
    assert panama["moneda"] == "USD"
    mexico = detectar_contexto("México")
    assert mexico is not None
    assert mexico["moneda"] == "MXN"
    espana = detectar_contexto("España")
    assert espana is not None
    assert espana["moneda"] == "EUR"
    assert detectar_contexto("no sé") is None
    assert detectar_contexto("") is None


async def test_contexto_guarda_defaults() -> None:
    with (
        patch(
            "workers.tasks.obtener_paso",
            return_value={"paso": "contexto", "espacio": "Mi Tienda", "tipo_uso": "negocio"},
        ),
        patch("workers.tasks.guardar_paso") as mock_guardar,
    ):
        respuesta = await _responder_paso_onboarding("50688888888", "sí")

    assert respuesta.startswith(TEXTO_ONBOARDING_CONTEXTO_CONFIRMADO.format(**CONTEXTO_DEFECTO))
    assert "categor" in respuesta
    mock_guardar.assert_called_once_with(
        "50688888888",
        PASO_CATEGORIAS,
        pais="Costa Rica",
        moneda="CRC",
        zona="America/Costa_Rica",
        espacio="Mi Tienda",
        tipo_uso="negocio",
    )


async def test_contexto_detecta_pais() -> None:
    with (
        patch("workers.tasks.obtener_paso", return_value={"paso": "contexto"}),
        patch("workers.tasks.guardar_paso") as mock_guardar,
    ):
        respuesta = await _responder_paso_onboarding("50688888888", "Panamá")

    assert "Panamá" in respuesta
    assert mock_guardar.call_args.kwargs["moneda"] == "USD"
    assert mock_guardar.call_args.args[1] == PASO_CATEGORIAS


async def test_contexto_reintenta_si_no_entiende() -> None:
    with patch("workers.tasks.obtener_paso", return_value={"paso": "contexto"}):
        respuesta = await _responder_paso_onboarding("50688888888", "no sé")
    assert respuesta == TEXTO_ONBOARDING_CONTEXTO_REINTENTO


async def test_contexto_deja_pasar_movimiento() -> None:
    with patch("workers.tasks.obtener_paso", return_value={"paso": "contexto"}):
        assert await _responder_paso_onboarding("50688888888", "gasté 5000 en café") is None


async def test_contexto_no_se_traga_arco() -> None:
    with patch("workers.tasks.obtener_paso", return_value={"paso": "contexto"}):
        assert await _responder_paso_onboarding("50688888888", "darme de baja") is None


async def test_pipeline_contexto_confirma() -> None:
    with (
        patch(
            "workers.tasks.obtener_consentimiento",
            return_value={"estado": "aceptado", "version_politica": "1.0"},
        ),
        patch(
            "workers.tasks.obtener_paso",
            return_value={"paso": "contexto", "espacio": "Mi Tienda", "tipo_uso": "personal"},
        ),
        patch("workers.tasks.guardar_paso") as mock_guardar,
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
    ):
        result = await _procesar_pipeline(None, "50688888888", texto_entrante="sí")

    assert result == ""
    assert mock_guardar.call_args.args[1] == PASO_CATEGORIAS
    mock_whatsapp.assert_called_once()
    mensaje = mock_whatsapp.call_args.kwargs["mensaje"]
    assert mensaje.startswith(TEXTO_ONBOARDING_CONTEXTO_CONFIRMADO.format(**CONTEXTO_DEFECTO))
    assert "categor" in mensaje


def test_categorias_sugeridas_por_tipo() -> None:
    assert "Ventas" in categorias_sugeridas("negocio")
    assert "Alimentación" in categorias_sugeridas("personal")
    assert categorias_sugeridas("desconocido") == categorias_sugeridas("personal")


def test_formatear_pregunta_categorias() -> None:
    texto = formatear_pregunta_categorias("negocio")
    assert "Ventas" in texto
    assert "todas" in texto


def test_procesar_categorias_todas() -> None:
    assert procesar_categorias("todas", "personal") == categorias_sugeridas("personal")


def test_procesar_categorias_quita() -> None:
    resultado = procesar_categorias("sin Ocio", "personal")
    assert resultado is not None
    assert "Ocio" not in resultado
    assert "Alimentación" in resultado


def test_procesar_categorias_quita_varias() -> None:
    resultado = procesar_categorias("quita ocio y salud", "personal")
    assert resultado is not None
    assert "Ocio" not in resultado
    assert "Salud" not in resultado


def test_procesar_categorias_agrega() -> None:
    resultado = procesar_categorias("agrega Mascotas", "personal")
    assert resultado is not None
    assert "Mascotas" in resultado


def test_procesar_categorias_quita_y_agrega() -> None:
    resultado = procesar_categorias("sin Ocio, agrega Mascotas", "personal")
    assert resultado is not None
    assert "Ocio" not in resultado
    assert "Mascotas" in resultado


def test_procesar_categorias_invalido() -> None:
    assert procesar_categorias("hola", "personal") is None


async def test_categorias_guarda_y_pasa_a_primer_movimiento() -> None:
    with (
        patch(
            "workers.tasks.obtener_paso",
            return_value={"paso": "categorias", "tipo_uso": "negocio", "espacio": "Mi Tienda"},
        ),
        patch("workers.tasks.guardar_paso") as mock_guardar,
    ):
        respuesta = await _responder_paso_onboarding("50688888888", "todas")

    esperadas = ", ".join(categorias_sugeridas("negocio"))
    assert respuesta == (
        TEXTO_ONBOARDING_CATEGORIAS_CONFIRMADO.format(categorias=esperadas)
        + "\n\n"
        + TEXTO_ONBOARDING_PRIMER_MOVIMIENTO
    )
    mock_guardar.assert_called_once_with(
        "50688888888",
        PASO_PRIMER_MOVIMIENTO,
        categorias=esperadas,
        tipo_uso="negocio",
        espacio="Mi Tienda",
    )


async def test_categorias_reintenta_si_no_entiende() -> None:
    with patch(
        "workers.tasks.obtener_paso", return_value={"paso": "categorias", "tipo_uso": "personal"}
    ):
        respuesta = await _responder_paso_onboarding("50688888888", "hola")
    assert respuesta == TEXTO_ONBOARDING_CATEGORIAS_REINTENTO


async def test_categorias_deja_pasar_movimiento() -> None:
    with patch(
        "workers.tasks.obtener_paso", return_value={"paso": "categorias", "tipo_uso": "personal"}
    ):
        assert await _responder_paso_onboarding("50688888888", "gasté 5000 en café") is None


async def test_categorias_no_se_traga_arco() -> None:
    with patch(
        "workers.tasks.obtener_paso", return_value={"paso": "categorias", "tipo_uso": "personal"}
    ):
        assert await _responder_paso_onboarding("50688888888", "darme de baja") is None


async def test_pipeline_categorias_confirma() -> None:
    with (
        patch(
            "workers.tasks.obtener_consentimiento",
            return_value={"estado": "aceptado", "version_politica": "1.0"},
        ),
        patch(
            "workers.tasks.obtener_paso",
            return_value={"paso": "categorias", "tipo_uso": "personal"},
        ),
        patch("workers.tasks.guardar_paso") as mock_guardar,
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
    ):
        result = await _procesar_pipeline(None, "50688888888", texto_entrante="todas")

    assert result == ""
    assert mock_guardar.call_args.args[1] == PASO_PRIMER_MOVIMIENTO
    mock_whatsapp.assert_called_once()


def test_detectar_saltar_primer_movimiento() -> None:
    assert detectar_saltar_primer_movimiento("saltar") is True
    assert detectar_saltar_primer_movimiento("Después") is True
    assert detectar_saltar_primer_movimiento("ahora no") is True
    assert detectar_saltar_primer_movimiento("gasté 2000 en café") is False
    assert detectar_saltar_primer_movimiento("") is False


def test_texto_resumen_onboarding_con_movimiento() -> None:
    estado = {
        "paso": "primer_movimiento",
        "espacio": "Mi Tienda",
        "tipo_uso": "negocio",
        "pais": "Costa Rica",
        "moneda": "CRC",
        "categorias": "Ventas, Otros",
    }
    texto = texto_resumen_onboarding(estado, {"categoria": "Ventas", "monto": 2000})
    assert "Mi Tienda" in texto
    assert "Ventas" in texto
    assert "₡2000" in texto


def test_texto_resumen_onboarding_sin_movimiento() -> None:
    estado = {"espacio": "Mi Tienda", "moneda": "USD"}
    texto = texto_resumen_onboarding(estado)
    assert TEXTO_ONBOARDING_RESUMEN_SIN_MOVIMIENTO in texto


async def test_primer_movimiento_saltar_cierra_alta() -> None:
    with (
        patch(
            "workers.tasks.obtener_paso",
            return_value={"paso": "primer_movimiento", "espacio": "Mi Tienda"},
        ),
        patch("workers.tasks.guardar_paso") as mock_guardar,
        patch("workers.tasks.upsert_usuario") as mock_usuario,
    ):
        respuesta = await _responder_paso_onboarding("50688888888", "saltar")

    assert respuesta is not None
    assert "Mi Tienda" in respuesta
    assert TEXTO_ONBOARDING_RESUMEN_SIN_MOVIMIENTO in respuesta
    mock_guardar.assert_called_once_with("50688888888", PASO_COMPLETADO, espacio="Mi Tienda")
    mock_usuario.assert_called_once()
    assert mock_usuario.call_args.args[0]["telefono"] == "50688888888"
    assert mock_usuario.call_args.args[0]["espacio"] == "Mi Tienda"


async def test_primer_movimiento_deja_pasar_movimiento() -> None:
    with patch(
        "workers.tasks.obtener_paso",
        return_value={"paso": "primer_movimiento", "espacio": "Mi Tienda"},
    ):
        assert await _responder_paso_onboarding("50688888888", "gasté 2000 en café") is None


async def test_primer_movimiento_no_se_traga_arco() -> None:
    with patch(
        "workers.tasks.obtener_paso",
        return_value={"paso": "primer_movimiento", "espacio": "Mi Tienda"},
    ):
        assert await _responder_paso_onboarding("50688888888", "darme de baja") is None


async def test_finalizar_onboarding_guarda_completado() -> None:
    with (
        patch(
            "workers.tasks.obtener_paso",
            return_value={"paso": "primer_movimiento", "espacio": "Mi Tienda", "moneda": "CRC"},
        ),
        patch("workers.tasks.guardar_paso") as mock_guardar,
        patch("workers.tasks.upsert_usuario") as mock_usuario,
    ):
        resumen = await _finalizar_onboarding_si_corresponde(
            "50688888888", {"categoria": "Alimentación", "monto": 1500}
        )

    assert resumen is not None
    assert "Mi Tienda" in resumen
    assert "₡1500" in resumen
    mock_guardar.assert_called_once_with(
        "50688888888", PASO_COMPLETADO, espacio="Mi Tienda", moneda="CRC"
    )
    mock_usuario.assert_called_once()
    assert mock_usuario.call_args.args[0]["moneda"] == "CRC"


async def test_finalizar_onboarding_fuera_de_paso() -> None:
    with patch("workers.tasks.obtener_paso", return_value={"paso": "completado"}):
        assert (
            await _finalizar_onboarding_si_corresponde(
                "50688888888", {"categoria": "Alimentación", "monto": 1500}
            )
            is None
        )


async def test_pipeline_primer_movimiento_resume() -> None:
    with (
        patch(
            "workers.tasks.obtener_consentimiento",
            return_value={"estado": "aceptado", "version_politica": "1.0"},
        ),
        patch(
            "workers.tasks.obtener_paso",
            return_value={
                "paso": "primer_movimiento",
                "espacio": "Mi Tienda",
                "tipo_uso": "personal",
                "pais": "Costa Rica",
                "moneda": "CRC",
                "categorias": "Alimentación, Otros",
            },
        ),
        patch("workers.tasks.guardar_paso") as mock_guardar,
        patch(
            "workers.tasks.parse_financial_text",
            return_value={
                "accion": "registrar",
                "monto": 2000,
                "categoria": "Alimentación",
                "tipo_movimiento": "Gasto",
                "detalle": "café",
            },
        ),
        patch("workers.tasks.append_transaction_to_sheet"),
        patch("workers.tasks.upsert_usuario") as mock_usuario,
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
    ):
        result = await _procesar_pipeline(None, "50688888888", texto_entrante="gasté 2000 en café")

    assert result == ""
    mock_whatsapp.assert_called_once()
    mensaje = mock_whatsapp.call_args.kwargs["mensaje"]
    assert "Mi Tienda" in mensaje
    assert "Alimentación - ₡2000" in mensaje
    assert mock_guardar.call_args.args[1] == PASO_COMPLETADO
    mock_usuario.assert_called_once()
