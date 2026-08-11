import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

EXPECTED_DIR = os.path.join(tempfile.gettempdir(), "caja_chica")
EXPECTED_PATH = os.path.join(EXPECTED_DIR, "12345.ogg")


def test_download_audio_task_exito() -> None:
    """Valida el flujo exitoso de la tarea asíncrona simulando las
    respuestas HTTP de Meta utilizando httpx.
    """
    # 1. Limpieza de módulos para forzar recarga
    if "app.config" in sys.modules:
        del sys.modules["app.config"]
    if "workers.tasks" in sys.modules:
        del sys.modules["workers.tasks"]

    # 2. Configuración del entorno
    mock_env = {
        "WHATSAPP_VERIFY_TOKEN": "test_token",
        "WHATSAPP_API_TOKEN": "test_api",
        "WHATSAPP_PHONE_NUMBER_ID": "test_id",
        "OPENAI_API_KEY": "test_openai_key",
        "DATABASE_URL": "postgresql://user:pass@localhost/db",
        "REDIS_URL": "redis://localhost:6379/0",
        "APPDATA": os.environ.get("APPDATA", "C:\\temp"),
    }

    # 3. Ejecución con patching
    with patch.dict("os.environ", mock_env):
        from workers.tasks import download_audio_task

        with (
            patch("workers.tasks.httpx.Client") as mock_client_class,
            patch("workers.tasks.os.makedirs") as mock_makedirs,
            patch("workers.tasks.open", create=True) as mock_open,
            patch(
                "workers.tasks.transcribir_audio_whisper",
                return_value="transcripcion de prueba",
            ),
            patch(
                "workers.tasks.parse_financial_text",
                return_value={
                    "categoria": "comida",
                    "monto": 5000,
                },
            ),
            patch("workers.tasks.append_transaction_to_sheet") as mock_sheet,
            patch("workers.tasks.enviar_mensaje_whatsapp", create=True) as mock_whatsapp,
        ):

            mock_client_instance = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_client_instance

            mock_response_meta = MagicMock()
            mock_response_meta.json.return_value = {"url": "https://cdn.facebook.com/m/audio.ogg"}

            mock_response_audio = MagicMock()
            mock_response_audio.content = b"fake_ogg_bytes"

            mock_client_instance.get.side_effect = [
                mock_response_meta,
                mock_response_audio,
            ]

            # Ejecución actualizada con sender_phone
            test_sender = "50688888888"
            result_path = download_audio_task("12345", test_sender)

            # Aserciones
            assert result_path == EXPECTED_PATH
            assert mock_client_instance.get.call_count == 2
            expected_headers = {"Authorization": "Bearer test_api"}
            assert all(
                call.kwargs.get("headers") == expected_headers
                for call in mock_client_instance.get.call_args_list
            )
            mock_makedirs.assert_called_once_with(EXPECTED_DIR, exist_ok=True)
            mock_open.assert_called_once_with(EXPECTED_PATH, "wb")

            # Verificamos que el mensaje se envió al número correcto
            mock_whatsapp.assert_called_once()
            call_kwargs = mock_whatsapp.call_args.kwargs
            assert call_kwargs["to_phone"] == test_sender

            # Verificamos que la transacción se guardó con el teléfono del remitente
            mock_sheet.assert_called_once_with({"categoria": "comida", "monto": 5000}, test_sender)


def test_download_audio_task_whisper_falla() -> None:
    """Verifica que si Whisper falla, envía mensaje de error y no intenta parsear."""
    with (
        patch("workers.tasks.transcribir_audio_whisper", return_value=None),
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
        patch("workers.tasks.parse_financial_text") as mock_parser,
        patch("workers.tasks.httpx.Client"),
        patch("workers.tasks.os.makedirs"),
        patch("workers.tasks.open", create=True),
    ):

        from workers.tasks import download_audio_task

        # Ejecución
        result = download_audio_task("12345", "50688888888")

        # Aserciones
        assert result == EXPECTED_PATH
        mock_whatsapp.assert_called_with(
            to_phone="50688888888",
            mensaje="No entendí el audio. Por favor, intentá de nuevo con más claridad.",
        )
        mock_parser.assert_not_called()


def test_download_audio_task_parse_falla() -> None:
    """Verifica que si el parser falla, envía mensaje de error y no guarda en Sheet."""
    with (
        patch("workers.tasks.transcribir_audio_whisper", return_value="texto valido"),
        patch("workers.tasks.parse_financial_text", return_value=None),
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
        patch("workers.tasks.append_transaction_to_sheet") as mock_sheet,
        patch("workers.tasks.httpx.Client"),
        patch("workers.tasks.os.makedirs"),
        patch("workers.tasks.open", create=True),
    ):

        from workers.tasks import download_audio_task

        # Ejecución
        result = download_audio_task("12345", "50688888888")

        # Aserciones
        assert result == EXPECTED_PATH
        mock_whatsapp.assert_called_with(
            to_phone="50688888888",
            mensaje=(
                "No encontré datos financieros en tu mensaje. "
                "Intentá de nuevo indicando monto, categoría y si es gasto o ingreso."
            ),
        )
        mock_sheet.assert_not_called()


def test_download_audio_task_whisper_no_rompe_flujo_exitoso() -> None:
    """Valida que el flujo exitoso sigue funcionando como antes."""
    with (
        patch("workers.tasks.transcribir_audio_whisper", return_value="texto"),
        patch("workers.tasks.parse_financial_text", return_value={"categoria": "A", "monto": 100}),
        patch("workers.tasks.append_transaction_to_sheet"),
        patch("workers.tasks.enviar_mensaje_whatsapp"),
        patch("workers.tasks.httpx.Client"),
        patch("workers.tasks.os.makedirs"),
        patch("workers.tasks.open", create=True),
    ):

        from workers.tasks import download_audio_task

        result = download_audio_task("12345", "50688888888")
        assert result == EXPECTED_PATH
