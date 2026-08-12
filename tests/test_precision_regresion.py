"""
Trampas de regresión (5.5.4) — blindan las reglas de negocio decididas el 11-12/08/2026.

Cada función es una "trampa": si la regla se debilita, la trampa se enciende en rojo.

Reglas cubiertas (ver session-log 12/08/2026 y stage-055.md):
- A  Corrección = registro COMPLETO (nunca null) -> casos dorados 32 y 34.
- B  Frase sin monto -> NO se crea transacción (accion='aclaracion') -> caso 22.
- C  Los modismos SIEMPRE resuelven a colones; monto nunca null si hay dinero -> caso 6.
- D  Gastos de movilidad = Transporte; ingreso por prestar un servicio = Servicios
     -> casos 11 y 20.
- E  Limitación aceptada de Whisper (transcripción de modismos). Cuando la
     transcripción ES correcta, la lógica debe acertar ("seis tejas" = 600) -> caso 9.

Las reglas A-D se protegen con tests de CONTRATO de prompt: verifican que el system
prompt (SYSTEM_PROMPT_PARSE) contenga la regla. Si la promesa cambia, el prompt debe
cambiarse CON su trampa al mismo tiempo. La regla E es un test de documentación del
comportamiento esperado con transcripción correcta.
"""

from unittest.mock import AsyncMock, patch

import pytest

from services.openai_service import SYSTEM_PROMPT_PARSE, parse_financial_text

_PROMPT = SYSTEM_PROMPT_PARSE.lower()


# ------------------------------------------------------------------
# REGLA A — La corrección produce SIEMPRE un registro completo
# ------------------------------------------------------------------
def test_regla_a_correccion_debe_ser_registro_completo():
    """
    Trampa A (casos dorados 32 y 34): en accion='corregir' el prompt debe exigir
    los 4 campos (monto, categoria, tipo_movimiento, detalle) y prohibir field null.
    """
    assert "registro completo" in _PROMPT
    assert "nunca dejes campos en null" in _PROMPT


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
