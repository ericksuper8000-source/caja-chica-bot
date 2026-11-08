"""
Verifica un backup del sheet sin escribir nada.

Uso (dentro del contenedor de la app):
    python scripts/verificar_backup.py /backups/caja-chica-backup-AAAAMMDD-HHMMSS.zip

Sale con código 0 si el backup concilia con su MANIFEST; 1 si está roto.
"""

import argparse
import json
from pathlib import Path

from services.backup_service import verificar_backup


def main() -> int:
    parser = argparse.ArgumentParser(description="Verifica un backup del sheet.")
    parser.add_argument("ruta", type=Path, help="Ruta del archivo .zip del backup")
    args = parser.parse_args()

    reporte = verificar_backup(args.ruta)
    print(json.dumps(reporte, ensure_ascii=False, indent=2))
    return 0 if reporte["valido"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
