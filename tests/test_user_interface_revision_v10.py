from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_overview_does_not_mount_branch_explorer():
    source = (ROOT / "static/js/graph-enhancements.js").read_text(encoding="utf-8")
    overview = source.split("if (page === 'overview')", 1)[1].split("} else if (page === 'branches')", 1)[0]
    assert "installExplorer" not in overview


def test_branch_explorer_is_after_forecast_and_uses_selected_branch():
    app = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    enhancements = (ROOT / "static/js/graph-enhancements.js").read_text(encoding="utf-8")
    assert "['Branch information','Activity','Forecast','Branch Explorer','Ask a question','Programs']" in app
    assert 'id="branch-explorer-host"' in app
    assert "profile?.dataset.branchCode" in enhancements
    assert "installExplorer(explorerHost, 'branch', [code])" in enhancements
    assert "relate-branch-select" not in enhancements


def test_branch_explorer_hides_branch_properties_annual_records_and_events():
    source = (ROOT / "static/js/graph-enhancements.js").read_text(encoding="utf-8")
    assert "branch.properties" not in source
    assert "HAS_CIRCULATION_RECORD" not in source
    assert "HAS_VISITS_RECORD" not in source
    assert "HAS_WORKSTATION_RECORD" not in source
    assert "HAS_REGISTRATION_RECORD" not in source
    assert "HOSTS_EVENT" not in source
    assert "IN_NEIGHBOURHOOD" in source
    assert "IN_WARD" in source
    assert "OFFERS_SERVICE" in source
    assert "HAS_FACILITY" in source
    assert "graph.store" not in source


def test_branch_comparison_explorer_uses_all_selected_branches():
    source = (ROOT / "static/js/graph-enhancements.js").read_text(encoding="utf-8")
    assert "comparisonConnections(branches)" in source
    assert "installExplorer(result, 'comparison', codes)" in source
    assert "Shared connections" in source
    assert "Branch-specific connections" in source


def test_branch_details_include_requested_fields_before_website():
    source = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    fields = ["['Hours',hoursMarkup]", "['Public Parking',parkingValue]", "['Neighbourhood',b.neighbourhood]", "['Ward',b.ward]", "['Website',b.website"]
    positions = [source.index(field) for field in fields]
    assert positions == sorted(positions)

    backend = (ROOT / "main.py").read_text(encoding="utf-8")
    for field in ('"hours"', '"public_parking"', '"neighbourhood"', '"ward"'):
        assert field in backend


def test_explorer_summary_uses_human_readable_labels_and_only_useful_categories():
    source = (ROOT / "static/js/graph-enhancements.js").read_text(encoding="utf-8")
    assert "function humanizeIdentifier(value)" in source
    assert "explorerNodeTypes.has(item.label)" in source
    assert "explorerRelationshipTypes.has(item.type)" in source
    assert "Branch directory" in source
    assert "Located in neighbourhood" in source
