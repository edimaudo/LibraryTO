from __future__ import annotations

import csv
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from main import app
from app.services import data_store, relate as relate_service

client = TestClient(app)


def write_csv(path: Path, headers: list[str], rows: list[list[object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


@pytest.fixture()
def sample_data(tmp_path, monkeypatch):
    monkeypatch.setattr(data_store, "DATA_DIR", tmp_path)
    write_csv(
        tmp_path / "tpl-branch-general-information.csv",
        ["BranchCode", "BranchName", "Address", "ServiceTier", "BranchType", "YearOpened", "SquareFootage", "Workstations", "Latitude", "Longitude", "KidsStop", "LeadingReading"],
        [
            ["BR001", "Maple Branch", "100 Main Street", "NL", "Neighbourhood Library", 1998, 12000, 24, 43.70, -79.40, "Yes", "No"],
            ["BR002", "River Branch", "200 River Road", "DL", "District Library", 1972, 18000, 32, 43.72, -79.42, "No", "Yes"],
        ],
    )
    metrics = {
        "circulation": ("tpl-circulation-annual-by-branch.csv", "Circulation", 1000, 800),
        "visits": ("tpl-visits-annual-by-branch.csv", "Visits", 500, 400),
        "workstations": ("tpl-workstation-usage-annual-by-branch.csv", "Sessions", 300, 250),
        "registrations": ("tpl-card-registrations-annual-by-branch.csv", "Registrations", 120, 90),
    }
    for filename, value_field, branch_a, branch_b in metrics.values():
        rows = []
        for index, year in enumerate(range(2018, 2024)):
            rows.append(["BR001", year, branch_a + index * 10])
            rows.append(["BR002", year, branch_b + index * 10])
        write_csv(tmp_path / filename, ["BranchCode", "Year", value_field], rows)

    write_csv(
        tmp_path / "tpl-events-feed.csv",
        ["EventID", "Title", "StartDate", "StartTime", "LocationName", "BranchCode", "Audiences", "Languages", "EventTypes", "Description", "RegistrationOpen", "IsFull", "RegistrationClosed"],
        [
            ["EV001", "Family Coding Workshop", "2099-01-15", "10:00 AM", "Maple Branch", "BR001", "Families", "English", "Workshop", "Introductory coding activities", "Yes", "No", "No"],
            ["EV002", "Reading Circle", "2099-01-20", "14:00", "River Branch", "BR002", "Adults", "French", "Reading", "A community reading group", "No", "Yes", "No"],
        ],
    )
    (tmp_path / "tpl_library_graph.rl").write_bytes(b"test graph placeholder")
    data_store.refresh_data_cache()
    yield tmp_path
    data_store.refresh_data_cache()


def test_all_pages_render():
    for path in ["/", "/branch-insights", "/comparisons", "/programs-events"]:
        response = client.get(path)
        assert response.status_code == 200
        assert "LibraryTO" in response.text
        assert "Inter" in response.text
        assert "plotly-2.35.2.min.js" not in response.text  # loaded on demand by the frontend
        assert "Data &amp; Methodology" not in response.text
    removed = client.get("/data-methodology")
    assert removed.status_code == 404


def test_empty_state_overview_and_exact_expected_names():
    response = client.get("/overview")
    assert response.status_code == 200
    assert response.json()["branch_count"] == 0
    status = client.get("/status").json()
    assert status["datasets"]["branches"]["filename"] == "tpl-branch-general-information.csv"
    assert status["datasets"]["events"]["filename"] == "tpl-events-feed.csv"
    assert status["relate"]["filename"] == "tpl_library_graph.rl"


def test_overview_uses_latest_year_only(sample_data):
    response = client.get("/overview")
    data = response.json()
    assert data["latest_years"]["circulation"] == "2023"
    assert data["totals"]["circulation"] == 1900
    assert data["branch_count"] == 2


def test_overview_includes_year_aligned_analytics_and_branch_map_data(sample_data):
    payload = client.get("/overview").json()
    assert {item["code"] for item in payload["branches"]} == {"BR001", "BR002"}
    assert payload["branches"][0]["year_opened"] in {"1998", "1972"}
    assert payload["annual_values"]["visits"][-1]["values"]["BR001"] == 550
    assert set(payload["tier_trends"]["visits"][-1]["tiers"]) == {"DL", "NL"}


def test_comparison_backend_caps_selection_at_five(monkeypatch):
    from app.services import analytics
    branches = [
        {"code": f"BR{index:03d}", "name": f"Branch {index}", "service_tier": "NL", "service_tier_code": "NL", "services": []}
        for index in range(1, 7)
    ]
    monkeypatch.setattr(analytics, "branch_records", lambda: branches)
    monkeypatch.setattr(analytics, "observations", lambda: [])
    analytics._compare_cached.cache_clear()
    try:
        result = analytics.compare([branch["code"] for branch in branches])
        assert len(result["branches"]) == 5
    finally:
        analytics._compare_cached.cache_clear()


def test_event_results_include_filtered_discovery_breakdowns(sample_data):
    payload = client.get("/events/recommendations").json()
    assert payload["analysis"]["total_upcoming"] == 2
    assert {item["label"] for item in payload["analysis"]["types"]} == {"Workshop", "Reading"}
    assert {item["label"] for item in payload["analysis"]["audiences"]} == {"Families", "Adults"}
    filtered = client.get("/events/recommendations?audience=Families").json()
    assert filtered["analysis"]["total_upcoming"] == 1
    assert [item["label"] for item in filtered["analysis"]["audiences"]] == ["Families"]
    by_type = client.get("/events/recommendations?event_type=Reading").json()
    assert [event["id"] for event in by_type["events"]] == ["EV002"]
    by_branch = client.get("/events/recommendations?branch=BR001").json()
    assert [event["id"] for event in by_branch["events"]] == ["EV001"]


def test_branch_map_metadata_is_normalized(sample_data):
    branches = client.get("/branches").json()
    maple = next(item for item in branches if item["code"] == "BR001")
    assert maple["type_of_library"] == "Neighbourhood Library"
    assert maple["year_opened"] == "1998"


def test_branch_detail_and_forecast(sample_data):
    detail = client.get("/branches/BR001")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["branch"]["name"] == "Maple Branch"
    assert payload["branch"]["services"] == ["KidsStop"]
    forecasts = client.get("/branches/BR001/forecasts").json()
    assert forecasts["circulation"]["available"] is True
    assert forecasts["circulation"]["method"] == "ARIMA"
    assert [item["year"] for item in forecasts["circulation"]["forecasts"]] == [2025, 2026]


def test_comparison_returns_branch_year_values_without_rankings(sample_data):
    response = client.get("/comparisons/data?branches=BR001,BR002")
    assert response.status_code == 200
    data = response.json()
    assert [branch["code"] for branch in data["branches"]] == ["BR001", "BR002"]
    row_2023 = next(row for row in data["metrics"]["visits"] if row["year"] == "2023")
    assert row_2023["values"] == {"BR001": 550, "BR002": 450}


def test_event_recommendations_and_registration_filter(sample_data):
    all_events = client.get("/events/recommendations").json()
    assert all_events["total"] == 2
    open_events = client.get("/events/recommendations?registration=available").json()
    assert [event["id"] for event in open_events["events"]] == ["EV001"]
    assert open_events["events"][0]["registration_status"] == "Registration open"


def test_search_and_csv_export(sample_data):
    search = client.get("/search?q=Maple").json()
    assert search["branches"][0]["code"] == "BR001"
    export = client.get("/exports/observations.csv?metric=visits")
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("text/csv")
    assert "branch_code" in export.text
    assert "visits" in export.text


def test_missing_branch_and_graph_api_errors(sample_data, monkeypatch):
    missing = client.get("/branches/DOES-NOT-EXIST")
    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("application/json")
    assert missing.json()["error"] == "Branch not found."
    monkeypatch.setattr(relate_service, "RELATE_FILE", sample_data / "not-present.rl")
    ask = client.post("/ask", json={"question": "What services are available?", "branch_code": "BR001"})
    assert ask.status_code == 503
    assert "not-present.rl" in ask.json()["error"]


def test_graph_adapter_uses_read_only_parameterized_schema_queries(sample_data, monkeypatch):
    tmp_path = sample_data
    graph_path = tmp_path / "tpl_library_graph.rl"
    graph_path.write_bytes(b"placeholder")
    monkeypatch.setattr(relate_service, "RELATE_FILE", graph_path)

    class Cursor:
        def __init__(self, rows):
            self.rows = rows
        def fetchall(self):
            return self.rows

    class FakeConnection:
        def __init__(self):
            self.closed = False
            self.queries = []
        def execute(self, statement, params=None):
            self.queries.append((statement, params or {}))
            if "CALL db.labels()" in statement:
                return Cursor([{"label": "Branch"}])
            if "CALL db.relationshipTypes()" in statement:
                return Cursor([{"relationshipType": "OFFERS_SERVICE"}])
            if "CALL db.schema.nodeTypeProperties()" in statement:
                return Cursor([
                    {"nodeLabels": ["Branch"], "propertyName": "name"},
                    {"nodeLabels": ["Branch"], "propertyName": "branch_code"},
                ])
            if "MATCH (n:`Branch`)" in statement:
                return Cursor([
                    {
                        "labels": ["Branch"],
                        "properties": {"name": "Maple Branch", "branch_code": "BR001", "PhysicalBranch": 1},
                        "relationship_type": "OFFERS_SERVICE",
                        "related_labels": ["ServiceOffering"],
                        "related_properties": {"name": "Digital Innovation Hub"},
                    },
                    {
                        "labels": ["Branch"],
                        "properties": {"name": "Maple Branch Virtual", "branch_code": "VIRTUAL", "PhysicalBranch": 0},
                        "relationship_type": None,
                        "related_labels": [],
                        "related_properties": {},
                    },
                ])
            return Cursor([])
        def close(self):
            self.closed = True

    connections = []
    def connect(*, database, read_only):
        assert database == str(graph_path)
        assert read_only is True
        connection = FakeConnection()
        connections.append(connection)
        return connection

    fake_module = SimpleNamespace(connect=connect, __version__="1.1.0")
    monkeypatch.setitem(sys.modules, "relate", fake_module)
    schema = relate_service.graph_schema()
    assert schema["labels"] == ["Branch"]
    assert schema["relationship_types"] == ["OFFERS_SERVICE"]

    result = relate_service.ask("Show Maple Branch services", "BR001")
    assert result["status"] == "ok"
    assert result["answer"].startswith("The closest matches are Maple Branch")
    assert result["highlights"][0]["title"] == "Maple Branch"
    assert any(item["value"] == "BR001" for item in result["highlights"][0]["details"])
    assert all(item["properties"].get("name") != "Maple Branch Virtual" for item in result["evidence"])
    assert result["evidence"][0]["connections"][0]["relationship_type"] == "OFFERS_SERVICE"
    graph_connection = connections[-1]
    search_query = [item for item in graph_connection.queries if "MATCH (n:`Branch`)" in item[0]][0]
    assert "maple" in search_query[1].values()
    assert all(connection.closed for connection in connections)


def test_physical_branch_zero_is_excluded_from_all_metrics_and_branch_lists(tmp_path, monkeypatch):
    monkeypatch.setattr(data_store, "DATA_DIR", tmp_path)
    write_csv(
        tmp_path / "tpl-branch-general-information.csv",
        ["BranchCode", "BranchName", "PhysicalBranch", "ServiceTier", "Latitude", "Longitude"],
        [["P001", "Physical One", 1, "NL", 43.7, -79.4], ["P002", "Physical Two", "true", "DL", 43.8, -79.5], ["V001", "Virtual Branch", 0, "NL", 0, 0]],
    )
    metric_specs = {
        "tpl-circulation-annual-by-branch.csv": "Circulation",
        "tpl-visits-annual-by-branch.csv": "Visits",
        "tpl-workstation-usage-annual-by-branch.csv": "Sessions",
        "tpl-card-registrations-annual-by-branch.csv": "Registrations",
    }
    for filename, value_field in metric_specs.items():
        write_csv(tmp_path / filename, ["BranchCode", "Year", value_field, "PhysicalBranch"], [
            ["P001", 2023, 100, 1], ["P002", 2023, 200, 1],
            ["P002", 2023, 9999, 0], ["V001", 2023, 9999, 0]
        ])
    write_csv(tmp_path / "tpl-events-feed.csv", ["EventID", "Title", "StartDate", "LocationName", "BranchCode", "PhysicalBranch"], [
        ["E1", "Physical event", "2099-01-01", "Physical One", "P001", 1],
        ["E2", "Virtual event", "2099-01-01", "Virtual Branch", "V001", 0],
        ["E3", "Flagged event", "2099-01-01", "Physical Two", "P002", 0],
        ["E4", "Name-linked event", "2099-01-02", "Physical One", "", 1]
    ])
    data_store.refresh_data_cache()
    assert [item["code"] for item in data_store.branch_records()] == ["P001", "P002"]
    assert {item["branch_code"] for item in data_store.observations()} == {"P001", "P002"}
    assert client.get("/overview").json()["branch_count"] == 2
    assert client.get("/overview").json()["totals"]["circulation"] == 300
    assert [item["id"] for item in data_store.event_records()] == ["E1", "E4"]
    branch_events = client.get("/events/recommendations?branch=P001").json()["events"]
    assert {item["id"] for item in branch_events} == {"E1", "E4"}
    assert "V001" not in [item["code"] for item in client.get("/branches").json()]
    data_store.refresh_data_cache()


def test_data_revision_tracks_csv_graph_and_frontend_version(sample_data, monkeypatch):
    from main import STATIC_VERSION
    before = data_store.data_revision()
    graph = sample_data / "tpl_library_graph.rl"
    graph.write_bytes(b"updated graph snapshot")
    after_graph = data_store.data_revision()
    assert before != after_graph
    csv_path = sample_data / "tpl-branch-general-information.csv"
    csv_path.write_text(csv_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    after_csv = data_store.data_revision()
    assert after_graph != after_csv
    page = client.get("/").text
    assert f"{STATIC_VERSION}-{after_csv}" in page


def test_overview_is_cached_and_data_routes_have_http_cache_headers(sample_data):
    first = client.get("/overview")
    second = client.get("/overview")
    assert first.status_code == second.status_code == 200
    assert "max-age=300" in first.headers.get("cache-control", "")
    from app.services.analytics import overview
    assert overview.cache_info().hits >= 1


def test_events_options_are_dropdown_values(sample_data):
    payload = client.get("/events/options").json()
    assert "Families" in payload["audiences"]
    assert "English" in payload["languages"]
    assert any(branch["code"] == "BR001" for branch in payload["branches"])


def test_frontend_uses_plotly_tabs_and_mobile_friendly_comparison_controls():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    html = (root / "templates" / "index.html").read_text(encoding="utf-8")
    js = (root / "static" / "js" / "app.js").read_text(encoding="utf-8")
    css = (root / "static" / "css" / "app.css").read_text(encoding="utf-8")
    assert "plotly-2.35.2.min.js" in js
    assert "role=\"tablist\"" in js
    assert "compare-branch-option" in js
    assert "of 5 selected" in js
    assert "slice(0, 5)" in js
    assert 'id="branch-select"' in js
    assert "Ctrl (Windows)" not in js and "Command (Mac)" not in js
    assert "data-status" not in html
    assert "--focus: #8ed8ef" in css
    assert 'html[data-scale="small"] { font-size: 12px; }' in css
    assert 'html[data-scale="medium"] { font-size: 16px; }' in css
    assert 'html[data-scale="large"] { font-size: 20px; }' in css
    assert "--button-text: #10212a" in css
    assert ".button.secondary" in css and "color: var(--text)" in css
    assert "role=\"tabpanel\" tabindex=\"0\"" in js
    assert "aria-controls=\"comparison-view-annual\"" in js
    assert "enableTabKeyboard(comparisonTabs" in js
    assert "enableTabKeyboard(metricTabList" in js
    assert "answer-highlights" in js
    assert "Annual ${metricName(metric)}" in js
    assert "Network vs. Service-Tier Trends" in js
    assert "Metric Distribution" in js
    assert "Annual Metrics vs. Square Footage" in js
    assert "Annual metric correlation" in js
    assert "Overachievers" in js and "Underutilized" in js
    assert "View branch locations as a table" in js
    assert "map-branch-select" in js
    assert "Branch details" not in js
    assert "Find a Branch" not in js
    assert "Branches by service tier" not in js
    assert "Annual Trend" not in js
    assert "Export CSV" not in js
    assert "Type of Library:" in js and "Year Opened:" in js and "# of Workstations:" in js
    assert "branch.lat !== null" in js and "branch.lon !== null" in js
    assert "Download matching events CSV" in js
    assert "Events by audience" in js and "Events by language" in js
    assert "View ${label.toLowerCase()} data" not in js
    assert "@media (max-width: 850px)" in css and "@media (max-width: 560px)" in css
    assert ".text-button, .settings select {" in css
    control_rule = css.split(".text-button, .settings select {", 1)[1].split("}", 1)[0]
    assert "height: 44px;" in control_rule and "min-height: 44px;" in control_rule and "max-height: 44px;" in control_rule
    assert "hovermode: 'closest'" in js and "x unified" not in js
    assert "data-cache-version" in html
    assert "CACHE_STALE_MS" in js and "sessionStorage" in js


def test_custom_404_page_and_unknown_route_is_html():
    page = client.get("/not-a-real-page")
    assert page.status_code == 404
    assert "Page not found" in page.text
    assert "Go to Overview" in page.text
    missing = client.get("/not-a-real-route")
    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("text/html")
