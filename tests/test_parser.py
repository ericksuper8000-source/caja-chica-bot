import pytest
from unittest.mock import patch, AsyncMock

# Guardrail estricto: Mockeamos el entorno antes de importar la configuración de la app
with patch.dict(
    "os.environ",
    {
        "DATABASE_URL": "postgresql://postgres:postgres@localhost:5432/testdb",
        "WHATSAPP_API_TOKEN": "mock_token",
        "WHATSAPP_VERIFY_TOKEN": "mock_verify",
        "WHATSAPP_PHONE_NUMBER_ID": "12345",
        "OPENAI_API_KEY": "sk-mock-key-12345",
    },
):
    from services.openai_service import parse_financial_text


@pytest.mark.anyio
async def test_parse_financial_text_success():
    """
    Valida que el servicio de OpenAI extraiga correctamente las entidades estructuradas
    utilizando modismos ticos y devolviendo el modelo tipado esperado.
    """
    # 1. Definimos el mock de la respuesta estructurada de OpenAI
    mock_transaction_data = {
        "monto": 5000,
        "categoria": "Transporte",
        "tipo_movimiento": "Gasto",
        "detalle": "Pasajes de autobús",
    }

    # 2. Simulamos el comportamiento asíncrono del cliente de OpenAI
    mock_response = AsyncMock()
    mock_response.choices = [AsyncMock(message=AsyncMock(parsed=mock_transaction_data))]

    # 3. Ejecutamos la prueba interceptando la llamada real a OpenAI
    with patch(
        "services.openai_service.openai_client.beta.chat.completions.parse",
        new_callable=AsyncMock,
    ) as mock_parse:
        mock_parse.return_value = mock_response

        texto_usuario = "Mae, registrá 5 rojos de pasajes porfa"
        resultado = await parse_financial_text(text_input=texto_usuario)

        # 4. Aserciones estrictas de negocio (Costa Rica)
        assert resultado["monto"] == 5000
        assert resultado["categoria"] == "Transporte"
        assert resultado["tipo_movimiento"] == "Gasto"
        assert mock_parse.called


@pytest.mark.anyio
async def test_parse_financial_text_invalid_input():
    """
    Valida el comportamiento del sistema cuando el texto no contiene
    información financiera útil.
    """
    with patch(
        "services.openai_service.openai_client.beta.chat.completions.parse",
        new_callable=AsyncMock,
    ) as mock_parse:
        # Forzamos a que retorne None o un objeto vacío simulando que la IA no encontró nada
        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock(message=AsyncMock(parsed=None))]
        mock_parse.return_value = mock_response

        resultado = await parse_financial_text(text_input="Hola buenas tardes qué tal")
        assert resultado is None
