"""
Tests de métricas operativas (Paso 1): conteo de backups y endpoint `/metrics`.
No exponen datos de clientes; solo uptime, entorno y archivos de respaldo.
"""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from services.backup_service import _nombre_backup
from services.metricas_service import contar_backups

client = TestClient(app)


def test_contar_backups_vacio(tmp_path: Path) -> None:
    assert contar_backups(tmp_path) == {
        "total": 0,
        "ultimo": None,
        "ultimo_tamano_bytes": 0,
    }


def test_contar_backups_orden_por_nombre_e_ignora_ajenos(tmp_path: Path) -> None:
    viejo = tmp_path / _nombre_backup(datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC))
    nuevo = tmp_path / _nombre_backup(datetime(2026, 11, 8, 20, 0, 0, tzinfo=UTC))
    viejo.write_bytes(b"viejo")
    nuevo.write_bytes(b"nuevo")
    (tmp_path / "notas.txt").write_text("no es un backup", encoding="utf-8")

    resultado = contar_backups(tmp_path)

    assert resultado["total"] == 2
    assert resultado["ultimo"] == nuevo.name
    assert resultado["ultimo_tamano_bytes"] == len(b"nuevo")


def test_metrics_endpoint_expone_uptime_y_backups(tmp_path: Path) -> None:
    ruta = tmp_path / _nombre_backup(datetime(2026, 11, 8, 20, 0, 0, tzinfo=UTC))
    ruta.write_bytes(b"backup")

    with patch.object(settings, "BACKUP_DIR", str(tmp_path)):
        respuesta = client.get("/metrics")

    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert "uptime_segundos" in datos
    assert datos["entorno"] == settings.ENVIRONMENT
    assert datos["backups"]["total"] == 1
    assert datos["backups"]["ultimo"] == ruta.name
