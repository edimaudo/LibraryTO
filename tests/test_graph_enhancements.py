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


def test_explorer_returns_selected_branch_properties_and_connected_record_properties(monkeypatch, tmp_path):
    graph_path = tmp_path / "tpl_library_graph.rl"
    graph_path.write_bytes(b"fake")
    monkeypatch.setattr(graph, "RELATE_FILE", graph_path)
    monkeypatch.setattr(graph, "branch_records", lambda: [{"code": "A1", "name": "Anchor Branch"}])

    class Cursor:
        def __init__(self, rows):
            self._rows = rows
        def fetchall(self):
            return self._rows

    class Connection:
        def __init__(self):
            self.closed = False
        def execute(self, statement, params=None):
            if "db.schema.nodeTypeProperties" in statement:
                return Cursor([
                    {"nodeLabels": ["BranchGeneralInformation"], "propertyName": "BranchCode"},
                    {"nodeLabels": ["BranchGeneralInformation"], "propertyName": "BranchName"},
                    {"nodeLabels": ["BranchGeneralInformation"], "propertyName": "WardName"},
                    {"nodeLabels": ["CirculationAnnualByBranch"], "propertyName": "Year"},
                ])
            if "db.relationshipTypes" in statement:
                return Cursor([{"relationshipType": "HAS_CIRCULATION_RECORD"}])
            if "RETURN count(n)" in statement:
                return Cursor([{"count": 1}])
            if "RETURN count(r)" in statement:
                return Cursor([{"count": 2}])
            if "RETURN properties(b) AS properties" in statement:
                return Cursor([{"properties": {"BranchCode": "A1", "BranchName": "Anchor Branch", "WardName": "Ward 1"}}])
            if "type(r) AS relationship_type" in statement:
                return Cursor([{
                    "relationship_type": "HAS_CIRCULATION_RECORD",
                    "labels": ["CirculationAnnualByBranch"],
                    "properties": {"BranchCode": "A1", "Year": 2023, "Circulation": 12345},
                    "relationship_properties": {},
                }])
            return Cursor([])
        def close(self):
            self.closed = True

    connection = Connection()
    monkeypatch.setattr(graph, "open_graph", lambda read_only=True: connection)
    result = graph.explorer_snapshot(["A1"])
    selected = result["selected"][0]
    assert selected["properties"]["WardName"] == "Ward 1"
    assert selected["connections"][0]["properties"]["Circulation"] == 12345
    assert result["relationship_count"] == 2
    assert connection.closed is True


def test_qna_finds_peer_branches_through_shared_service_node():
    schema = {
        "BranchGeneralInformation": {"branchcode": "BranchCode", "branchname": "BranchName"},
        "LibraryService": {"servicekey": "service_key", "servicename": "service_name"},
    }

    class Cursor:
        def fetchall(self):
            return [{
                "branch_properties": {"BranchCode": "B2", "BranchName": "Peer Branch"},
                "service_properties": {"service_key": "dih", "service_name": "Digital Innovation Hub"},
                "metric_properties": [],
            }]

    class Connection:
        def __init__(self):
            self.statement = ""
        def execute(self, statement, params=None):
            self.statement = statement
            assert params["anchor_code"] == "a1"
            assert params["service_key"] == "dih"
            return Cursor()

    connection = Connection()
    result = graph.answer_connected_question(
        connection,
        schema,
        "Which other branches offer a Digital Innovation Hub?",
        {"code": "A1", "name": "Anchor Branch"},
    )
    assert result["status"] == "ok"
    assert "Peer Branch" in result["answer"]
    assert "OFFERS_SERVICE" in connection.statement
    assert "anchor" in connection.statement and "peer" in connection.statement


def test_yearless_overview_circulation_ranking_traverses_all_year_relationships():
    schema = {
        "BranchGeneralInformation": {"branchcode": "BranchCode", "branchname": "BranchName"},
        "CirculationAnnualByBranch": {"branchcode": "BranchCode", "year": "Year", "circulation": "Circulation"},
        "LibraryWard": {"name": "name", "wardno": "ward_no"},
        "LibraryNeighbourhood": {"name": "name", "neighbourhoodno": "neighbourhood_no"},
        "LibraryService": {"servicekey": "service_key", "servicename": "service_name"},
    }

    class Cursor:
        def fetchall(self):
            return [
                {"branch_properties": {"BranchCode": "A1", "BranchName": "Alpha Branch"}, "metric_properties": {"Year": 2018, "Circulation": 1800}, "service_properties": []},
                {"branch_properties": {"BranchCode": "B2", "BranchName": "Beta Branch"}, "metric_properties": {"Year": 2024, "Circulation": 1200}, "service_properties": []},
            ]

    class Connection:
        def __init__(self):
            self.statement = ""
            self.parameters = {}
        def execute(self, statement, params=None):
            self.statement = statement
            self.parameters = params or {}
            return Cursor()

    connection = Connection()
    result = graph.answer_connected_question(
        connection, schema, "What branch had the highest annual circulation?", None
    )
    assert result is not None
    assert "physical branch network" in result["answer"]
    assert "Alpha Branch (1,800) in 2018" in result["answer"]
    assert "2024: Beta Branch (1,200)" in result["answer"]
    assert "HAS_CIRCULATION_RECORD" in connection.statement
    assert "metric.`Year`" not in connection.statement


