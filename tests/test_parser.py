import pytest
from unittest.mock import patch, AsyncMock, MagicMock

# Guardrail estricto: Mockeamos el entorno
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

def create_mock_parsed_response(data: dict) -> MagicMock:
    """Helper para simular un objeto Pydantic que responde a .model_dump()"""
    mock_obj = MagicMock()
    mock_obj.model_dump.return_value = data
    return mock_obj

@pytest.mark.anyio
async def test_parse_financial_text_success():
    data = {"monto": 5000, "categoria": "Transporte", "tipo_movimiento": "Gasto", "detalle": "Pasajes de autobús"}
    mock_response = AsyncMock()
    mock_response.choices = [AsyncMock(message=AsyncMock(parsed=create_mock_parsed_response(data)))]

    with patch("services.openai_service.openai_client.beta.chat.completions.parse", new_callable=AsyncMock) as mock_parse:
        mock_parse.return_value = mock_response
        resultado = await parse_financial_text(text_input="Mae, registrá 5 rojos de pasajes porfa")
        
        assert resultado["monto"] == 5000
        assert mock_parse.called

@pytest.mark.anyio
async def test_parse_financial_text_invalid_input():
    with patch("services.openai_service.openai_client.beta.chat.completions.parse", new_callable=AsyncMock) as mock_parse:
        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock(message=AsyncMock(parsed=None))]
        mock_parse.return_value = mock_response

        resultado = await parse_financial_text(text_input="Hola buenas tardes qué tal")
        assert resultado is None

@pytest.mark.anyio
async def test_extraccion_modismos_ticos_rojos():
    data = {"monto": 3000, "categoria": "Transporte", "tipo_movimiento": "Gasto", "detalle": "pasaje del bus"}
    mock_response = AsyncMock()
    mock_response.choices = [AsyncMock(message=AsyncMock(parsed=create_mock_parsed_response(data)))]

    with patch("services.openai_service.openai_client.beta.chat.completions.parse", new_callable=AsyncMock) as mock_parse:
        mock_parse.return_value = mock_response
        resultado = await parse_financial_text(text_input="Mae, apunte ahí que se me fueron 3 rojos en el pasaje del bus")
        assert resultado["monto"] == 3000

@pytest.mark.anyio
async def test_extraccion_modismos_ticos_tucan():
    data = {"monto": 10000, "categoria": "Ingresos", "tipo_movimiento": "Ingreso", "detalle": "brete que le hice al vecino"}
    mock_response = AsyncMock()
    mock_response.choices = [AsyncMock(message=AsyncMock(parsed=create_mock_parsed_response(data)))]

    with patch("services.openai_service.openai_client.beta.chat.completions.parse", new_callable=AsyncMock) as mock_parse:
        mock_parse.return_value = mock_response
        resultado = await parse_financial_text(text_input="Me entró un tucán por el brete que le hice al vecino")
        assert resultado["monto"] == 10000

@pytest.mark.anyio
async def test_extraccion_modismos_ticos_tejas():
    data = {"monto": 500, "categoria": "Alimentación", "tipo_movimiento": "Gasto", "detalle": "empanada en la pulpería"}
    mock_response = AsyncMock()
    mock_response.choices = [AsyncMock(message=AsyncMock(parsed=create_mock_parsed_response(data)))]

    with patch("services.openai_service.openai_client.beta.chat.completions.parse", new_callable=AsyncMock) as mock_parse:
        mock_parse.return_value = mock_response
        resultado = await parse_financial_text(text_input="Gasté 5 tejas en una empanada en la pulpería")
        assert resultado["monto"] == 500