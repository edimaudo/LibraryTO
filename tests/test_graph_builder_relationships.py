from __future__ import annotations

from scripts import build_relate_graph as builder


class Cursor:
    def __init__(self, rows=None):
        self.rows = rows or []

    def fetchall(self):
        return self.rows


class RecordingConnection:
    def __init__(self):
        self.executed = []
        self.executemany_calls = []
        self.commits = 0

    def execute(self, statement, params=None):
        self.executed.append((statement, params or {}))
        if "db.schema.nodeTypeProperties" in statement:
            return Cursor([
                {"nodeLabels": ["Neighbourhoods"], "propertyName": "NBHDName"},
                {"nodeLabels": ["Neighbourhoods"], "propertyName": "NBHDNo"},
            ])
        if "RETURN count(r) AS count" in statement:
            return Cursor([{"count": 1}])
        return Cursor([])

    def executemany(self, statement, rows):
        self.executemany_calls.append((statement, rows))

    def commit(self):
        self.commits += 1


def test_builder_creates_only_source_grounded_relationships_for_physical_branches():
    datasets = {
        "tpl-branch-general-information.csv": [
            {
                "_libraryto_source_key": "branches:1", "BranchCode": "P1", "BranchName": "Physical One",
                "PhysicalBranch": "1", "NBHDNo": "12", "NBHDName": "Sample Neighbourhood",
                "WardNo": "3", "WardName": "Sample Ward", "DIH": "1", "PublicWashroom": "1",
            },
            {
                "_libraryto_source_key": "branches:2", "BranchCode": "V1", "BranchName": "Virtual One",
                "PhysicalBranch": "0", "NBHDNo": "12", "NBHDName": "Sample Neighbourhood",
                "WardNo": "3", "WardName": "Sample Ward", "DIH": "1", "PublicWashroom": "1",
            },
        ],
        "tpl-circulation-annual-by-branch.csv": [
            {"_libraryto_source_key": "circulation:1", "BranchCode": "P1", "Year": "2024", "Circulation": "1000"},
            {"_libraryto_source_key": "circulation:2", "BranchCode": "V1", "Year": "2024", "Circulation": "9000"},
        ],
        "tpl-visits-annual-by-branch.csv": [],
        "tpl-workstation-usage-annual-by-branch.csv": [],
        "tpl-card-registrations-annual-by-branch.csv": [],
        "tpl-events-feed.csv": [
            {"_libraryto_source_key": "events:1", "EventID": "E1", "Title": "Physical Event", "BranchCode": "P1"},
            {"_libraryto_source_key": "events:2", "EventID": "E2", "Title": "Virtual Event", "BranchCode": "V1"},
        ],
        "tpl-Neighbourhoods.csv": [],
    }
    connection = RecordingConnection()

    counts = builder.build_relationships(connection, datasets)

    statements = [statement for statement, _ in connection.executed]
    statements.extend(statement for statement, _ in connection.executemany_calls)
    combined = "\n".join(statements)
    for relationship in (
        "HAS_CIRCULATION_RECORD", "HOSTS_EVENT", "IN_NEIGHBOURHOOD", "IN_WARD",
        "OFFERS_SERVICE", "HAS_FACILITY", "HAS_GEOGRAPHY_RECORD",
    ):
        assert relationship in combined

    circulation_batch = next(rows for statement, rows in connection.executemany_calls if "HAS_CIRCULATION_RECORD" in statement)
    assert circulation_batch == [{"branch_key": "branches:1", "target_key": "circulation:1"}]
    event_batch = next(rows for statement, rows in connection.executemany_calls if "HOSTS_EVENT" in statement)
    assert event_batch == [{"branch_key": "branches:1", "target_key": "events:1"}]
    assert counts["IN_NEIGHBOURHOOD"] == 1
    assert counts["IN_WARD"] == 1
    assert counts["OFFERS_SERVICE"] == 1
    assert counts["HAS_FACILITY"] == 1
    assert connection.commits >= 1
