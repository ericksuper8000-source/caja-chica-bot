import hashlib
import hmac
import json
import time
from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.security import validar_firma_whatsapp
from app.main import app

client = TestClient(app)

TEST_VERIFY_TOKEN = "***REDACTED_VERIFY_TOKEN***"


@pytest.fixture(autouse=True)
def override_security_dependency() -> Generator[AsyncMock, None, None]:
    """Inyecta un bypass automático de seguridad para los endpoints del test."""
    mock_validator = AsyncMock()
    app.dependency_overrides[validar_firma_whatsapp] = lambda: mock_validator
    with patch("app.main.TOKEN_VERIFICACION", TEST_VERIFY_TOKEN):
        yield mock_validator
    app.dependency_overrides.clear()


def test_environment_health() -> None:
    """Paso 0.6: Verifica que el endpoint de sanidad responda correctamente."""
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock()
    mock_redis.aclose = AsyncMock()

    with (
        patch("app.main.aioredis.from_url", return_value=mock_redis),
        patch("app.main.celery_app.control.ping", return_value=[{"worker1": "ok"}]),
    ):
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"redis": "ok", "celery": "ok", "status": "healthy"}


def test_verificar_webhook_handshake_exitoso() -> None:
    """Paso 1.1: Valida el handshake exitoso (GET) con el token correcto."""
    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": "***REDACTED_VERIFY_TOKEN***",
        "hub.challenge": "desafio_token_123",
    }
    response = client.get("/v1/whatsapp/webhook", params=params)
    assert response.status_code == 200
    assert response.text == "desafio_token_123"


def test_verificar_webhook_handshake_invalido() -> None:
    """Paso 1.1: Valida que un token incorrecto sea rechazado con HTTP 403."""
    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": "token_incorrecto_mae",
        "hub.challenge": "desafio_token_123",
    }
    response = client.get("/v1/whatsapp/webhook", params=params)
    assert response.status_code == 403
    assert response.json() == {"detail": "Token de verificación inválido"}


def test_recibir_mensaje_webhook_exitoso() -> None:
    """Paso 1.2 & 1.4: Simula la recepción de un payload válido de Meta."""
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "1234567890",
                "changes": [
                    {
                        "value": {"messaging_product": "whatsapp", "metadata": {}},
                        "field": "messages",
                    }
                ],
            }
        ],
    }

    start_time = time.time()
    response = client.post("/v1/whatsapp/webhook", json=payload)
    end_time = time.time()

    # Guardrail de velocidad de Meta API (< 2 segundos)
    assert end_time - start_time < 2.0
    assert response.status_code == 200
    # Corregido: La API ahora retorna solo {"status": "recibido"}
    assert response.json() == {"status": "recibido"}


def test_recibir_mensaje_webhook_payload_invalido() -> None:
    """Paso 1.2: Valida que estructuras JSON corruptas o incompletas sean rechazadas."""
    payload_invalido = {"objeto_incorrecto": "hack", "entry": []}
    response = client.post("/v1/whatsapp/webhook", json=payload_invalido)
    assert response.status_code == 422


def test_recibir_mensaje_texto_despacha_tarea() -> None:
    """Fase 6.5: un mensaje de TEXTO ('ACEPTO') se despacha al canal de consentimiento."""
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "1234567890",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {},
                            "messages": [
                                {
                                    "from": "50660646370",
                                    "id": "wamid.TEXTO01",
                                    "timestamp": "1724166000",
                                    "type": "text",
                                    "text": {"body": "ACEPTO"},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }

    with patch("app.main.procesar_mensaje_texto_task.delay") as mock_delay:
        response = client.post("/v1/whatsapp/webhook", json=payload)

    assert response.status_code == 200
    assert response.json() == {"status": "recibido"}
    mock_delay.assert_called_once_with("50660646370", "ACEPTO")


def test_recibir_mensaje_audio_no_despacha_texto() -> None:
    """Fase 6.5: un audio NO debe disparar la tarea de texto (solo la de descarga)."""
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "1234567890",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {},
                            "messages": [
                                {
                                    "from": "50660646370",
                                    "id": "wamid.AUDIO01",
                                    "timestamp": "1724166000",
                                    "type": "audio",
                                    "audio": {"id": "media_xyz", "mime_type": "audio/ogg"},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }

    with (
        patch("app.main.download_audio_task.delay") as mock_audio_delay,
        patch("app.main.procesar_mensaje_texto_task.delay") as mock_texto_delay,
    ):
        response = client.post("/v1/whatsapp/webhook", json=payload)

    assert response.status_code == 200
    mock_audio_delay.assert_called_once_with("media_xyz", "50660646370")
    mock_texto_delay.assert_not_called()


TEST_APP_SECRET = "test_hmac_secret_key_123"


def test_recibir_mensaje_firma_hmac_valida() -> None:
    """Valida que firma HMAC-SHA256 correcta permite acceso al endpoint."""
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "1234567890",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {},
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }

    payload_bytes = json.dumps(payload).encode("utf-8")
    firma = hmac.new(TEST_APP_SECRET.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()

    app.dependency_overrides.clear()

    with patch("app.core.security.APP_SECRET", TEST_APP_SECRET):
        response = client.post(
            "/v1/whatsapp/webhook",
            content=payload_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": f"sha256={firma}",
            },
        )

    assert response.status_code == 200
    assert response.json() == {"status": "recibido"}


def test_recibir_mensaje_firma_hmac_invalida() -> None:
    """Valida que firma HMAC incorrecta retorna HTTP 403."""
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "1234567890",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {},
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }

    payload_bytes = json.dumps(payload).encode("utf-8")
    firma_incorrecta = "a" * 64

    app.dependency_overrides.clear()

    with patch("app.core.security.APP_SECRET", TEST_APP_SECRET):
        response = client.post(
            "/v1/whatsapp/webhook",
            content=payload_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": f"sha256={firma_incorrecta}",
            },
        )

    assert response.status_code == 403
