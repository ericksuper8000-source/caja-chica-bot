import os
import pytest
from app.config import Settings


@pytest.mark.skipif(
    os.getenv("ENVIRONMENT") == "test",
    reason="Requiere .env real con credenciales de WhatsApp",
)
def test_config_loading() -> None:
    settings = Settings()
    assert settings.WHATSAPP_API_TOKEN != "", "WHATSAPP_API_TOKEN no está configurado"
    assert (
        settings.WHATSAPP_PHONE_NUMBER_ID != ""
    ), "WHATSAPP_PHONE_NUMBER_ID no está configurado"
