"""
Trampas de regresión (5.5.4) — blindan las reglas de negocio decididas el 11-12/08/2026.

Cada función es una "trampa": si la regla se debilita, la trampa se enciende en rojo.

Reglas cubiertas (ver session-log 12/08/2026 y stage-055.md):
- A  Corrección = DELTA (null = "no cambió"); solo llena lo mencionado -> hallazgo 13/08/2026.
- B  Frase sin monto -> NO se crea transacción (accion='aclaracion') -> caso 22.
- C  Los modismos SIEMPRE resuelven a colones; monto nunca null si hay dinero -> caso 6.
- D  Gastos de movilidad = Transporte; ingreso por prestar un servicio = Servicios
     -> casos 11 y 20.
- E  Limitación aceptada de Whisper (transcripción de modismos). Cuando la
     transcripción ES correcta, la lógica debe acertar ("seis tejas" = 600) -> caso 9.
- F  Un modismo con número anula el aclaracion por falta de monto -> caso 6 (12/08).
- G  'Otros' solo como último recurso (no refugio) -> eval 12/08.
- H  Corrección parcial (solo monto) preserva categoría y detalle de la fila anterior
     -> hallazgo 13/08/2026.
- I  Monto 0 NO es un monto válido: sin precio, monto va en null (no 0) -> hallazgo
     20/08/2026 ("3 cajas de pañuelos" se guardaba con monto 0).
- J  Presupuesto/tope/límite/consulta NO es una transacción (accion='no_transaccion',
     0 filas) y un gasto real que mencione la palabra 'presupuesto' SÍ se guarda
     -> DUENO-16 (29/09/2026, fix 8.6.3).

Las reglas A-D, F-J e I se protegen con tests de CONTRATO de prompt: verifican que el system
prompt (SYSTEM_PROMPT_PARSE) contenga la regla. Si la promesa cambia, el prompt debe
cambiarse CON su trampa al mismo tiempo. La regla E es un test de documentación del
comportamiento esperado con transcripción correcta.
"""

from unittest.mock import AsyncMock, patch

import pytest

from services.openai_service import SYSTEM_PROMPT_PARSE, parse_financial_text

_PROMPT = SYSTEM_PROMPT_PARSE.lower()


# ------------------------------------------------------------------
# REGLA A — La corrección es un DELTA: null = "no cambió" (13/08/2026)
# ------------------------------------------------------------------
def test_regla_a_correccion_es_delta_no_reemplazo_total():
    """
    Trampa A (hallazgo 13/08/2026): una corrección NO es un reemplazo total. En
    accion='corregir' el prompt debe expresar que solo se llenan los campos que el
    usuario menciona; los no mencionados van en null y el sistema conserva el valor
    anterior (corrección parcial no destruye categoría/detalle).
    """
    assert "el resultado es un delta" in _PROMPT
    assert "va en null" in _PROMPT
    assert "conserva el valor anterior" in _PROMPT
    assert "no mencione" in _PROMPT


# ------------------------------------------------------------------
# REGLA B — Sin monto no se crea transacción
# ------------------------------------------------------------------
def test_regla_b_sin_monto_no_crea_transaccion():
    """
    Trampa B (caso dorado 22): si el mensaje implica una transacción pero NO indica
    monto, la acción debe ser 'aclaracion' (preguntar), nunca 'registrar'.
    """
    assert "sin monto" in _PROMPT
    assert "nunca creas la transacción" in _PROMPT


# ------------------------------------------------------------------
# REGLA C — Modismos siempre resueltos; monto nunca null si hay dinero
# ------------------------------------------------------------------
def test_regla_c_modismos_siempre_resueltos_monto_no_null():
    """
    Trampa C (caso dorado 6 'dos tucanes'): el prompt debe fijar que si la frase
    menciona dinero, el monto SIEMPRE es un entero y nunca null, y mantener la
    tabla de modismos (tucán = 5.000).
    """
    assert "nunca null" in _PROMPT
    assert "tucán" in _PROMPT
    assert "5,000" in _PROMPT


# ------------------------------------------------------------------
# REGLA D — Categorías: movilidad vs. servicio prestado
# ------------------------------------------------------------------
def test_regla_d_gastos_movilidad_son_transporte_y_ingreso_por_servicio():
    """
    Trampa D (casos dorados 11 y 20): 'parqueo'/'peaje'/'gasolina' (gastos de
    movilidad) deben ir a Transporte; el dinero recibido por PRESTAR un servicio
    ('servicio de transporte') debe ir a Servicios.
    """
    assert "parqueo" in _PROMPT
    assert "movilidad" in _PROMPT
    assert "prestar un servicio" in _PROMPT


