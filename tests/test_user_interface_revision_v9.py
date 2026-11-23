from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_branch_overview_aggregates_selected_reporting_years():
    source = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    assert "function branchOverviewResults(data,metric,yearSelection='all')" in source
    assert "const yearLabel=yearSelection==='all'?'All Years':String(yearSelection)" in source
    assert "Total across selected reporting years" in source


def test_location_year_defaults_to_all_years_and_uses_aggregated_values():
    source = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    assert '<option value="all" selected>All Years</option>${renderYearOptions(years,\'\')}' in source
    assert "rows.forEach(row=>Object.entries(row.values||{})" in source


def test_branch_insights_activity_and_forecast_share_one_panel():
    source = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    assert "Activity & Forecast" in source
    assert "const activityForecast=Object.keys(METRICS).map" in source
    assert "branch-panel-2" in source and "branch-explorer-host" in source


def test_explorer_uses_graph_peer_paths_to_create_insights():
    source = (ROOT / "app/services/graph_enhancements.py").read_text(encoding="utf-8")
    assert "def _peer_branches_in_shared_areas" in source
    assert "IN_NEIGHBOURHOOD" in source and "IN_WARD" in source
    assert '"peer_branches": peer_branches' in source
