import pytest
from unittest.mock import patch, AsyncMock
from services.whatsapp_service import enviar_mensaje_whatsapp


@pytest.mark.anyio
async def test_enviar_mensaje_whatsapp_exitoso():
    """Valida que la función maneja correctamente una respuesta exitosa."""
    # Creamos un mock para la respuesta del cliente
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"messages": [{"id": "123"}]}
    # Hacemos que raise_for_status sea una función que no hace nada (sin error)
    mock_response.raise_for_status = AsyncMock()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        resultado = await enviar_mensaje_whatsapp("50612345678", "Hola desde el test")

        assert resultado is True
        mock_post.assert_called_once()
        mock_response.raise_for_status.assert_called_once()
