import sys
from unittest.mock import MagicMock, patch


def test_download_audio_task_exito() -> None:
    """Valida el flujo exitoso de la tarea asíncrona simulando las

    respuestas HTTP de Meta utilizando httpx.
    """
    if "app.config" in sys.modules:
        del sys.modules["app.config"]
    if "workers.tasks" in sys.modules:
        del sys.modules["workers.tasks"]

    mock_env = {
        "WHATSAPP_VERIFY_TOKEN": "test_token",
        "WHATSAPP_API_TOKEN": "test_api",
        "WHATSAPP_PHONE_NUMBER_ID": "test_id",
        "DATABASE_URL": "postgresql://user:pass@localhost/db",
        "REDIS_URL": "redis://localhost:6379/0",
    }

    with patch.dict("os.environ", mock_env, clear=True):
        from workers.tasks import download_audio_task

        # Parcheamos el cliente de httpx directamente dentro de workers.tasks
        with patch("workers.tasks.httpx.Client") as mock_client_class, patch(
            "workers.tasks.os.makedirs"
        ) as mock_makedirs, patch("workers.tasks.open", create=True) as mock_open:

            # Configuración del mock de cliente y las respuestas
            mock_client_instance = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_client_instance

            mock_response_meta = MagicMock()
            mock_response_meta.json.return_value = {
                "url": "https://cdn.facebook.com/m/audio.ogg"
            }

            mock_response_audio = MagicMock()
            mock_response_audio.content = b"fake_ogg_bytes"

            # Secuenciamos las respuestas del método .get() de httpx
            mock_client_instance.get.side_effect = [
                mock_response_meta,
                mock_response_audio,
            ]

            result_path = download_audio_task("12345")

            assert result_path == "/tmp/caja_chica/12345.ogg"
            assert mock_client_instance.get.call_count == 2
            mock_makedirs.assert_called_once_with("/tmp/caja_chica", exist_ok=True)
            mock_open.assert_called_once_with("/tmp/caja_chica/12345.ogg", "wb")