# ------------------------------------------------------------------
# REGLA F — Caso 6: "dos tucanes" NO debe disparar aclaración (12/08/2026)
# ------------------------------------------------------------------
def test_regla_f_modismo_con_numero_anula_aclaracion():
    """
    Trampa F (caso dorado 6): el 12/08/2026 el eval detectó un falso positivo — con la
    transcripción perfecta 'Compré inventario y pagué dos tucanes' el bot respondía
    accion='aclaracion'. Regla: un modismo con número ES un monto y anula el
    'aclaracion por falta de monto'; la palabra 'y' por sí sola no crea dos flujos.
    """
    assert "un modismo con número es un monto" in _PROMPT
    assert "aclaracion por falta de monto" in _PROMPT


# ------------------------------------------------------------------
# REGLA G — 'Otros' solo como último recurso (12/08/2026)
# ------------------------------------------------------------------
def test_regla_g_otros_solo_ultimo_recurso():
    """
    Trampa G: en la corrida 2 del eval del 12/08/2026, GPT cayó en 'Otros' por varianza
    estocástica en vez de 'Servicios'/'Ventas'. Regla: 'Otros' es de último recurso y
    Servicios/Ventas se prefieren cuando apliquen.
    """
    assert "último recurso" in _PROMPT
    assert "se prefieren por encima de 'otros'" in _PROMPT


# ------------------------------------------------------------------
# REGLA H — Corrección parcial NO inventa campos (13/08/2026)
# ------------------------------------------------------------------
def test_regla_h_correccion_parcial_no_inventa_categoria():
    """
    Trampa H (hallazgo 13/08/2026): en una corrección que solo menciona el monto
    ("disculpa me equivoque eran 5000"), el prompt NO debe obligar a inventar la
    categoría (caía a 'Otros' y borraba el detalle). Debe permitir campos en null
    y prohibir adivinar una categoría que el usuario no menciona.
    """
    assert "nunca inventes un valor" in _PROMPT
    assert "prohibido adivinar" in _PROMPT
    assert "solo infiere del contexto" in _PROMPT
    assert "si el usuario restablece" in _PROMPT


# ------------------------------------------------------------------
# REGLA E — Con transcripción correcta, la lógica acierta (caso "tejas")
# ------------------------------------------------------------------
@pytest.mark.anyio
async def test_regla_e_transcripcion_correcta_tejas_da_600():
    """
    Trampa E (caso dorado 9): documenta la limitación aceptada de Whisper. Cuando la
    transcripción ES correcta ('seis tejas'), la lógica debe devolver monto=600.
    Si Whisper transcribe mal ('seis cejas', 11/08/2026), es un error de oído de la
    capa de transcripción, NO de este servicio; esa variación queda aceptada.
    """
    mock_transaction_data = {
        "monto": 600,
        "categoria": "Servicios",
        "tipo_movimiento": "Gasto",
        "detalle": "Motor",
    }
    mock_response = AsyncMock()
    mock_response.choices = [AsyncMock(message=AsyncMock(parsed=mock_transaction_data))]

    with patch(
        "services.openai_service.openai_client.beta.chat.completions.parse",
        new_callable=AsyncMock,
    ) as mock_parse:
        mock_parse.return_value = mock_response

        resultado = await parse_financial_text(text_input="Me cobraron seis tejas por el motor")

        assert resultado["monto"] == 600
        assert resultado["tipo_movimiento"].lower() == "gasto"


# ------------------------------------------------------------------
# REGLA I — Monto 0 NO es un monto válido (hallazgo 20/08/2026)
# ------------------------------------------------------------------
def test_regla_i_monto_cero_no_es_monto_valido():
    """
    Trampa I (hallazgo 20/08/2026): un mensaje sin precio ('3 cajas de pañuelos')
    hacía que el LLM devolviera monto=0 en vez de null, y el sistema guardaba una
    transacción de 0 colones. Regla: el 0 no es un monto válido; si no se menciona
    dinero, monto va en null (y el pipeline pide el monto).
    """
    assert "0 (cero)" in _PROMPT
    assert "no es un monto válido" in _PROMPT
    assert "nunca lo inventes como 0" in _PROMPT
    assert "nunca registres una transacción" in _PROMPT


# ------------------------------------------------------------------
# REGLA J — Presupuesto/consulta NO es transacción (DUENO-16, fix 8.6.3)
# ------------------------------------------------------------------
_MENSAJE_NO_TRANSACCION = (
    "Eso todavía no lo llevo: presupuestos, topes y consultas no se "
    "guardan como gastos. Mandame el gasto real con monto y categoría "
    "y lo apunto."
)


def test_regla_j_contrato_no_transaccion_en_prompt():
    """
    Trampa J, contrato (DUENO-16, 29/09/2026): el prompt debe definir la intención
    'no_transaccion' para presupuestos, topes, límites y consultas, evaluada ANTES
    que las reglas de monto (el número de un presupuesto es una idea a futuro, no
    una transacción), y prohibir clasificar por palabra suelta (un gasto real que
    mencione 'presupuesto' sigue siendo 'registrar').
    """
    assert "no_transaccion" in _PROMPT
    assert "una idea a futuro, no es una transacción" in _PROMPT
    assert "esta regla se evalúa antes" in _PROMPT
    assert "no clasifiques por palabra suelta" in _PROMPT
    assert "gasté 2000 en carpeta presupuesto" in _PROMPT


