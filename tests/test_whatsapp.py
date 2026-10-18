from unittest.mock import AsyncMock, patch

import pytest

from services.whatsapp_service import dividir_mensaje_largo, enviar_mensaje_whatsapp


def test_dividir_mensaje_vacio():
    """Texto vacío → sin bloques."""
    assert dividir_mensaje_largo("") == []


def test_dividir_mensaje_corto_en_un_bloque():
    """Texto que cabe en el límite → un solo bloque idéntico."""
    texto = "Estos son tus movimientos:\nlinea uno\nlinea dos"
    assert dividir_mensaje_largo(texto) == [texto]


def test_dividir_mensaje_largo_por_lineas():
    """Texto largo → varios bloques, cada uno <= límite, contenido intacto."""
    lineas = [f"movimiento numero {i:03d} de prueba" for i in range(200)]
    texto = "\n".join(lineas)

    bloques = dividir_mensaje_largo(texto, limite=100)

    assert len(bloques) > 1
    assert all(len(bloque) <= 100 for bloque in bloques)
    assert "\n".join(bloques) == texto


def test_dividir_linea_mas_larga_que_limite():
    """Una línea sola más larga que el límite se parte en seco."""
    texto = "x" * 250

    bloques = dividir_mensaje_largo(texto, limite=100)

    assert [len(bloque) for bloque in bloques] == [100, 100, 50]
    assert "".join(bloques) == texto


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
