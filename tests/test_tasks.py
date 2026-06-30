import sys
from unittest.mock import MagicMock, patch


def test_download_audio_task_exito() -> None:
    """Valida el flujo exitoso de la tarea asíncrona."""
    if "app.config" in sys.modules:
        del sys.modules["app.config"]
    if "workers.tasks" in sys.modules:
        del sys.modules["workers.tasks"]

    mock_env = {
        "WHATSAPP_VERIFY_TOKEN": "test_token",
        "WHATSAPP_API_TOKEN": "test_api",
        "WHATSAPP_PHONE_NUMBER_ID": "test_id",
        "OPENAI_API_KEY": "test_openai_key",
        "DATABASE_URL": "postgresql://user:pass@localhost/db",
        "REDIS_URL": "redis://localhost:6379/0",
    }

    with patch.dict("os.environ", mock_env, clear=True):
        from workers.tasks import download_audio_task

        # Usamos '_' para los mocks que no se referencian explícitamente en el cuerpo del test
        with patch("workers.tasks.httpx.AsyncClient") as mock_client_class, patch(
            "workers.tasks.os.makedirs"
        ) as mock_makedirs, patch(
            "workers.tasks.open", create=True
        ) as mock_open, patch(
            "workers.tasks.procesar_audio_a_transaccion"
        ) as mock_ia, patch(
            "workers.tasks.append_transaction_to_sheet"
        ) as _, patch(
            "workers.tasks.enviar_mensaje_whatsapp"
        ) as _:

            mock_client_instance = (
                mock_client_class.return_value.__aenter__.return_value
            )

            mock_response_meta = MagicMock()
            mock_response_meta.json.return_value = {
                "url": "https://cdn.facebook.com/m/audio.ogg"
            }

            mock_response_audio = MagicMock()
            mock_response_audio.content = b"fake_ogg_bytes"

            mock_client_instance.get.side_effect = [
                mock_response_meta,
                mock_response_audio,
            ]

            result = download_audio_task("12345", "50600000000")

            assert result == "Pipeline ejecutado con éxito"
            assert mock_client_instance.get.call_count == 2
            mock_makedirs.assert_called_once_with("/tmp/caja_chica", exist_ok=True)
            mock_open.assert_called_once_with("/tmp/caja_chica/12345.ogg", "wb")
            assert mock_ia.called is True
