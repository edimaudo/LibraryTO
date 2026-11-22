"""Apply the LibraryTO judging fixes to an existing repository checkout.

Run this from the repository root after extracting the update ZIP over the
existing LibraryTO source. It does not create branches, commit, push, or deploy.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re
import textwrap

ROOT = Path(__file__).resolve().parent


def replace_once(path: Path, old: str, new: str, description: str) -> None:
    source = path.read_text(encoding="utf-8")
    if new in source:
        return
    count = source.count(old)
    if count != 1:
        raise RuntimeError(
            f"Cannot safely apply {description}: expected one marker in "
            f"{path.relative_to(ROOT)}, found {count}. No fuzzy replacement was attempted."
        )
    path.write_text(source.replace(old, new, 1), encoding="utf-8")
    print(f"Patched {path.relative_to(ROOT)}: {description}")


def inject_template_assets(path: Path) -> None:
    """Insert the graph enhancement assets next to the existing app assets."""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    current = "".join(lines)
    additions = []
    if "/css/graph-enhancements.css" not in current:
        candidates = [i for i, line in enumerate(lines) if "/css/app.css" in line and "stylesheet" in line]
        if len(candidates) != 1:
            raise RuntimeError("Could not uniquely locate the app stylesheet in templates/index.html")
        css_line = "  <link rel=\"stylesheet\" href=\"{{ url_for('static', path='/css/graph-enhancements.css') }}?v={{ static_version }}\">\n"
        additions.append((candidates[0] + 1, css_line))
    if "/js/graph-enhancements.js" not in current:
        candidates = [i for i, line in enumerate(lines) if "/js/app.js" in line and "<script" in line]
        if len(candidates) != 1:
            raise RuntimeError("Could not uniquely locate the main application script in templates/index.html")
        js_line = "  <script src=\"{{ url_for('static', path='/js/graph-enhancements.js') }}?v={{ static_version }}\" defer></script>\n"
        additions.append((candidates[0] + 1, js_line))
    for index, line in sorted(additions, reverse=True):
        lines.insert(index, line)
    path.write_text("".join(lines), encoding="utf-8")
    if additions:
        print("Patched templates/index.html: load Relate Explorer and activity-intensity assets")


def replace_function(path: Path, function_name: str, replacement: str) -> None:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    matches = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one top-level {function_name}() in {path.relative_to(ROOT)}; found {len(matches)}.")
    node = matches[0]
    lines = source.splitlines(keepends=True)
    start = node.lineno - 1
    end = node.end_lineno
    replacement = textwrap.dedent(replacement).strip("\n") + "\n\n"
    lines[start:end] = [replacement]
    patched = "".join(lines)
    ast.parse(patched)
    path.write_text(patched, encoding="utf-8")
    print(f"Patched {path.relative_to(ROOT)}: {function_name}() ranking semantics")


RANKING_FUNCTION = r'''
def _answer_metric_ranking(connection, schema, metric: str, year: str | None, question: str = "") -> dict[str, Any]:
    """Rank annual branch observations across the requested reporting period.

    If a year is supplied, rank within that year. If the question explicitly
    requests the latest/most recent year, use the latest year. Otherwise a
    yearless question compares all available branch-year observations and
    reports the highest (or lowest) annual record with its reporting year.
    """
    found = _label_for_metric(schema, metric)
    if not found:
        return _not_found(f"The Relate graph does not contain annual {METRIC_SPECS[metric]['noun']} records.")
    label, properties = found
    value_key = _first_key(properties, METRIC_SPECS[metric]["value_aliases"])
    rows = _nodes(connection, label, properties, year=year, limit=5000)
    eligible = _eligible_codes()
    records_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    actual_years: set[str] = set()
    for props in rows:
        if not is_physical_branch(props):
            continue
        normalized = _normalised_properties(props)
        code = str(next((normalized.get(alias) for alias in BRANCH_CODE_ALIASES if normalized.get(alias) not in (None, "")), "")).strip()
        branch_item = eligible.get(code.casefold())
        value = number(props.get(value_key)) if value_key else None
        raw_year = next((normalized.get(alias) for alias in YEAR_ALIASES if normalized.get(alias) not in (None, "")), None)
        year_match = re.search(r"(?:19|20)\d{2}", str(raw_year or ""))
        record_year = year_match.group(0) if year_match else ""
        if not branch_item or value is None or not record_year:
            continue
        if year and record_year != str(year):
            continue
        actual_years.add(record_year)
        records_by_key[(branch_item["code"], record_year)] = {
            "code": branch_item["code"],
            "name": branch_item["name"],
            "year": record_year,
            "value": float(value),
            "properties": props,
        }
    if not records_by_key:
        return _not_found(f"No annual {METRIC_SPECS[metric]['noun']} values were found for {year or 'the available reporting years'}.")

    q = _normalise_question(question)
    latest_requested = bool(re.search(r"\b(latest|most recent|last reported|current year)\b", q))
    if year:
        chosen_year = str(year)
        period_records = [item for item in records_by_key.values() if item["year"] == chosen_year]
    elif latest_requested:
        chosen_year = max(actual_years, key=int)
        period_records = [item for item in records_by_key.values() if item["year"] == chosen_year]
    else:
        chosen_year = None
        period_records = list(records_by_key.values())

    lowest = bool(re.search(r"\b(lowest|least|fewest|smallest)\b", q))
    period_records.sort(key=lambda item: (item["value"], int(item["year"]), item["name"].casefold()), reverse=not lowest)
    top_match = re.search(r"\btop\s+(\d{1,2})\b", q)
    limit = max(1, min(int(top_match.group(1)), 10)) if top_match else 1
    selected = period_records[:limit]
    direction = "lowest" if lowest else "highest"
    noun = METRIC_SPECS[metric]["noun"]

    # Compute one branch leader for every reporting year so the user can see
    # how the answer changes over time, even when the overall maximum is in an
    # earlier year than the latest dataset year.
    yearly_leaders = []
    if not year and not latest_requested:
        for reporting_year in sorted(actual_years, key=int):
            year_rows = [item for item in records_by_key.values() if item["year"] == reporting_year]
            year_rows.sort(key=lambda item: (item["value"], item["name"].casefold()), reverse=not lowest)
            if year_rows:
                yearly_leaders.append(year_rows[0])

    if chosen_year:
        lead = selected[0]
        answer = (
            f"In {chosen_year}, the {direction} annual {noun} among physical branches was "
            f"{lead['name']} ({_display_number(lead['value'])})."
        )
        details = [{"label": "Branch", "value": lead["name"]},
                   {"label": "Annual value", "value": _display_number(lead["value"])},
                   {"label": "Reporting year", "value": chosen_year}]
    else:
        lead = selected[0]
        answer = (
            f"Across all available reporting years, the {direction} annual {noun} was "
            f"{lead['name']} ({_display_number(lead['value'])}) in {lead['year']}."
        )
        if yearly_leaders:
            annual_summary = "; ".join(
                f"{item['year']}: {item['name']} ({_display_number(item['value'])})"
                for item in yearly_leaders
            )
            answer += f" {direction.capitalize()} branch by reporting year: {annual_summary}."
        details = [{"label": "Branch with highest annual record" if not lowest else "Branch with lowest annual record", "value": lead["name"]},
                   {"label": "Annual value", "value": _display_number(lead["value"])},
                   {"label": "Reporting year", "value": lead["year"]}]
        details.extend({"label": f"{item['year']} annual leader", "value": f"{item['name']} · {_display_number(item['value'])}"} for item in yearly_leaders)

    if limit > 1:
        answer += " Ranked records: " + "; ".join(
            f"{item['name']} ({_display_number(item['value'])}, {item['year']})" for item in selected
        ) + "."
        details.extend({"label": f"Rank {index + 1}", "value": f"{item['name']} · {_display_number(item['value'])} · {item['year']}"} for index, item in enumerate(selected))

    return {
        "status": "ok",
        "answer": answer,
        "highlights": [{
            "title": f"{direction.capitalize()} {METRICS_LABELS[metric]}",
            "category": chosen_year or "All available reporting years",
            "details": details,
        }],
        "evidence": [{"labels": [label], "properties": item["properties"], "connections": []} for item in (yearly_leaders or selected)],
        "direct_intent": True,
        "scope_verified": True,
        "network_scope": True,
    }
'''


def patch_overview_analysis(app_js: Path) -> None:
    source = app_js.read_text(encoding="utf-8")
    start = source.find("function rankingMetricPanel(data,metric,index) {")
    end = source.find("function popup(branch) {", start)
    if start < 0 or end < 0:
        raise RuntimeError("Could not locate the Overview Branch Analysis rendering block in static/js/app.js.")
    snippet = (ROOT / "patches/branch_analysis.js").read_text(encoding="utf-8")
    source = source[:start] + snippet + "\n" + source[end:]

    # Replace the four independent square-footage charts with one year-aware
    # chart inside each corresponding metric subtab.
    source = source.replace("  const footprint=footprintCharts(data);\n", "")
    old = '''      <section class="analysis-section"><h2>Top 10 and bottom 10 branches</h2><p class="small-note">Rankings use each branch's total reported value across the available reporting years.</p>${rankingTabs(data)}</section>
      <section class="analysis-section"><h2>Annual activity and branch area</h2><div class="grid-2">${footprint}</div></section>'''
    new = '''      <section class="analysis-section branch-analysis-section">${rankingTabs(data)}</section>'''
    if new not in source:
        if source.count(old) != 1:
            raise RuntimeError("Could not safely replace the old four-chart Branch Analysis layout in static/js/app.js.")
        source = source.replace(old, new, 1)

    # Update only the Overview renderer with a delegated year selector handler.
    overview_start = source.find("async function renderOverview() {")
    overview_end = source.find("function branchPicker(", overview_start)
    if overview_start < 0 or overview_end < 0:
        raise RuntimeError("Could not locate renderOverview() in static/js/app.js.")
    body = source[overview_start:overview_end]
    marker = "  attachTabs(host,(panel,index)=>{"
    handler = '''  host.addEventListener('change',event=>{
    const select=event.target.closest('.activity-size-year');
    if(!select)return;
    const panel=select.closest('.ranking-metric-panel');
    const chartHost=panel?.querySelector('.activity-size-chart');
    if(!panel||!chartHost)return;
    if(window.Plotly)$$('.plotly-chart',chartHost).forEach(el=>{try{Plotly.purge(el);}catch(_){}});
    chartHost.innerHTML=branchActivitySizeChart(data,panel.dataset.metric,select.value);
    drawCharts(chartHost);
  });
'''
    if handler not in body:
        if body.count(marker) != 1:
            raise RuntimeError("Could not add the annual reporting-year chart control to renderOverview().")
        body = body.replace(marker, handler + marker, 1)

    # Bind Overview Q&A before Plotly finishes rendering so the form is
    # immediately usable even when chart libraries are still loading.
    bind_call = "  bindQuestionForm('#overview-question-form','#overview-question','#overview-answer',null);\n"
    # Move any existing binding instead of duplicating it after the chart wait.
    body = body.replace(bind_call, "")
    if body.count(marker) != 1:
        raise RuntimeError("Could not position the Overview Q&A binding before chart rendering.")
    body = body.replace(marker, bind_call + marker, 1)
    source = source[:overview_start] + body + source[overview_end:]

    # Tag each comparison metric panel so its intensity panel follows the
    # currently selected comparison metric rather than showing a duplicate
    # global measure selector.
    old_metric_panel = 'class="tab-panel" role="tabpanel" aria-labelledby="comparison-year-tab-${i}" '
    new_metric_panel = 'data-metric="${metric}" class="tab-panel" role="tabpanel" aria-labelledby="comparison-year-tab-${i}" '
    if new_metric_panel not in source:
        if source.count(old_metric_panel) != 1:
            raise RuntimeError("Could not identify the comparison metric panels for activity-intensity placement.")
        source = source.replace(old_metric_panel, new_metric_panel, 1)

    # The shared tab handler also sees the nested ranking subtabs. Restrict
    # the map callback to the actual Overview Location panel so choosing the
    # fourth metric cannot initialize a hidden map.
    old_map_guard = "    if(index===3){const mapEl=$('#branch-map');"
    new_map_guard = "    if(index===3 && panel.id==='overview-panel-3'){const mapEl=$('#branch-map');"
    if new_map_guard not in source:
        if source.count(old_map_guard) != 1:
            raise RuntimeError("Could not isolate the Overview location-map tab callback.")
        source = source.replace(old_map_guard, new_map_guard, 1)

    app_js.write_text(source, encoding="utf-8")
    print("Patched static/js/app.js: per-metric Branch Analysis layout and year-specific branch-size chart")


def verify_applied_changes(root: Path) -> None:
    """Fail loudly if source integration points are missing after patching."""
    main_source = (root / "main.py").read_text(encoding="utf-8")
    relate_source = (root / "app/services/relate.py").read_text(encoding="utf-8")
    app_source = (root / "static/js/app.js").read_text(encoding="utf-8")
    template_source = (root / "templates/index.html").read_text(encoding="utf-8")
    enhancement_source = (root / "static/js/graph-enhancements.js").read_text(encoding="utf-8")

    required_checks = {
        "Relate feature router registered": "app.include_router(graph_features_router)" in main_source,
        "relationship-based Q&A enabled": "answer_connected_question(connection, schema, question, selected_branch)" in relate_source,
        "yearless ranking compares all available reporting years": "Across all available reporting years" in relate_source,
        "per-metric annual branch-size chart present": "Annual activity and branch size" in app_source,
        "old four-chart branch-area panel removed": "footprintCharts(data)" not in app_source,
        "old redundant ranking instruction removed": "Rankings use each branch's total reported value" not in app_source,
        "activity-intensity assets loaded": "/css/graph-enhancements.css" in template_source and "/js/graph-enhancements.js" in template_source,
        "Relate Explorer is wired into all three sections": all(token in enhancement_source for token in ("page === 'overview'", "page === 'branches'", "page === 'comparisons'")),
        "activity intensity is wired into all three sections": all(token in enhancement_source for token in ("'overview'", "'branch'", "'comparison'", "installIntensity")),
        "static cache version bumped": 'STATIC_VERSION = "20261122-3"' in main_source,
    }
    overview_start = app_source.find("async function renderOverview() {")
    overview_end = app_source.find("function branchPicker(", overview_start)
    overview = app_source[overview_start:overview_end] if overview_start >= 0 and overview_end > overview_start else ""
    bind_index = overview.find("bindQuestionForm('#overview-question-form'")
    draw_index = overview.find("await drawCharts($('#overview-panel-0'))")
    required_checks["Overview Q&A bound before chart rendering"] = bind_index >= 0 and draw_index >= 0 and bind_index < draw_index
    failed = [label for label, passed in required_checks.items() if not passed]
    if failed:
        raise RuntimeError("Update integration verification failed: " + "; ".join(failed))
    print("Verified update integration: " + ", ".join(label for label in required_checks))


def main() -> int:
    required = [
        ROOT / "main.py", ROOT / "app/services/relate.py", ROOT / "templates/index.html",
        ROOT / "app/services/graph_enhancements.py", ROOT / "app/routes/graph_features.py",
        ROOT / "static/js/graph-enhancements.js", ROOT / "static/css/graph-enhancements.css",
        ROOT / "scripts/build_relate_graph.py", ROOT / "scripts/validate_relate_graph.py",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        raise SystemExit("Extract the entire update ZIP into the existing LibraryTO repository root first. Missing: " + ", ".join(missing))

    main_py = ROOT / "main.py"
    replace_once(
        main_py,
        "from app.services.relate import RelateUnavailable, ask as relate_ask, graph_status\n",
        "from app.services.relate import RelateUnavailable, ask as relate_ask, graph_status\nfrom app.routes.graph_features import router as graph_features_router\n",
        "register Relate Explorer and activity-intensity routes",
    )
    current_fastapi = 'app = FastAPI(title="LibraryTO", version="1.1.0", description="Explore Toronto Public Library branch information, activity and programs.", docs_url=None, redoc_url=None, openapi_url=None)\n'
    revised_fastapi = 'app = FastAPI(title="LibraryTO", version="1.2.0", description="Explore Toronto Public Library branch information, activity and connected context.", docs_url=None, redoc_url=None, openapi_url=None)\napp.include_router(graph_features_router)\n'
    if revised_fastapi not in main_py.read_text(encoding="utf-8"):
        replace_once(main_py, current_fastapi, revised_fastapi, "register graph feature endpoints")
    source = main_py.read_text(encoding="utf-8")
    source, count = re.subn(r'STATIC_VERSION\s*=\s*"[^"]+"', 'STATIC_VERSION = "20261122-3"', source, count=1)
    if count != 1:
        raise RuntimeError("Could not locate STATIC_VERSION in main.py")
    main_py.write_text(source, encoding="utf-8")

    relate_py = ROOT / "app/services/relate.py"
    replace_function(relate_py, "_answer_metric_ranking", RANKING_FUNCTION)
    replace_once(
        relate_py,
        "        schema = _cached_schema(connection)\n\n        if oldest_branch_question:\n",
        "        schema = _cached_schema(connection)\n\n        # Traverse actual Relate edges for ward, neighbourhood, service and peer questions.\n        from app.services.graph_enhancements import answer_connected_question\n        connected_answer = answer_connected_question(connection, schema, question, selected_branch)\n        if connected_answer is not None:\n            return connected_answer\n\n        if oldest_branch_question:\n",
        "route connected-context Q&A through Relate relationships",
    )

    app_js = ROOT / "static/js/app.js"
    replace_once(
        app_js,
        "async function loadProfile(code) {\n  const pane=$('#branch-profile');if(!pane)return;\n",
        "async function loadProfile(code) {\n  const pane=$('#branch-profile');if(!pane)return;\n  pane.dataset.branchCode=code;\n",
        "make the selected branch available to its graph explorer",
    )
    patch_overview_analysis(app_js)

    template = ROOT / "templates/index.html"
    inject_template_assets(template)
    verify_applied_changes(ROOT)

    print("\nSource patches applied. Rebuild the single-file Relate store while the app is stopped:")
    print("  python scripts/build_relate_graph.py")
    print("  python scripts/validate_relate_graph.py")
    print("Then run: python -m pytest -q")
    print("Start: uvicorn main:app --reload")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
