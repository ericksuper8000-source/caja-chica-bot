import hashlib
import hmac


SECRET_TEST = "test_secret_clave_123"


def test_hmac_firma_se_calcula_correctamente() -> None:
    """Valida que HMAC-SHA256 produce un hash hex de 64 caracteres."""
    payload = (
        b'{"object": "whatsapp_business_account", '
        b'"entry": [{"changes": [{"value": {"messages": '
        b'[{"type": "audio", "audio": {"id": "TEST_MEDIA_123"}, '
        b'"from": "123456789"}]}}]}]}'
    )

    firma = hmac.new(
        SECRET_TEST.encode("utf-8"), payload, hashlib.sha256
    ).hexdigest()

    assert len(firma) == 64
    assert all(c in "0123456789abcdef" for c in firma)


def test_hmac_firma_es_determinista() -> None:
    """Valida que los mismos inputs producen la misma firma."""
    payload = b'{"dato": "test"}'

    firma_a = hmac.new(
        SECRET_TEST.encode("utf-8"), payload, hashlib.sha256
    ).hexdigest()
    firma_b = hmac.new(
        SECRET_TEST.encode("utf-8"), payload, hashlib.sha256
    ).hexdigest()

    assert firma_a == firma_b


def test_hmac_firma_cambia_con_diferente_payload() -> None:
    """Valida que payloads diferentes generan firmas distintas."""
    payload_a = b'{"dato": "uno"}'
    payload_b = b'{"dato": "dos"}'

    firma_a = hmac.new(
        SECRET_TEST.encode("utf-8"), payload_a, hashlib.sha256
    ).hexdigest()
    firma_b = hmac.new(
        SECRET_TEST.encode("utf-8"), payload_b, hashlib.sha256
    ).hexdigest()

    assert firma_a != firma_b


def test_hmac_firma_cambia_con_diferente_secret() -> None:
    """Valida que secrets diferentes generan firmas distintas."""
    payload = b'{"dato": "test"}'

    firma_a = hmac.new(b"secret_uno", payload, hashlib.sha256).hexdigest()
    firma_b = hmac.new(b"secret_dos", payload, hashlib.sha256).hexdigest()

    assert firma_a != firma_b
