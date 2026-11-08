import asyncio
import csv
import io
import logging
import re
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import gspread
from gspread.utils import ValueInputOption, rowcol_to_a1

from app.config import settings
from services.sheets_service import get_sheets_client

logger = logging.getLogger(__name__)

# Fase 6.5.5 — Backups del sheet (ADR-0014). El sheet es hoy el único almacén de datos
# (transacciones por pestaña + consentimientos); un borrado o corrupción sin respaldo
# significaría pérdida de dinero del cliente. La solución es una copia local diaria:
# una CSV por pestaña + un MANIFEST.txt, empaquetados en un .zip con marca de tiempo.
# Diseñado para que el destino sea intercambiable (hoy /backups local, mañana un bucket)
# sin tocar la tarea programada.
BACKUP_FILE_PREFIX = "caja-chica-backup-"
BACKUP_FILENAME_RE = re.compile(rf"^{BACKUP_FILE_PREFIX}(\d{{8}})-(\d{{6}})\.zip$")


def _nombre_backup(timestamp: datetime) -> str:
    """Construye el nombre del archivo de backup: caja-chica-backup-AAAAMMDD-HHMMSS.zip."""
    return f"{BACKUP_FILE_PREFIX}{timestamp.strftime('%Y%m%d-%H%M%S')}.zip"


def _sync_crear_backup(spreadsheet: Any, backup_dir: Path) -> Path:
    """
    Operación síncrona (para correr en asyncio.to_thread): genera una copia completa del
    spreadsheet —una CSV por pestaña + MANIFEST.txt— empaquetada en un .zip nombrado con
    la fecha/hora UTC. Crea el directorio si no existe y devuelve la ruta del archivo.
    """
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(UTC)
    nombre = _nombre_backup(timestamp)
    ruta = backup_dir / nombre

    worksheets = spreadsheet.worksheets()
    with zipfile.ZipFile(ruta, "w", compression=zipfile.ZIP_DEFLATED) as zip_fh:
        total_filas = 0
        for worksheet in worksheets:
            nombre_csv = f"{worksheet.title}.csv"
            filas = worksheet.get_all_values()
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerows(filas)
            zip_fh.writestr(nombre_csv, buffer.getvalue().encode("utf-8"))
            total_filas += len(filas)

        manifest = "\n".join(
            [
                "backup_caja_chica",
                f"generado_utc={timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
                f"spreadsheet_id={spreadsheet.id}",
                f"spreadsheet_title={spreadsheet.title}",
                f"pestanas={len(worksheets)}",
                f"filas_totales={total_filas}",
            ]
        )
        zip_fh.writestr("MANIFEST.txt", manifest)

    logger.info(f"Backup del sheet generado: {ruta} ({len(worksheets)} pestañas).")
    return ruta


def _sync_purge_backups(backup_dir: Path, retention_days: int) -> list[Path]:
    """
    Operación síncrona: elimina los backups más viejos que `retention_days` días (por la
    fecha del NOMBRE, no por mtime, que se altera al copiar). Devuelve los archivos
    eliminados. Conserva el resto sin tocarlo.
    """
    if retention_days <= 0:
        return []

    cutoff = datetime.now(UTC).date() - timedelta(days=retention_days)
    eliminados: list[Path] = []
    for ruta in backup_dir.glob(f"{BACKUP_FILE_PREFIX}*.zip"):
        match = BACKUP_FILENAME_RE.match(ruta.name)
        if not match:
            continue
        try:
            fecha_backup = datetime.strptime(match.group(1), "%Y%m%d").date()
        except ValueError:
            continue
        if fecha_backup < cutoff:
            try:
                ruta.unlink()
                eliminados.append(ruta)
            except OSError as e:
                logger.warning(f"No se pudo eliminar backup viejo {ruta}: {e}")
    if eliminados:
        logger.info(f"Backups purgados (retención {retention_days} días): {len(eliminados)}.")
    return eliminados


def _sync_leer_backup(ruta: Path) -> dict[str, Any]:
    """
    Lee un .zip de backup y devuelve su MANIFEST y sus hojas como listas de filas.

    No escribe nada: es la base de la verificación y del dry-run de restauración.
    """
    if not ruta.exists():
        raise FileNotFoundError(f"no existe el backup: {ruta}")
    with zipfile.ZipFile(ruta) as zip_fh:
        nombres = zip_fh.namelist()
        if "MANIFEST.txt" not in nombres:
            raise ValueError("el backup no contiene MANIFEST.txt")
        manifest: dict[str, str] = {}
        for linea in zip_fh.read("MANIFEST.txt").decode("utf-8").splitlines():
            if "=" in linea:
                clave, valor = linea.split("=", 1)
                manifest[clave.strip()] = valor.strip()

        hojas: dict[str, list[list[str]]] = {}
        for nombre in nombres:
            if not nombre.endswith(".csv"):
                continue
            with zip_fh.open(nombre) as fh:
                lector = csv.reader(io.TextIOWrapper(fh, encoding="utf-8"))
                hojas[nombre[:-4]] = [list(fila) for fila in lector]
    return {"manifest": manifest, "hojas": hojas}


