import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from services.openai_service import transcribir_audio_whisper

@pytest.mark.anyio
async def test_transcribir_audio_whisper_exito() -> None:
    """Valida que la función transcribir_audio_whisper lea el archivo local
    y devuelva el texto de forma correcta utilizando el cliente asíncrono.
    """
    with patch("services.openai_service.os.path.exists", return_value=True), patch(
        "services.openai_service.open", create=True
    ) as mock_open:

        mock_file_instance = MagicMock()
        mock_open.return_value.__enter__.return_value = mock_file_instance

        mock_transcription_response = MagicMock()
        mock_transcription_response.text = (
            "Mae, gasté 5 rojos en gasolina para el pickup de la empresa"
        )

        mock_create = AsyncMock(return_value=mock_transcription_response)

        # Apuntamos a openai_client.audio.transcriptions.create
        with patch(
            "services.openai_service.openai_client.audio.transcriptions.create",
            mock_create,
        ):
            resultado = await transcribir_audio_whisper("/tmp/test_audio.ogg")
            assert (
                resultado
                == "Mae, gasté 5 rojos en gasolina para el pickup de la empresa"
            )


@pytest.mark.anyio
async def test_transcribir_audio_whisper_archivo_no_encontrado() -> None:
    """Verifica que la función retorne None si el archivo de audio no existe."""
    with patch("services.openai_service.os.path.exists", return_value=False):
        resultado = await transcribir_audio_whisper("/tmp/ruta_falsa/no_existente.ogg")
        assert resultado is None