from __future__ import annotations

import pytest

from app.services import graph_enhancements as graph


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self):
        self.closed = False
        self.statements = []

    def execute(self, statement, params=None):
        self.statements.append((statement, params or {}))
        if "RETURN count(n) AS count" in statement:
            return Cursor([{"count": 2}])
        return Cursor([
            {"labels": ["BranchGeneralInformation"], "properties": {
                "BranchCode": "AA", "BranchName": "Alpha Branch", "PresentSiteYear": 1950,
                "_libraryto_source_key": "private:1",
            }},
            {"labels": ["BranchGeneralInformation"], "properties": {
                "BranchCode": "AB", "BranchName": "Alpine Branch", "PresentSiteYear": 1960,
            }},
        ])

    def close(self):
        self.closed = True


def test_graph_inspector_returns_bounded_nodes_and_hides_private_source_keys(monkeypatch):
    connection = FakeConnection()
    monkeypatch.setattr(graph, "open_graph", lambda read_only=True: connection)
    monkeypatch.setattr(graph, "_schema", lambda _connection: (
        {"BranchGeneralInformation": {
            "branchcode": "BranchCode", "branchname": "BranchName", "presentsiteyear": "PresentSiteYear",
            "librarytosourcesourcekey": "_libraryto_source_key",
        }},
        ["IN_WARD"],
    ))

    result = graph.inspect_graph_nodes("BranchGeneralInformation", "alp", limit=50, offset=0)

    assert result["available"] is True
    assert result["display_label"] == "Branch General Information"
    assert result["total"] == 2
    assert len(result["records"]) == 2
    assert "_libraryto_source_key" not in result["records"][0]["properties"]
    assert result["has_more"] is False
    assert connection.closed is True
    assert any("CONTAINS $search" in statement for statement, _ in connection.statements)


def test_graph_inspector_rejects_labels_not_in_discovered_schema(monkeypatch):
    connection = FakeConnection()
    monkeypatch.setattr(graph, "open_graph", lambda read_only=True: connection)
    monkeypatch.setattr(graph, "_schema", lambda _connection: ({"BranchGeneralInformation": {}}, []))

    with pytest.raises(ValueError, match="Choose a node label"):
        graph.inspect_graph_nodes("NoSuchLabel")
    assert connection.closed is True
