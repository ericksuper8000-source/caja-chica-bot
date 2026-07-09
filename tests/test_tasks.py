import sys
import os
from unittest.mock import MagicMock, patch


def test_download_audio_task_exito() -> None:
    """Valida el flujo exitoso de la tarea asíncrona simulando las
    respuestas HTTP de Meta utilizando httpx.
    """
    # 1. Limpieza de módulos para forzar recarga en caso de ejecución múltiple
    if "app.config" in sys.modules:
        del sys.modules["app.config"]
    if "workers.tasks" in sys.modules:
        del sys.modules["workers.tasks"]

    # 2. Configuración del entorno
    # Se incluye APPDATA para satisfacer dependencias internas de gspread/oauth
    mock_env = {
        "WHATSAPP_VERIFY_TOKEN": "test_token",
        "WHATSAPP_API_TOKEN": "test_api",
        "WHATSAPP_PHONE_NUMBER_ID": "test_id",
        "OPENAI_API_KEY": "test_openai_key",
        "DATABASE_URL": "postgresql://user:pass@localhost/db",
        "REDIS_URL": "redis://localhost:6379/0",
        "APPDATA": os.environ.get("APPDATA", "C:\\temp"),
    }

    # 3. Patching sin borrar todo el entorno (evita KeyError)
    with patch.dict("os.environ", mock_env):
        from workers.tasks import download_audio_task

        with patch("workers.tasks.httpx.Client") as mock_client_class, patch(
            "workers.tasks.os.makedirs"
        ) as mock_makedirs, patch("workers.tasks.open", create=True) as mock_open:

            mock_client_instance = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_client_instance

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

            # Ejecución
            result_path = download_audio_task("12345")

            # Aserciones
            assert result_path == "/tmp/caja_chica/12345.ogg"
            assert mock_client_instance.get.call_count == 2
            mock_makedirs.assert_called_once_with("/tmp/caja_chica", exist_ok=True)
            mock_open.assert_called_once_with("/tmp/caja_chica/12345.ogg", "wb")
