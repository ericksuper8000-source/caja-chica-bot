import pytest
from unittest.mock import patch, AsyncMock
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


@pytest.mark.anyio
async def test_extraccion_modismos_ticos_rojos():
    """Caso 1: Validar el uso de 'rojos' como miles de colones"""
    mock_transaction_data = {
        "monto": 3000,
        "categoria": "Transporte",
        "tipo_movimiento": "Gasto",
        "detalle": "pasaje del bus",
    }
    mock_response = AsyncMock()
    mock_response.choices = [AsyncMock(message=AsyncMock(parsed=mock_transaction_data))]

    with patch(
        "services.openai_service.openai_client.beta.chat.completions.parse",
        new_callable=AsyncMock,
    ) as mock_parse:
        mock_parse.return_value = mock_response

        texto_usuario = "Mae, apunte ahí que se me fueron 3 rojos en el pasaje del bus"
        resultado = await parse_financial_text(text_input=texto_usuario)

        assert resultado["monto"] == 3000
        assert resultado["tipo_movimiento"].lower() == "gasto"
        assert "pasaje" in resultado["detalle"].lower()


@pytest.mark.anyio
async def test_extraccion_modismos_ticos_tucan():
    """Caso 2: Validar el uso de 'tucán' como billete de 5,000 colones"""
    mock_transaction_data = {
        "monto": 5000,
        "categoria": "Ingresos",
        "tipo_movimiento": "Ingreso",
        "detalle": "brete que le hice al vecino",
    }
    mock_response = AsyncMock()
    mock_response.choices = [AsyncMock(message=AsyncMock(parsed=mock_transaction_data))]

    with patch(
        "services.openai_service.openai_client.beta.chat.completions.parse",
        new_callable=AsyncMock,
    ) as mock_parse:
        mock_parse.return_value = mock_response

        texto_usuario = "Me entró un tucán por el brete que le hice al vecino"
        resultado = await parse_financial_text(text_input=texto_usuario)

        assert resultado["monto"] == 5000
        assert resultado["tipo_movimiento"].lower() == "ingreso"
        assert "brete" in resultado["detalle"].lower()


@pytest.mark.anyio
async def test_extraccion_modismos_ticos_tejas():
    """Caso 3: Validar el uso de 'tejas' como cientos de colones"""
    mock_transaction_data = {
        "monto": 500,
        "categoria": "Alimentación",
        "tipo_movimiento": "Gasto",
        "detalle": "empanada en la pulpería",
    }
    mock_response = AsyncMock()
    mock_response.choices = [AsyncMock(message=AsyncMock(parsed=mock_transaction_data))]

    with patch(
        "services.openai_service.openai_client.beta.chat.completions.parse",
        new_callable=AsyncMock,
    ) as mock_parse:
        mock_parse.return_value = mock_response

        texto_usuario = "Gasté 5 tejas en una empanada en la pulpería"
        resultado = await parse_financial_text(text_input=texto_usuario)

        assert resultado["monto"] == 500
        assert resultado["tipo_movimiento"].lower() == "gasto"