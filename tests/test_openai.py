import os
from unittest.mock import AsyncMock, patch, MagicMock
import pytest

# 1. Inyectamos variables ficticias obligatorias en el entorno ANTES de importar el servicio
# Esto evita de forma matemática que PydanticSettings lance un ValidationError
mock_env = {
    "WHATSAPP_VERIFY_TOKEN": "test_token",
    "WHATSAPP_API_TOKEN": "test_api",
    "WHATSAPP_PHONE_NUMBER_ID": "test_id",
    "OPENAI_API_KEY": "test_openai_key",
    "DATABASE_URL": "postgresql://localhost/db",
    "REDIS_URL": "redis://localhost:6379/0",
}
with patch.dict("os.environ", mock_env):
    from services.openai_service import transcribir_audio_whisper


@pytest.mark.anyio
async def test_transcribir_audio_whisper_exito() -> None:
    """Valida que la función transcribir_audio_whisper lea el archivo local

    y devuelva el texto de forma correcta utilizando el cliente asíncrono mockeado.
    """
    # Simulamos que el archivo físico existe en el disco
    with patch("services.openai_service.os.path.exists", return_value=True), patch(
        "services.openai_service.open", create=True
    ) as mock_open:

        mock_file_instance = MagicMock()
        mock_open.return_value.__enter__.return_value = mock_file_instance

        # Estructura de respuesta simulada de OpenAI Whisper
        mock_transcription_response = MagicMock()
        mock_transcription_response.text = (
            "Mae, gasté 5 rojos en gasolina para el pickup de la empresa"
        )

        mock_create = AsyncMock(return_value=mock_transcription_response)

        with patch("services.openai_service.client.audio.transcriptions.create", mock_create):
            resultado = await transcribir_audio_whisper("/tmp/caja_chica/audio_test.ogg")

            assert resultado == "Mae, gasté 5 rojos en gasolina para el pickup de la empresa"
            mock_create.assert_called_once_with(
                model="whisper-1",
                file=mock_file_instance,
                language="es",
                prompt="Transcribe esta nota de voz sobre control de dinero, gastos, ingresos y finanzas de una pyme en Costa Rica. Ignora muletillas.",
            )


@pytest.mark.anyio
async def test_transcribir_audio_whisper_archivo_no_encontrado() -> None:
    """Verifica que la función levante un FileNotFoundError si el archivo

    de audio no existe en la ruta especificada.
    """
    with patch("services.openai_service.os.path.exists", return_value=False):
        with pytest.raises(FileNotFoundError) as exc_info:
            await transcribir_audio_whisper("/tmp/ruta_falsa/no_existente.ogg")

        assert "No se encontró el archivo de audio en la ruta" in str(exc_info.value)
