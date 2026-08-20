import csv
import io
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.config import settings
from services.backup_service import (
    BACKUP_FILE_PREFIX,
    BACKUP_FILENAME_RE,
    _nombre_backup,
    _sync_crear_backup,
    _sync_purge_backups,
    crear_backup,
)


# ==========================================
# FASE 6.5.5 — BACKUPS DEL SHEET (ADR-0014)
# ==========================================
def test_nombre_backup_formato_correcto() -> None:
    """El nombre del backup sigue el patrón caja-chica-backup-AAAAMMDD-HHMMSS.zip."""
    timestamp = datetime(2026, 8, 20, 23, 0, 0, tzinfo=UTC)
    nombre = _nombre_backup(timestamp)
    assert nombre == "caja-chica-backup-20260820-230000.zip"
    assert BACKUP_FILENAME_RE.match(nombre) is not None


def test_crear_backup_genera_zip_con_csv_por_pestana(tmp_path: Path) -> None:
    """Un spreadsheet de 2 pestañas genera un .zip con una CSV por pestaña + MANIFEST."""
    pestana_consentimiento = MagicMock()
    pestana_consentimiento.title = "Consentimiento"
    pestana_consentimiento.get_all_values.return_value = [
        ["telefono", "estado", "fecha", "version_politica"],
        ["50660646370", "aceptado", "2026-08-20 20:18:39", "1"],
    ]

    pestana_cliente = MagicMock()
    pestana_cliente.title = "50660646370"
    pestana_cliente.get_all_values.return_value = [
        ["fecha", "monto", "categoria", "detalle", "telefono"],
        ["2026-08-20 19:00:00", "-3000", "Alimentación", "Almuerzo", "50660646370"],
    ]

    spreadsheet = MagicMock()
    spreadsheet.id = "hoja_de_prueba_id"
    spreadsheet.title = "Caja Chica"
    spreadsheet.worksheets.return_value = [pestana_consentimiento, pestana_cliente]

    ruta = _sync_crear_backup(spreadsheet, tmp_path)

    assert ruta.exists()
    assert ruta.suffix == ".zip"
    assert ruta.name.startswith(BACKUP_FILE_PREFIX)

    with zipfile.ZipFile(ruta) as zip_fh:
        nombres = zip_fh.namelist()
        assert "Consentimiento.csv" in nombres
        assert "50660646370.csv" in nombres
        assert "MANIFEST.txt" in nombres

        # La CSV conserva exactamente las filas del sheet (incluyendo encabezados)
        with zip_fh.open("50660646370.csv") as fh:
            filas = list(csv.reader(io.TextIOWrapper(fh, encoding="utf-8")))
        assert filas[0] == ["fecha", "monto", "categoria", "detalle", "telefono"]
        assert filas[1][1] == "-3000"
        assert filas[1][3] == "Almuerzo"


def test_crear_backup_manifest_reporta_pestanas_y_filas(tmp_path: Path) -> None:
    """El MANIFEST registra la fecha, el spreadsheet y los conteos para poder auditar."""
    pestana = MagicMock()
    pestana.title = "Consentimiento"
    pestana.get_all_values.return_value = [
        ["telefono", "estado"],
        ["50660646370", "aceptado"],
    ]

    spreadsheet = MagicMock()
    spreadsheet.id = "hoja_manifest"
    spreadsheet.title = "Caja Chica"
    spreadsheet.worksheets.return_value = [pestana]

    ruta = _sync_crear_backup(spreadsheet, tmp_path)

    with zipfile.ZipFile(ruta) as zip_fh:
        manifest = zip_fh.read("MANIFEST.txt").decode("utf-8")

    assert "generado_utc=" in manifest
    assert "spreadsheet_id=hoja_manifest" in manifest
    assert "pestanas=1" in manifest
    assert "filas_totales=2" in manifest


def test_purge_elimina_viejos_y_conserva_recientes(tmp_path: Path) -> None:
    """Con retención de 90 días se borran los backups >90 días y se conservan los demás."""
    viejo = tmp_path / _nombre_backup(datetime.now(UTC) - timedelta(days=100))
    reciente = tmp_path / _nombre_backup(datetime.now(UTC) - timedelta(days=1))
    viejo.touch()
    reciente.touch()

    eliminados = _sync_purge_backups(tmp_path, retention_days=90)

    assert viejo in eliminados
    assert not viejo.exists()
    assert reciente.exists()
    assert reciente not in eliminados


def test_purge_no_toca_archivos_ajenos(tmp_path: Path) -> None:
    """Solo purga backups con nuestro patrón de nombre; otros archivos se conservan."""
    backup_viejo = tmp_path / _nombre_backup(datetime.now(UTC) - timedelta(days=200))
    backup_viejo.touch()
    ajeno = tmp_path / "notas_de_prueba.txt"
    ajeno.write_text("esto no es un backup", encoding="utf-8")

    _sync_purge_backups(tmp_path, retention_days=90)

    assert not backup_viejo.exists()
    assert ajeno.exists()


def test_purge_retencion_cero_no_elimina_nada(tmp_path: Path) -> None:
    """Retención <= 0 desactiva la purga (protección contra configs erróneas)."""
    viejo = tmp_path / _nombre_backup(datetime.now(UTC) - timedelta(days=500))
    viejo.touch()

    assert _sync_purge_backups(tmp_path, retention_days=0) == []
    assert viejo.exists()


@pytest.mark.anyio
async def test_crear_backup_async_genera_y_purga(tmp_path: Path) -> None:
    """crear_backup() orquesta: genera el .zip real en BACKUP_DIR y aplica la retención."""
    pestana = MagicMock()
    pestana.title = "Consentimiento"
    pestana.get_all_values.return_value = [["telefono", "estado"], ["50660646370", "aceptado"]]

    spreadsheet = MagicMock()
    spreadsheet.id = "hoja_async"
    spreadsheet.title = "Caja Chica"
    spreadsheet.worksheets.return_value = [pestana]

    mock_client = MagicMock()
    mock_client.open_by_key.return_value = spreadsheet

    viejo = tmp_path / _nombre_backup(datetime.now(UTC) - timedelta(days=100))
    viejo.touch()

    with (
        patch("services.backup_service.get_sheets_client", return_value=mock_client),
        patch.object(settings, "BACKUP_DIR", str(tmp_path)),
        patch.object(settings, "BACKUP_RETENTION_DAYS", 90),
    ):
        ruta = await crear_backup()

    assert ruta is not None
    assert ruta.parent == tmp_path
    assert ruta.exists()
    # El backup viejo (>90 días) fue purgado por la misma corrida
    assert not viejo.exists()


@pytest.mark.anyio
async def test_crear_backup_error_retorna_none(tmp_path: Path) -> None:
    """Si la API de Sheets falla, crear_backup devuelve None sin propagar la excepción."""
    mock_client = MagicMock()
    mock_client.open_by_key.side_effect = Exception("timeout de API")

    with (
        patch("services.backup_service.get_sheets_client", return_value=mock_client),
        patch.object(settings, "BACKUP_DIR", str(tmp_path)),
    ):
        ruta = await crear_backup()

    assert ruta is None
