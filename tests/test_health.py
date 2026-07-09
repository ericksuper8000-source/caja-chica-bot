import os


def test_environment_variables():
    # Verifica que nuestro conftest.py esté inyectando las variables correctamente
    assert (
        os.environ.get("DATABASE_URL")
        == "postgresql://postgres:password@localhost:5432/caja_chica_db"
    )
    assert os.environ.get("ENVIRONMENT") == "test"
