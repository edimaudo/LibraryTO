"""Validate that the committed LibraryTO Relate file contains connected context."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.graph_enhancements import explorer_snapshot


def main() -> int:
    snapshot = explorer_snapshot([])
    print(f"Store: {snapshot['store']} ({snapshot['mode']})")
    print(f"Nodes: {snapshot['node_count']:,}")
    print(f"Relationships: {snapshot['relationship_count']:,}")
    print("\nRelationship counts:")
    for item in snapshot["relationship_counts"]:
        print(f"  {item['type']}: {item['count']:,}")
    required = {"HAS_CIRCULATION_RECORD", "HAS_VISITS_RECORD", "HAS_WORKSTATION_RECORD", "HAS_REGISTRATION_RECORD", "IN_NEIGHBOURHOOD", "IN_WARD", "OFFERS_SERVICE"}
    observed = {item["type"] for item in snapshot["relationship_counts"] if item["count"] > 0}
    missing = sorted(required - observed)
    if missing:
        print("\nMissing required populated relationship types:")
        for item in missing:
            print(f"  {item}")
        return 1
    print("\nRelate graph validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