def test_selected_branch_cross_branch_metric_question_excludes_anchor_branch():
    schema = {
        "BranchGeneralInformation": {"branchcode": "BranchCode", "branchname": "BranchName"},
        "CirculationAnnualByBranch": {"branchcode": "BranchCode", "year": "Year", "circulation": "Circulation"},
        "LibraryWard": {"name": "name", "wardno": "ward_no"},
        "LibraryNeighbourhood": {"name": "name", "neighbourhoodno": "neighbourhood_no"},
        "LibraryService": {"servicekey": "service_key", "servicename": "service_name"},
    }

    class Cursor:
        def fetchall(self):
            return [{
                "branch_properties": {"BranchCode": "B2", "BranchName": "Beta Branch"},
                "metric_properties": {"Year": 2024, "Circulation": 1200},
                "service_properties": [],
            }]

    class Connection:
        def __init__(self):
            self.statement = ""
            self.parameters = {}
        def execute(self, statement, params=None):
            self.statement = statement
            self.parameters = params or {}
            return Cursor()

    connection = Connection()
    result = graph.answer_connected_question(
        connection,
        schema,
        "Which other branches had the highest annual circulation?",
        {"code": "A1", "name": "Anchor Branch"},
    )
    assert result is not None
    assert "Beta Branch" in result["answer"]
    assert "other physical branches (excluding Anchor Branch)" in result["answer"]
    assert all("Anchor Branch" not in item["value"] for item in result["highlights"][0]["details"])
    assert "<> $anchor_code" in connection.statement
    assert connection.parameters["anchor_code"] == "a1"


def test_asking_selected_branch_for_its_ward_uses_directory_fallback():
    schema = {
        "BranchGeneralInformation": {"branchcode": "BranchCode", "branchname": "BranchName"},
        "LibraryWard": {"name": "name", "wardno": "ward_no"},
    }
    result = graph.answer_connected_question(
        object(), schema, "What ward is this branch in?", {"code": "A1", "name": "Anchor Branch"}
    )
    assert result is None


def test_branch_qna_finds_shared_services_with_peers_in_selected_ward():
    schema = {
        "BranchGeneralInformation": {"branchcode": "BranchCode", "branchname": "BranchName"},
        "LibraryWard": {"name": "name", "wardno": "ward_no"},
        "LibraryService": {"servicekey": "service_key", "servicename": "service_name"},
    }

    class Cursor:
        def fetchall(self):
            return [{
                "branch_properties": {"BranchCode": "B2", "BranchName": "Peer Branch"},
                "area_properties": {"name": "Sample Ward", "ward_no": "3"},
                "metric_properties": [],
                "service_properties": {"service_key": "dih", "service_name": "Digital Innovation Hub"},
            }]

    class Connection:
        def __init__(self):
            self.statements = []
        def execute(self, statement, params=None):
            self.statements.append(statement)
            if "MATCH (a:`LibraryWard`)" in statement:
                return Cursor()
            return Cursor()

    connection = Connection()
    result = graph.answer_connected_question(
        connection,
        schema,
        "Which other branches in the same ward offer the same services as this branch?",
        {"code": "A1", "name": "Anchor Branch"},
    )
    combined = " ".join(connection.statements)
    assert result is not None
    assert "Peer Branch" in result["answer"]
    assert "IN_WARD" in combined
    assert "OFFERS_SERVICE" in combined
    assert "anchor_code" in combined


def test_peer_branch_traversal_returns_shared_area_and_service_context():
    class Cursor:
        def __init__(self, rows):
            self._rows = rows
        def fetchall(self):
            return self._rows

    class Connection:
        def __init__(self):
            self.queries = []
        def execute(self, statement, params=None):
            self.queries.append(statement)
            if "IN_NEIGHBOURHOOD" in statement:
                return Cursor([{
                    "area_properties": {"name": "Northview", "neighbourhood_no": 11},
                    "peer_properties": {"BranchCode": "B2", "BranchName": "Beta Branch"},
                    "service_properties": [
                        {"service_name": "Youth Hub"},
                        {"service_name": "Digital Innovation Hub"},
                    ],
                }])
            return Cursor([])

    connection = Connection()
    schema = {
        "BranchGeneralInformation": {"branchcode": "BranchCode", "branchname": "BranchName"},
        "LibraryNeighbourhood": {"name": "name", "neighbourhoodno": "neighbourhood_no"},
        "LibraryWard": {"name": "name", "wardno": "ward_no"},
        "LibraryService": {"servicekey": "service_key", "servicename": "service_name"},
    }
    result = graph._peer_branches_in_shared_areas(
        connection,
        "BranchGeneralInformation",
        schema["BranchGeneralInformation"],
        "A1",
        schema,
    )

    assert len(result) == 1
    assert result[0]["branch_code"] == "B2"
    assert result[0]["branch_name"] == "Beta Branch"
    assert result[0]["contexts"] == [{"context_type": "neighbourhood", "context_name": "Northview (No. 11)"}]
    assert result[0]["services"] == ["Digital Innovation Hub", "Youth Hub"]
    assert any("IN_NEIGHBOURHOOD" in query for query in connection.queries)
    assert any("IN_WARD" in query for query in connection.queries)
