import os
import pytest
from app.config import Settings


def test_config_loading() -> None:
    if os.getenv("ENVIRONMENT") == "test":
        pytest.skip("Requiere .env real con credenciales de WhatsApp")
    settings = Settings()
    assert settings.WHATSAPP_API_TOKEN != "", "WHATSAPP_API_TOKEN no está configurado"
    assert (
        settings.WHATSAPP_PHONE_NUMBER_ID != ""
    ), "WHATSAPP_PHONE_NUMBER_ID no está configurado"
