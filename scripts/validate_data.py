"""Validate LibraryTO source assets and physical branch count."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import RELATE_FILE
from app.services.data_store import DATASETS, branch_records, dataset_path, load_all, normalize_key, refresh_data_cache

EXPECTED_PHYSICAL_BRANCHES = 100


def main() -> int:
    refresh_data_cache()
    errors: list[str] = []

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
        present_headers = {normalize_key(name) for name in rows[0].keys()}
        for alternatives in spec["required"]:
            if not any(normalize_key(name) in present_headers for name in alternatives):
                missing.append(" or ".join(alternatives))
        if missing:
            print(f"FOUND ({len(rows)} rows), MISSING FIELDS: {', '.join(missing)}")
            errors.append(f"{spec['filename']} is missing required fields: {', '.join(missing)}")
        else:
            print(f"OK ({len(rows)} rows)")

    physical_branches = branch_records()
    print(f"Eligible physical branches: {len(physical_branches)} (expected {EXPECTED_PHYSICAL_BRANCHES})")
    if len(physical_branches) != EXPECTED_PHYSICAL_BRANCHES:
        errors.append(f"Expected {EXPECTED_PHYSICAL_BRANCHES} physical branches after excluding PhysicalBranch=0; found {len(physical_branches)}.")

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

    print("\nAll seven source assets and the physical branch count are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
