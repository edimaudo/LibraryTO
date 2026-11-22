from __future__ import annotations

from types import SimpleNamespace

from app.services import graph_enhancements as graph


def test_service_synonyms_resolve_to_source_directory_flags():
    assert graph._service_from_question("Which branches have a digital innovation hub?") == "dih"
    assert graph._service_from_question("List branches with a youth hub") == "youthhub"
    assert graph._service_from_question("Which branches offer adult literacy?") == "adultliteracyprogram"
    assert graph._service_from_question("Which branches have public washrooms?") == "publicwashroom"


def test_area_intent_recognizes_ward_and_neighbourhood_spellings():
    assert graph._area_intent("Which branches are in Ward 3?") == "ward"
    assert graph._area_intent("Which branches share this neighborhood?") == "neighbourhood"
    assert graph._area_intent("Which branches share this neighbourhood?") == "neighbourhood"


def test_activity_intensity_calculates_weighted_network_and_branch_rates(monkeypatch):
    sample = {
        "branches": [
            {"code": "A", "name": "Alpha", "square_footage": 1000},
            {"code": "B", "name": "Beta", "square_footage": 2000},
            {"code": "C", "name": "No floor area", "square_footage": None},
        ],
        "annual_values": {
            "visits": [
                {"year": "2023", "values": {"A": 10000, "B": 30000, "C": 5000}},
            ],
        },
    }
    monkeypatch.setattr("app.services.analytics.overview", lambda: sample)
    result = graph.activity_intensity_payload()
    year = result["metrics"]["visits"]["years"][0]
    assert year["network_per_1000_sq_ft"] == 13333.333
    assert year["branches_with_values"] == 2
    assert year["branch_values"][0]["code"] == "B"
    assert year["branch_values"][1]["per_1000_sq_ft"] == 10000.0


def test_activity_intensity_can_be_scoped_to_selected_branches(monkeypatch):
    sample = {
        "branches": [
            {"code": "A", "name": "Alpha", "square_footage": 1000},
            {"code": "B", "name": "Beta", "square_footage": 2000},
        ],
        "annual_values": {"circulation": [{"year": "2024", "values": {"A": 1000, "B": 6000}}]},
    }
    monkeypatch.setattr("app.services.analytics.overview", lambda: sample)
    result = graph.activity_intensity_payload(["A"])
    year = result["metrics"]["circulation"]["years"][0]
    assert result["scope"] == "selected branches"
    assert [row["code"] for row in year["branch_values"]] == ["A"]
    assert year["network_per_1000_sq_ft"] == 1000.0


def test_qna_uses_in_ward_and_offers_service_relationships():
    schema = {
        "BranchGeneralInformation": {"branchcode": "BranchCode", "branchname": "BranchName"},
        "LibraryWard": {"name": "name", "wardno": "ward_no"},
        "LibraryService": {"servicekey": "service_key", "servicename": "service_name"},
    }

    class Cursor:
        def __init__(self, rows):
            self._rows = rows
        def fetchall(self):
            return self._rows

    class Connection:
        def __init__(self):
            self.queries = []
        def execute(self, statement, params=None):
            self.queries.append((statement, params or {}))
            if "MATCH (a:`LibraryWard`)" in statement:
                return Cursor([])
            if "OFFERS_SERVICE" in statement:
                return Cursor([{
                    "branch_properties": {"BranchCode": "B1", "BranchName": "North Branch"},
                    "service_properties": {"service_key": "dih", "service_name": "Digital Innovation Hub"},
                    "metric_properties": [],
                }])
            return Cursor([])

    connection = Connection()
    selected = {"code": "A1", "name": "Anchor Branch"}
    result = graph.answer_connected_question(connection, schema, "Which branches in Ward 3 offer a Digital Innovation Hub?", selected)
    assert result is not None
    assert result["status"] == "ok"
    assert "North Branch" in result["answer"]
    graph_query = next(query for query, _ in connection.queries if "OFFERS_SERVICE" in query)
    assert "IN_WARD" in graph_query
    assert "OFFERS_SERVICE" in graph_query
    assert "(anchor:`BranchGeneralInformation`)-[:IN_WARD]" in graph_query
    assert any(params.get("area_value") == "3" for _, params in connection.queries)


def test_qna_returns_selected_branch_services_from_relationships():
    schema = {
        "BranchGeneralInformation": {"branchcode": "BranchCode", "branchname": "BranchName"},
        "LibraryService": {"servicekey": "service_key", "servicename": "service_name"},
    }

    class Cursor:
        def fetchall(self):
            return [{"branch_properties": {"BranchCode": "A1", "BranchName": "Anchor Branch"}, "service_properties": {"service_name": "Youth Hub"}, "metric_properties": []}]

    class Connection:
        def execute(self, statement, params=None):
            assert "OFFERS_SERVICE" in statement
            assert params["anchor_code"] == "a1"
            return Cursor()

    result = graph.answer_connected_question(Connection(), schema, "What services does this branch offer?", {"code": "A1", "name": "Anchor Branch"})
    assert result["scope_verified"] is True
    assert "Youth Hub" in result["answer"]
