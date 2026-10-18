from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.whatsapp_service import (
    LIMITE_CAPTION_WHATSAPP,
    dividir_mensaje_largo,
    enviar_imagen_whatsapp,
    enviar_mensaje_whatsapp,
)


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


def _respuesta_meta(json_data: dict[str, object]) -> AsyncMock:
    respuesta = AsyncMock()
    respuesta.json = MagicMock(return_value=json_data)
    # raise_for_status de httpx es SÍNCRONO (el servicio lo llama sin await).
    respuesta.raise_for_status = MagicMock()
    return respuesta


@pytest.mark.anyio
async def test_enviar_imagen_whatsapp_subeyenvia() -> None:
    """Dos llamadas a Meta: subir el archivo (media) y enviar el mensaje tipo image."""
    subida = _respuesta_meta({"id": "media_123"})
    envio = _respuesta_meta({"messages": [{"id": "wamid.1"}]})

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = [subida, envio]

        resultado = await enviar_imagen_whatsapp("50612345678", b"\x89PNGdatos", "caption corto")

    assert resultado is True
    assert mock_post.await_count == 2
    subida_kwargs = mock_post.call_args_list[0].kwargs
    assert subida_kwargs["data"]["type"] == "image/png"
    assert subida_kwargs["files"]["file"][0] == "reporte.png"
    payload = mock_post.call_args_list[1].kwargs["json"]
    assert payload["type"] == "image"
    assert payload["image"] == {"id": "media_123", "caption": "caption corto"}


@pytest.mark.anyio
async def test_enviar_imagen_whatsapp_recorta_caption_al_limite() -> None:
    """WhatsApp rechaza captions de más de 1.024 caracteres: se recorta antes de enviar."""
    subida = _respuesta_meta({"id": "media_999"})
    envio = _respuesta_meta({"messages": [{"id": "wamid.2"}]})

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = [subida, envio]

        resultado = await enviar_imagen_whatsapp("50612345678", b"png", "x" * 2000)

    assert resultado is True
    caption = mock_post.call_args_list[1].kwargs["json"]["image"]["caption"]
    assert len(caption) == LIMITE_CAPTION_WHATSAPP


@pytest.mark.anyio
async def test_enviar_imagen_whatsapp_sin_media_id_devuelve_false() -> None:
    """Si Meta no devuelve media_id no se intenta mandar el mensaje (y no lanza)."""
    subida = _respuesta_meta({})

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = [subida]

        resultado = await enviar_imagen_whatsapp("50612345678", b"png", "x")

    assert resultado is False
    assert mock_post.await_count == 1


@pytest.mark.anyio
async def test_enviar_imagen_whatsapp_error_devuelve_false() -> None:
    """Rompe-si: cualquier fallo de red se degrada a False (el pipeline cae a texto)."""
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = RuntimeError("sin red")

        resultado = await enviar_imagen_whatsapp("50612345678", b"png", "x")

    assert resultado is False
