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
        ["BranchCode", "BranchName", "Address", "ServiceTier", "SquareFootage", "Workstations", "Latitude", "Longitude", "KidsStop", "LeadingReading"],
        [
            ["BR001", "Maple Branch", "100 Main Street", "NL", 12000, 24, 43.70, -79.40, "Yes", "No"],
            ["BR002", "River Branch", "200 River Road", "DL", 18000, 32, 43.72, -79.42, "No", "Yes"],
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
    for path in ["/", "/branch-insights", "/comparisons", "/programs-events", "/data-methodology"]:
        response = client.get(path)
        assert response.status_code == 200
        assert "LibraryTO" in response.text
        assert "Inter" in response.text


def test_empty_state_overview_and_exact_expected_names():
    response = client.get("/api/overview")
    assert response.status_code == 200
    assert response.json()["branch_count"] == 0
    status = client.get("/api/system/status").json()
    assert status["datasets"]["branches"]["filename"] == "tpl-branch-general-information.csv"
    assert status["datasets"]["events"]["filename"] == "tpl-events-feed.csv"
    assert status["relate"]["filename"] == "tpl_library_graph.rl"


def test_overview_uses_latest_year_only(sample_data):
    response = client.get("/api/overview")
    data = response.json()
    assert data["latest_years"]["circulation"] == "2023"
    assert data["totals"]["circulation"] == 1900
    assert data["coverage"]["circulation"] == 2
    assert data["branch_count"] == 2


def test_branch_detail_and_forecast(sample_data):
    detail = client.get("/api/branches/BR001")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["branch"]["name"] == "Maple Branch"
    assert payload["branch"]["services"] == ["KidsStop"]
    forecasts = client.get("/api/branches/BR001/forecasts").json()
    assert forecasts["circulation"]["available"] is True
    assert len(forecasts["circulation"]["forecasts"]) == 3
    assert forecasts["circulation"]["naive_baseline_mae"] is not None


def test_comparison_returns_branch_year_values_without_rankings(sample_data):
    response = client.get("/api/compare?branches=BR001,BR002")
    assert response.status_code == 200
    data = response.json()
    assert [branch["code"] for branch in data["branches"]] == ["BR001", "BR002"]
    row_2023 = next(row for row in data["metrics"]["visits"] if row["year"] == "2023")
    assert row_2023["values"] == {"BR001": 550, "BR002": 450}


def test_event_recommendations_and_registration_filter(sample_data):
    all_events = client.get("/api/events/recommendations?start_date=2099-01-01").json()
    assert all_events["total"] == 2
    open_events = client.get("/api/events/recommendations?start_date=2099-01-01&registration=available").json()
    assert [event["id"] for event in open_events["events"]] == ["EV001"]
    assert open_events["events"][0]["registration_status"] == "Registration open"


def test_search_and_csv_export(sample_data):
    search = client.get("/api/search?q=Maple").json()
    assert search["branches"][0]["code"] == "BR001"
    export = client.get("/api/export/observations.csv?metric=visits")
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("text/csv")
    assert "branch_code" in export.text
    assert "visits" in export.text


def test_missing_branch_and_graph_api_errors(sample_data, monkeypatch):
    missing = client.get("/api/branches/DOES-NOT-EXIST")
    assert missing.status_code == 404
    monkeypatch.setattr(relate_service, "RELATE_FILE", sample_data / "not-present.rl")
    ask = client.post("/api/ask", json={"question": "What services are available?", "branch_code": "BR001"})
    assert ask.status_code == 503
    assert "not-present.rl" in ask.json()["error"]


def test_graph_adapter_uses_read_only_parameterized_schema_queries(tmp_path, monkeypatch):
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
                return Cursor([{
                    "labels": ["Branch"],
                    "properties": {"name": "Maple Branch", "branch_code": "BR001"},
                    "relationship_type": "OFFERS_SERVICE",
                    "related_labels": ["ServiceOffering"],
                    "related_properties": {"name": "Digital Innovation Hub"},
                }])
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
    assert result["evidence"][0]["connections"][0]["relationship_type"] == "OFFERS_SERVICE"
    graph_connection = connections[-1]
    search_query = [item for item in graph_connection.queries if "MATCH (n:`Branch`)" in item[0]][0]
    assert "maple" in search_query[1].values()
    assert all(connection.closed for connection in connections)


def test_custom_404_page_and_json_api_404():
    page = client.get("/not-a-real-page")
    assert page.status_code == 404
    assert "Page not found" in page.text
    assert "Go to Overview" in page.text
    api = client.get("/api/not-a-real-route")
    assert api.status_code == 404
    assert api.headers["content-type"].startswith("application/json")
