import time
from typing import Generator
from unittest.mock import AsyncMock
from fastapi.testclient import TestClient
import pytest
from app.main import app

# Importamos la función de seguridad real para poder sobrescribirla
from app.core.security import validar_firma_whatsapp

client = TestClient(app)


@pytest.fixture(autouse=True)
def override_security_dependency() -> Generator[AsyncMock, None, None]:
    """Inyecta un bypass automático de seguridad para los endpoints del test.

    Sobrescribe la dependencia real de FastAPI con un AsyncMock que no hace nada,
    permitiendo probar payloads simulados sin calcular firmas criptográficas reales.
    """
    mock_validator = AsyncMock()
    # Forzamos a FastAPI a usar nuestro mock en lugar de la función real
    app.dependency_overrides[validar_firma_whatsapp] = lambda: mock_validator
    yield mock_validator
    # Limpiamos los overrides después de cada test para no contaminar el entorno
    app.dependency_overrides.clear()


def test_environment_health() -> None:
    """Paso 0.6: Verifica que el endpoint de sanidad responda correctamente."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_verificar_webhook_handshake_exitoso() -> None:
    """Paso 1.1: Valida el handshake exitoso (GET) con el token correcto."""
    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": "mi_token_secreto_tico_123",
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
    """Paso 1.2 & 1.4: Simula la recepción de un payload válido de Meta.

    Verifica que la respuesta sea HTTP 200 OK en menos de 2 segundos.
    """
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
    assert response.json() == {
        "status": "recibido",
        "object": "whatsapp_business_account",
    }


def test_recibir_mensaje_webhook_payload_invalido() -> None:
    """Paso 1.2: Valida que estructuras JSON corruptas o incompletas

    sean rechazadas por la validación estricta de Pydantic (HTTP 422).
    """
    payload_invalido = {"objeto_incorrecto": "hack", "entry": []}
    response = client.post("/v1/whatsapp/webhook", json=payload_invalido)
    assert response.status_code == 422
