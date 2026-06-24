import sys
from unittest.mock import patch


def test_celery_inicializacion_correcta() -> None:
    """Verifica que la instancia global de Celery se configure

    correctamente con el nombre del proyecto y las URLs de los brokers.
    """
    # 1. Nos aseguramos de limpiar el caché de módulos para aislar el entorno
    if "app.config" in sys.modules:
        del sys.modules["app.config"]
    if "workers.celery_app" in sys.modules:
        del sys.modules["workers.celery_app"]

    # 2. Simulamos un entorno con las variables obligatorias ficticias para el test
    mock_env = {
        "WHATSAPP_VERIFY_TOKEN": "test_token",
        "WHATSAPP_API_TOKEN": "test_api",
        "WHATSAPP_PHONE_NUMBER_ID": "test_id",
        "OPENAI_API_KEY": "test_openai_key",
        "DATABASE_URL": "postgresql://user:pass@localhost/db",
        "REDIS_URL": "redis://localhost:6379/0",
    }

    with patch.dict("os.environ", mock_env, clear=True):
        # 3. Importamos el componente diferido dentro del contexto simulado
        from workers.celery_app import celery_app

        # 4. Aserciones de control estructural
        assert (
            celery_app.main == "caja_chica_workers"
        )  # <-- Cambiado de "workers" a "caja_chica_workers"
        assert celery_app.conf.broker_url == "redis://localhost:6379/0"
