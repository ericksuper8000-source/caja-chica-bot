"""
Restaura un backup del sheet en un spreadsheet.

Por defecto hace un dry-run (solo lee y cuenta). Para escribir de verdad hay que
pasar `--confirmar`. **Usar siempre una copia del spreadsheet, nunca producción.**

Uso:
    python scripts/restaurar_backup.py /backups/backup.zip --spreadsheet-id <ID>
    python scripts/restaurar_backup.py /backups/backup.zip --spreadsheet-id <ID> --confirmar
"""

import argparse
import asyncio
import json
from pathlib import Path

from services.backup_service import restaurar_backup
from services.sheets_service import get_sheets_client


def main() -> int:
    parser = argparse.ArgumentParser(description="Restaura un backup del sheet.")
    parser.add_argument("ruta", type=Path, help="Ruta del archivo .zip del backup")
    parser.add_argument(
        "--spreadsheet-id",
        required=True,
        help="ID del spreadsheet destino (usar una copia, no producción)",
    )
    parser.add_argument(
        "--confirmar",
        action="store_true",
        help="Escribe de verdad; sin esta bandera solo hace dry-run",
    )
    args = parser.parse_args()

    spreadsheet = get_sheets_client().open_by_key(args.spreadsheet_id)
    resultado = asyncio.run(
        restaurar_backup(args.ruta, spreadsheet, dry_run=not args.confirmar)
    )
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