def verificar_backup(ruta: Path) -> dict[str, Any]:
    """
    Verifica que un backup se pueda leer y que sus conteos coincidan con el MANIFEST.

    Devuelve un reporte apto para operación: `valido`, cantidad de pestañas/filas,
    manifest y errores. Un backup que no concilia no se debe usar para restaurar.
    """
    try:
        contenido = _sync_leer_backup(ruta)
        manifest = contenido["manifest"]
        hojas = contenido["hojas"]
        filas = sum(len(hoja) for hoja in hojas.values())
        errores: list[str] = []

        if not hojas:
            errores.append("sin_hojas")
        if "pestanas" not in manifest:
            errores.append("manifest_sin_pestanas")
        elif int(manifest["pestanas"]) != len(hojas):
            errores.append("pestanas_no_coinciden")
        if "filas_totales" not in manifest:
            errores.append("manifest_sin_filas")
        elif int(manifest["filas_totales"]) != filas:
            errores.append("filas_no_coinciden")

        return {
            "valido": not errores,
            "pestanas": len(hojas),
            "filas": filas,
            "manifest": manifest,
            "errores": errores,
        }
    except Exception as error:  # noqa: BLE001 - un backup roto no debe tumbar el proceso
        logger.error("Backup inválido %s: %s", ruta, error)
        return {
            "valido": False,
            "pestanas": 0,
            "filas": 0,
            "manifest": {},
            "errores": [type(error).__name__],
        }


def _sync_restaurar_en_worksheet(worksheet: Any, filas: list[list[Any]]) -> None:
    """Reemplaza el contenido de una pestaña con las filas de un backup."""
    worksheet.clear()
    if not filas:
        return
    ancho = max(len(fila) for fila in filas)
    normalizadas = [list(fila) + [""] * (ancho - len(fila)) for fila in filas]
    rango = f"A1:{rowcol_to_a1(len(normalizadas), ancho)}"
    worksheet.update(
        rango,
        normalizadas,
        value_input_option=ValueInputOption.user_entered,
    )


async def restaurar_backup(ruta: Path, spreadsheet: Any, *, dry_run: bool = True) -> dict[str, Any]:
    """
    Restaura un backup en un spreadsheet.

    `dry_run=True` (default) solo lee y cuenta: nunca escribe. Para restaurar de verdad
    hay que pasar `dry_run=False` y usar SIEMPRE una copia del spreadsheet, no producción.
    """
    contenido = await asyncio.to_thread(_sync_leer_backup, ruta)
    hojas = contenido["hojas"]
    filas_totales = sum(len(filas) for filas in hojas.values())
    if dry_run:
        return {
            "restaurado": False,
            "dry_run": True,
            "pestanas": len(hojas),
            "filas": filas_totales,
        }

    for titulo, filas in hojas.items():
        try:
            worksheet = spreadsheet.worksheet(titulo)
        except gspread.exceptions.WorksheetNotFound:
            ancho = max((len(fila) for fila in filas), default=1)
            worksheet = spreadsheet.add_worksheet(
                title=titulo,
                rows=max(len(filas), 1),
                cols=max(ancho, 1),
            )
        await asyncio.to_thread(_sync_restaurar_en_worksheet, worksheet, filas)

    return {
        "restaurado": True,
        "dry_run": False,
        "pestanas": len(hojas),
        "filas": filas_totales,
    }


async def crear_backup() -> Path | None:
    """
    Genera el backup diario del spreadsheet (Fase 6.5.5) y purga los que superan la
    retención configurada. Retorna la ruta del .zip generado o None si hubo un error
    de API/archivos (loggeado, sin crash).
    """
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID
    backup_dir = Path(settings.BACKUP_DIR)
    try:
        spreadsheet = get_sheets_client().open_by_key(spreadsheet_id)
        ruta = await asyncio.to_thread(_sync_crear_backup, spreadsheet, backup_dir)
        await asyncio.to_thread(_sync_purge_backups, backup_dir, settings.BACKUP_RETENTION_DAYS)
        return ruta
    except Exception as e:
        logger.error(f"Error al generar el backup del sheet: {e}")
        return None