def _consentimiento_aceptado():
    """Consentimiento aceptado con la versión vigente (igual que test_tasks.py)."""
    from services.politica_service import POLITICA_VERSION

    return {"estado": "aceptado", "version_politica": POLITICA_VERSION}


def test_regla_j_presupuesto_no_guarda_fila():
    """
    Trampa J, conducta (DUENO-16 B, 29/09/2026): "Presupuesto transporte 50000"
    creaba una fila falsa de -50000 Transporte. Con accion='no_transaccion' el
    pipeline responde ayuda y NO guarda ni corrige nada (0 filas).
    El test es hermético: no depende del `.env` ambiente (inexistente en CI), así que
    `settings` se mockea con token de prueba.
    """
    with (
        patch("workers.tasks.settings"),
        patch(
            "workers.tasks.transcribir_audio_whisper",
            return_value="Presupuesto transporte 50000",
        ),
        patch(
            "workers.tasks.obtener_consentimiento",
            return_value=_consentimiento_aceptado(),
        ),
        patch(
            "workers.tasks.parse_financial_text",
            return_value={"accion": "no_transaccion", "monto": None, "categoria": None},
        ),
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
        patch("workers.tasks.append_transaction_to_sheet") as mock_sheet,
        patch("workers.tasks.update_last_transaction_to_sheet") as mock_update,
        patch("workers.tasks.httpx.Client"),
        patch("workers.tasks.os.makedirs"),
        patch("workers.tasks.open", create=True),
    ):
        from workers.tasks import download_audio_task

        download_audio_task("12345", "50688888888")

        mock_sheet.assert_not_called()
        mock_update.assert_not_called()
        mock_whatsapp.assert_called_with(
            to_phone="50688888888",
            mensaje=_MENSAJE_NO_TRANSACCION,
        )


def test_regla_j_consulta_no_guarda_fila():
    """
    Trampa J, conducta (DUENO-16 A, 29/09/2026): "Cuánto gasté en este mes?"
    es una consulta, no dinero que entró o salió. 0 filas, respuesta de ayuda.
    El test es hermético: no depende del `.env` ambiente (inexistente en CI), así que
    `settings` se mockea con token de prueba.
    """
    with (
        patch("workers.tasks.settings"),
        patch(
            "workers.tasks.transcribir_audio_whisper",
            return_value="Cuánto gasté en este mes?",
        ),
        patch(
            "workers.tasks.obtener_consentimiento",
            return_value=_consentimiento_aceptado(),
        ),
        patch(
            "workers.tasks.parse_financial_text",
            return_value={"accion": "no_transaccion", "monto": None, "categoria": None},
        ),
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
        patch("workers.tasks.append_transaction_to_sheet") as mock_sheet,
        patch("workers.tasks.update_last_transaction_to_sheet") as mock_update,
        patch("workers.tasks.httpx.Client"),
        patch("workers.tasks.os.makedirs"),
        patch("workers.tasks.open", create=True),
    ):
        from workers.tasks import download_audio_task

        download_audio_task("12345", "50688888888")

        mock_sheet.assert_not_called()
        mock_update.assert_not_called()
        mock_whatsapp.assert_called_with(
            to_phone="50688888888",
            mensaje=_MENSAJE_NO_TRANSACCION,
        )


def test_regla_j_gasto_con_palabra_presupuesto_si_guarda():
    """
    Trampa J, control anti-ROMPE SI (fix 8.6.3): un gasto REAL que menciona la
    palabra 'presupuesto' ("gasté 2000 en carpeta presupuesto") SÍ se guarda.
    El fix clasifica por intención, no por palabra suelta.
    El test es hermético: no depende del `.env` ambiente (inexistente en CI), así que
    `settings` se mockea con token de prueba.
    """
    with (
        patch("workers.tasks.settings"),
        patch(
            "workers.tasks.transcribir_audio_whisper",
            return_value="gasté 2000 en carpeta presupuesto",
        ),
        patch(
            "workers.tasks.obtener_consentimiento",
            return_value=_consentimiento_aceptado(),
        ),
        patch(
            "workers.tasks.parse_financial_text",
            return_value={
                "accion": "registrar",
                "monto": 2000,
                "categoria": "Compras",
                "tipo_movimiento": "Gasto",
                "detalle": "carpeta presupuesto",
            },
        ),
        patch("workers.tasks.enviar_mensaje_whatsapp"),
        patch("workers.tasks.append_transaction_to_sheet") as mock_sheet,
        patch("workers.tasks.update_last_transaction_to_sheet"),
        patch("workers.tasks.httpx.Client"),
        patch("workers.tasks.os.makedirs"),
        patch("workers.tasks.open", create=True),
    ):
        from workers.tasks import download_audio_task

        download_audio_task("12345", "50688888888")

        mock_sheet.assert_called_once()
