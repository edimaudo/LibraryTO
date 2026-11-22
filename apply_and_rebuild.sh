#!/usr/bin/env bash
set -euo pipefail

# Run from the existing LibraryTO repository root with the app stopped.
python apply_libraryto_update.py
python scripts/build_relate_graph.py
python scripts/validate_relate_graph.py
python -m pytest -q
