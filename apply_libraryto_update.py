"""Apply the LibraryTO Relate graph and activity-intensity UI update.

Run from the root of an existing LibraryTO checkout after extracting this ZIP:
    python apply_libraryto_update.py
The script is idempotent and refuses to patch unfamiliar source layouts.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent


def replace_once(path: Path, old: str, new: str, description: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Cannot safely apply {description}: expected one source marker in {path.relative_to(ROOT)}, found {count}.")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"Patched {path.relative_to(ROOT)}: {description}")


def main() -> int:
    required = [
        ROOT / "main.py", ROOT / "app/services/relate.py", ROOT / "templates/index.html",
        ROOT / "app/services/graph_enhancements.py", ROOT / "app/routes/graph_features.py",
        ROOT / "static/js/graph-enhancements.js", ROOT / "static/css/graph-enhancements.css",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        raise SystemExit("Extract the entire update ZIP into the existing LibraryTO repository root first. Missing: " + ", ".join(missing))

    main_py = ROOT / "main.py"
    replace_once(
        main_py,
        "from app.services.relate import RelateUnavailable, ask as relate_ask, graph_status\n",
        "from app.services.relate import RelateUnavailable, ask as relate_ask, graph_status\nfrom app.routes.graph_features import router as graph_features_router\n",
        "register graph feature routes",
    )
    replace_once(
        main_py,
        "app = FastAPI(title=\"LibraryTO\", version=\"1.1.0\", description=\"Explore Toronto Public Library branch information, activity and programs.\", docs_url=None, redoc_url=None, openapi_url=None)\n",
        "app = FastAPI(title=\"LibraryTO\", version=\"1.2.0\", description=\"Explore Toronto Public Library branch information, activity and connected context.\", docs_url=None, redoc_url=None, openapi_url=None)\napp.include_router(graph_features_router)\n",
        "register Relate Explorer and activity-intensity endpoints",
    )
    # Keep query-string cache busting aligned with the new static assets.
    main_text = main_py.read_text(encoding="utf-8")
    if 'STATIC_VERSION = "20261121-4"' not in main_text:
        if 'STATIC_VERSION = "20261121-3"' in main_text:
            main_text = main_text.replace('STATIC_VERSION = "20261121-3"', 'STATIC_VERSION = "20261121-4"')
        elif 'STATIC_VERSION = "20261121-2"' in main_text:
            main_text = main_text.replace('STATIC_VERSION = "20261121-2"', 'STATIC_VERSION = "20261121-4"')
        else:
            import re
            main_text, n = re.subn(r'STATIC_VERSION\s*=\s*"[^"]+"', 'STATIC_VERSION = "20261121-4"', main_text, count=1)
            if n != 1:
                raise RuntimeError("Could not locate STATIC_VERSION in main.py")
        main_py.write_text(main_text, encoding="utf-8")
        print("Updated main.py: static asset cache version")

    relate_py = ROOT / "app/services/relate.py"
    replace_once(
        relate_py,
        """        schema = _cached_schema(connection)\n\n        if oldest_branch_question:\n""",
        """        schema = _cached_schema(connection)\n\n        # Relationship-dependent questions use connected Relate paths first.\n        from app.services.graph_enhancements import answer_connected_question\n        connected_answer = answer_connected_question(connection, schema, question, selected_branch)\n        if connected_answer is not None:\n            return connected_answer\n\n        if oldest_branch_question:\n""",
        "route neighbourhood, ward, service and cross-branch questions through graph relationships",
    )

    # Attach the selected physical branch code to the rendered profile so the
    # enhancement script can request the correct branch-level graph paths.
    app_js = ROOT / "static/js/app.js"
    replace_once(
        app_js,
        """async function loadProfile(code) {\n  const pane=$('#branch-profile');if(!pane)return;\n""",
        """async function loadProfile(code) {\n  const pane=$('#branch-profile');if(!pane)return;\n  pane.dataset.branchCode=code;\n""",
        "expose selected branch code to the Relate Explorer",
    )

    template = ROOT / "templates/index.html"
    replace_once(
        template,
        "  <link rel=\"stylesheet\" href=\"{{ url_for('static', path='/css/app.css') }}?v={{ static_version }}\">\n",
        "  <link rel=\"stylesheet\" href=\"{{ url_for('static', path='/css/app.css') }}?v={{ static_version }}\">\n  <link rel=\"stylesheet\" href=\"{{ url_for('static', path='/css/graph-enhancements.css') }}?v={{ static_version }}\">\n",
        "load Relate Explorer and intensity styles",
    )
    replace_once(
        template,
        "  <script src=\"{{ url_for('static', path='/js/app.js') }}?v={{ static_version }}\" defer></script>\n</body>",
        "  <script src=\"{{ url_for('static', path='/js/app.js') }}?v={{ static_version }}\" defer></script>\n  <script src=\"{{ url_for('static', path='/js/graph-enhancements.js') }}?v={{ static_version }}\" defer></script>\n</body>",
        "load the judge-facing Relate and normalized activity interface",
    )

    print("\nSource integration applied. Next, rebuild and validate the persistent graph:")
    print("  python scripts/build_relate_graph.py")
    print("  python scripts/validate_relate_graph.py")
    print("Then run tests and start LibraryTO as usual.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
