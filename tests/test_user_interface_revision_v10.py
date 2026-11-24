from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_all_tabs_and_subtabs_use_title_case_labels():
    source = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    assert "function titleCaseTabLabel(value)" in source
    assert "esc(titleCaseTabLabel(item))" in source


def test_overview_renames_annual_metric_to_branch_overview():
    source = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    overview = source.split("async function renderOverview() {", 1)[1].split("function branchPicker(", 1)[0]
    assert "'Branch Overview'" in overview
    assert "'Annual metric'" not in overview


def test_branch_overview_uses_one_reporting_year_filter_for_rankings_and_area_chart():
    source = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    assert 'branch-overview-year' in source
    assert '<option value="all" selected>All Years</option>' in source
    assert "branchOverviewResults(data,panel.dataset.metric,select.value)" in source
    assert "branchTotals(data,metric,selectedYears)" in source
    assert "branchActivitySizeChart(data,metric,selectedYears)" in source
    assert "Total across selected reporting years" in source
    assert "Reporting Year: %{customdata[2]}" in source
    assert "Measure:" not in source
    assert "activity-size-year" not in source


def test_location_map_defaults_to_all_reporting_years():
    source = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    overview = source.split("async function renderOverview() {", 1)[1].split("function branchPicker(", 1)[0]
    assert '<option value="all" selected>All Years</option>${renderYearOptions(years,\'\')}' in overview
    assert "if(year==='all')" in source


def test_activity_intensity_is_not_rendered_in_any_section():
    source = (ROOT / "static/js/graph-enhancements.js").read_text(encoding="utf-8")
    app = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    assert "installIntensity" not in source
    assert "Activity Intensity" not in source
    assert "Highest branch intensity" not in source
    assert "activityForecast" in app


def test_branch_information_contains_reported_services_after_ward_and_before_website():
    source = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    fields = ["['Hours',hoursMarkup]", "['Public Parking',parkingValue]", "['Neighbourhood',b.neighbourhood]", "['Ward',b.ward]", "['Reported Services',{html:servicesMarkup}]", "['Website',b.website"]
    positions = [source.index(field) for field in fields]
    assert positions == sorted(positions)
    assert "reported-services-heading" not in source.split("async function loadProfile", 1)[1].split("function bindQuestionForm", 1)[0]


def test_branch_insights_combines_activity_and_forecast_and_retains_explorer_order():
    source = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    branch = source.split("async function loadProfile(", 1)[1].split("function bindQuestionForm", 1)[0]
    assert "['Branch Information','Activity & Forecast','Branch Explorer','Ask A Question','Programs']" in branch
    assert 'id="branch-panel-1"' in branch and '${activityForecast}' in branch
    assert 'id="branch-panel-2"' in branch and 'id="branch-explorer-host"' in branch
    assert "tabsMarkup(['Branch information','Activity','Forecast'" not in branch


def test_comparison_branch_explorer_is_its_own_subtab():
    app = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    enhancements = (ROOT / "static/js/graph-enhancements.js").read_text(encoding="utf-8")
    assert "tabsMarkup(['Annual Metrics','Branch Information','Branch Explorer'],'comparison-main')" in app
    assert 'id="comparison-main-panel-2"' in app
    assert 'id="comparison-explorer-host"' in app
    assert "result?.querySelector('#comparison-explorer-host')" in enhancements
    assert "pairwiseInsights(selected)" in enhancements


def test_branch_explorer_shows_local_peer_and_service_coverage_insights_without_generic_cards():
    app = (ROOT / "static/js/graph-enhancements.js").read_text(encoding="utf-8")
    backend = (ROOT / "app/services/graph_enhancements.py").read_text(encoding="utf-8")
    assert "function branchExplorerInsights(branch)" in app
    assert "Closest Local Connections" in app
    assert "Local Service Reach" in app
    assert "Service Differences" in app
    assert "How Selected Branches Connect" in app
    assert "Reported Service Distribution" in app
    assert "branch-explorer-metrics" in app
    assert "sharedConnectionCount" in app
    assert "graph.node_count" not in app
    assert "graph.relationship_count" not in app
    assert '"peer_branches": peer_branches' in backend
    assert "IN_NEIGHBOURHOOD" in backend and "IN_WARD" in backend


def test_overview_and_programs_events_do_not_mount_branch_explorer():
    source = (ROOT / "static/js/graph-enhancements.js").read_text(encoding="utf-8")
    assert "page==='overview'" not in source
    assert "page==='events'" not in source


def test_accessibility_validator_and_docs_are_present():
    assert (ROOT / "scripts/validate_accessibility.py").is_file()
    assert (ROOT / "ACCESSIBILITY_VALIDATION.md").is_file()


def test_graph_explorer_is_an_overview_subtab_and_not_primary_navigation():
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    app = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    api = (ROOT / "app/routes/graph_features.py").read_text(encoding="utf-8")
    backend = (ROOT / "app/services/graph_enhancements.py").read_text(encoding="utf-8")
    main = (ROOT / "main.py").read_text(encoding="utf-8")
    overview = app.split("async function renderOverview() {", 1)[1].split("function branchPicker(", 1)[0]
    assert "Library Network Explorer" in overview
    assert 'id="overview-panel-4"' in overview
    assert 'id="overview-graph-explorer"' in overview
    assert 'href="/graph-explorer"' not in template
    assert "Inspect A Branch’s Graph Connections" not in app
    assert "Node Labels" in app and "Relationship Types" in app
    assert "Browse Nodes And Properties" in app
    assert "Branch Connections" not in app
    assert '@router.get("/relate/inspect")' in api
    assert "def inspect_graph_nodes(" in backend
    assert "_physical_branch_clause" in backend
    assert "graph:renderGraphExplorer" not in app
    assert '@app.get("/graph-explorer"' not in main


def test_graph_explorer_adds_nonduplicative_graph_topology_insights():
    app = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    backend = (ROOT / "app/services/graph_enhancements.py").read_text(encoding="utf-8")
    assert "Relationship Coverage" not in app
    assert "Top 10 Most Connected Branches" in app
    assert "Top 10 Neighbourhoods" in app
    assert "Top 10 Wards" in app
    assert '"area_hubs": area_hubs' in backend
    assert '"service_reach": service_reach' in backend
    assert "LIMIT 10" in backend
    assert '"relationship_coverage": coverage' in backend
    assert '"physical_branch_filter": "PhysicalBranch = 1"' in backend


def test_overview_ordinal_branch_question_uses_present_site_year_with_tie_note():
    source = (ROOT / "app/services/relate.py").read_text(encoding="utf-8")
    assert "def _ordinal_branch_rank(" in source
    assert "def _answer_ordinal_branch(" in source
    assert "Branches with the same present-site year are ordered alphabetically" in source
    assert "The source records the year of the current site" in source
