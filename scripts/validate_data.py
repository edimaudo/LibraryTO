"""Validate LibraryTO's exact source filenames and expected CSV columns."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import RELATE_FILE
from app.services.data_store import DATASETS, dataset_path, field, load_all


def main() -> int:
    load_all.cache_clear()
    errors: list[str] = []
    warnings: list[str] = []

    print("LibraryTO source validation")
    print(f"Data directory: {ROOT / 'data'}\n")

    for key, spec in DATASETS.items():
        path = dataset_path(key)
        rows = load_all()[key]
        print(f"{spec['filename']}: ", end="")
        if not path.is_file():
            print("MISSING")
            errors.append(f"Missing required file: {spec['filename']}")
            continue
        if not rows:
            print("EMPTY OR UNREADABLE")
            errors.append(f"File is empty or unreadable: {spec['filename']}")
            continue
        missing = []
        header_row = rows[0]
        for alternatives in spec["required"]:
            if not any(field(header_row, name) != "" for name in alternatives):
                missing.append(" or ".join(alternatives))
        if missing:
            print(f"FOUND ({len(rows)} rows), MISSING FIELDS: {', '.join(missing)}")
            errors.append(f"{spec['filename']} is missing required fields: {', '.join(missing)}")
        else:
            print(f"OK ({len(rows)} rows)")

    print(f"{RELATE_FILE.name}: ", end="")
    if RELATE_FILE.is_file():
        print(f"FOUND ({RELATE_FILE.stat().st_size:,} bytes)")
    else:
        print("MISSING")
        errors.append(f"Missing required file: {RELATE_FILE.name}")

    if errors:
        print("\nValidation failed:")
        for item in errors:
            print(f"- {item}")
        return 1

    print("\nAll seven data assets are present.")
    if warnings:
        print("Warnings:")
        for item in warnings:
            print(f"- {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
