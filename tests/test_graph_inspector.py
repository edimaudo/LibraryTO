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
        rows = [
            {"labels": ["BranchGeneralInformation"], "properties": {
                "BranchCode": "AA", "BranchName": "Alpha Branch", "PresentSiteYear": 1950,
                "PhysicalBranch": "1", "_libraryto_source_key": "private:1",
            }},
            {"labels": ["BranchGeneralInformation"], "properties": {
                "BranchCode": "AB", "BranchName": "Alpine Branch", "PresentSiteYear": 1960,
                "PhysicalBranch": "1",
            }},
            {"labels": ["BranchGeneralInformation"], "properties": {
                "BranchCode": "V1", "BranchName": "Virtual Branch Record", "PhysicalBranch": "0",
            }},
        ]
        if "MATCH (n:`BranchGeneralInformation`)" in statement and "PhysicalBranch" in statement:
            rows = [row for row in rows if row["properties"].get("PhysicalBranch") == "1"]
        return Cursor(rows)

    def close(self):
        self.closed = True


def test_graph_inspector_limits_branch_directory_browse_to_physical_branches(monkeypatch):
    connection = FakeConnection()
    monkeypatch.setattr(graph, "open_graph", lambda read_only=True: connection)
    monkeypatch.setattr(graph, "_schema", lambda _connection: (
        {"BranchGeneralInformation": {
            "branchcode": "BranchCode", "branchname": "BranchName", "presentsiteyear": "PresentSiteYear",
            "physicalbranch": "PhysicalBranch", "librarytosourcesourcekey": "_libraryto_source_key",
        }},
        ["IN_WARD"],
    ))

    result = graph.inspect_graph_nodes("BranchGeneralInformation", "alp", limit=50, offset=0)

    assert result["available"] is True
    assert result["display_label"] == "Branch General Information"
    assert result["physical_branch_filter"] == "PhysicalBranch = 1"
    assert result["total"] == 2
    assert len(result["records"]) == 2
    assert {row["properties"]["BranchCode"] for row in result["records"]} == {"AA", "AB"}
    assert "_libraryto_source_key" not in result["records"][0]["properties"]
    assert result["has_more"] is False
    assert connection.closed is True
    assert any("CONTAINS $search" in statement for statement, _ in connection.statements)
    assert all(
        "toString(n.`PhysicalBranch`) = '1'" in statement
        for statement, _ in connection.statements
        if "MATCH (n:`BranchGeneralInformation`)" in statement
    )


def test_graph_inspector_rejects_labels_not_in_discovered_schema(monkeypatch):
    connection = FakeConnection()
    monkeypatch.setattr(graph, "open_graph", lambda read_only=True: connection)
    monkeypatch.setattr(graph, "_schema", lambda _connection: ({"BranchGeneralInformation": {}}, []))

    with pytest.raises(ValueError, match="Choose a node label"):
        graph.inspect_graph_nodes("NoSuchLabel")
    assert connection.closed is True


def test_branch_label_requires_physical_branch_flag():
    with pytest.raises(graph.GraphUnavailable, match="physical branch directory"):
        graph._branch_label({"BranchGeneralInformation": {"branchcode": "BranchCode", "branchname": "BranchName"}})


def test_peer_branch_query_requires_physical_flag_for_anchor_and_peer(monkeypatch):
    connection = FakeConnection()
    schema = {
        "BranchGeneralInformation": {
            "branchcode": "BranchCode", "branchname": "BranchName", "physicalbranch": "PhysicalBranch",
        },
        "LibraryNeighbourhood": {"name": "name", "neighbourhoodno": "neighbourhood_no"},
        "LibraryWard": {"name": "name", "wardno": "ward_no"},
        "LibraryService": {"servicekey": "service_key", "servicename": "service_name"},
    }
    graph._peer_branches_in_shared_areas(
        connection, "BranchGeneralInformation", schema["BranchGeneralInformation"], "AA", schema
    )
    peer_queries = [statement for statement, _ in connection.statements]
    assert peer_queries
    assert all("anchor.`PhysicalBranch`) = '1'" in query for query in peer_queries)
    assert all("peer.`PhysicalBranch`) = '1'" in query for query in peer_queries)


def test_explorer_snapshot_counts_only_physical_branch_nodes_and_edges(monkeypatch):
    schema = {
        "BranchGeneralInformation": {
            "branchcode": "BranchCode", "branchname": "BranchName", "physicalbranch": "PhysicalBranch",
        },
        "LibraryNeighbourhood": {"name": "name", "neighbourhoodno": "neighbourhood_no"},
        "LibraryWard": {"name": "name", "wardno": "ward_no"},
        "LibraryService": {"servicekey": "service_key", "servicename": "service_name"},
    }

    class SnapshotConnection:
        def __init__(self):
            self.closed = False
            self.statements = []

        def execute(self, statement, params=None):
            self.statements.append(statement)
            if "RETURN count(DISTINCT b) AS branches, count(r) AS relationships" in statement:
                return Cursor([{"branches": 1, "relationships": 6}])
            if "RETURN b.`BranchCode` AS code" in statement:
                return Cursor([{"code": "AA", "name": "Alpha Branch", "connections": 6}])
            if "RETURN properties(b) AS properties LIMIT 1" in statement:
                return Cursor([{"properties": {"BranchCode": "AA", "BranchName": "Alpha Branch", "PhysicalBranch": "1"}}])
            if "RETURN type(r) AS relationship_type" in statement:
                return Cursor([{
                    "relationship_type": "IN_WARD", "labels": ["LibraryWard"],
                    "properties": {"name": "Sample Ward", "ward_no": "2"},
                    "relationship_properties": {},
                }])
            if "RETURN area_properties AS" in statement or "area_properties" in statement:
                return Cursor([])
            if "RETURN properties(a) AS properties, count(DISTINCT b) AS branches" in statement:
                return Cursor([{"properties": {"name": "Sample Area", "neighbourhood_no": "12"}, "branches": 4}])
            if "RETURN count(DISTINCT b) AS count" in statement:
                return Cursor([{"count": 1}])
            if "RETURN count(n) AS count" in statement or "RETURN count(b) AS count" in statement:
                return Cursor([{"count": 1}])
            if "RETURN count(r) AS count" in statement:
                return Cursor([{"count": 6}])
            if "RETURN properties(area) AS area_properties" in statement:
                return Cursor([])
            return Cursor([])

        def close(self):
            self.closed = True

    connection = SnapshotConnection()
    monkeypatch.setattr(graph, "open_graph", lambda read_only=True: connection)
    monkeypatch.setattr(graph, "_schema", lambda _connection: (schema, [
        "IN_NEIGHBOURHOOD", "IN_WARD", "OFFERS_SERVICE", "HAS_GEOGRAPHY_RECORD"
    ]))
    monkeypatch.setattr(graph, "branch_records", lambda: [{"code": "AA", "name": "Alpha Branch"}])

    result = graph.explorer_snapshot(["AA"])

    branch_count_query = next(q for q in connection.statements if "MATCH (n:`BranchGeneralInformation`)" in q)
    assert "toString(n.`PhysicalBranch`) = '1'" in branch_count_query
    assert all(
        "toString(b.`PhysicalBranch`) = '1'" in q
        for q in connection.statements
        if "MATCH (b:`BranchGeneralInformation`)" in q
    )
    assert result["node_counts"][0]["count"] == 1
    assert result["insights"]["physical_branch_nodes"] == 1
    assert result["insights"]["connected_physical_branches"] == 1
    assert result["insights"]["physical_branch_relationships"] == 6
    assert result["selected"][0]["branch_code"] == "AA"
    assert connection.closed is True
