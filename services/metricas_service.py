"""
Métricas operativas mínimas (Paso 1 de operación).

No es Prometheus ni un sistema de observabilidad: es un resumen barato y sin PII que
la app puede exponer en `/metrics` para responder “¿está corriendo?” y “¿hay backups
recientes?”. Las métricas de negocio (movimientos/día, errores) se consultan desde los
logs y la hoja; el runbook explica cómo.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from services.backup_service import BACKUP_FILE_PREFIX, BACKUP_FILENAME_RE


def contar_backups(backup_dir: str | Path) -> dict[str, Any]:
    """Cuenta los backups válidos por nombre y devuelve el más reciente (sin PII)."""
    ruta = Path(backup_dir)
    archivos: list[Path] = []
    if ruta.exists():
        for archivo in ruta.glob(f"{BACKUP_FILE_PREFIX}*.zip"):
            if BACKUP_FILENAME_RE.match(archivo.name):
                archivos.append(archivo)
    archivos.sort(key=lambda item: item.name, reverse=True)
    ultimo = archivos[0] if archivos else None
    return {
        "total": len(archivos),
        "ultimo": ultimo.name if ultimo else None,
        "ultimo_tamano_bytes": ultimo.stat().st_size if ultimo else 0,
    }
