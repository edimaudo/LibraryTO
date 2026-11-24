from __future__ import annotations

from app.services import relate


def test_ordinal_branch_questions_parse_numeric_and_word_ordinals():
    assert relate._ordinal_branch_rank("What was the 5th branch to open?") == 5
    assert relate._ordinal_branch_rank("Which was the third branch to be opened?") == 3
    assert relate._ordinal_branch_rank("What was the 21st branch to open?") == 21
    assert relate._ordinal_branch_rank("Which branch has the most visits?") is None
    assert relate._ordinal_branch_rank("What was the 4th event at the branch?") is None


def test_ordinal_branch_answer_uses_present_site_year_and_alphabetical_ties(monkeypatch):
    schema = {
        "BranchGeneralInformation": {
            "branchcode": "BranchCode",
            "branchname": "BranchName",
            "presentsiteyear": "PresentSiteYear",
        }
    }
    branches = {
        "aa": {"code": "AA", "name": "Alpha"},
        "bb": {"code": "BB", "name": "Bravo"},
        "cc": {"code": "CC", "name": "Charlie"},
        "dd": {"code": "DD", "name": "Delta"},
    }
    rows = [
        {"BranchCode": "BB", "BranchName": "Bravo", "PresentSiteYear": "1960", "PhysicalBranch": "1"},
        {"BranchCode": "AA", "BranchName": "Alpha", "PresentSiteYear": "1950", "PhysicalBranch": "1"},
        {"BranchCode": "CC", "BranchName": "Charlie", "PresentSiteYear": "1960", "PhysicalBranch": "1"},
        {"BranchCode": "DD", "BranchName": "Delta", "PresentSiteYear": "1970", "PhysicalBranch": "1"},
    ]
    monkeypatch.setattr(relate, "_label_for_branch", lambda _schema: ("BranchGeneralInformation", schema["BranchGeneralInformation"]))
    monkeypatch.setattr(relate, "_eligible_codes", lambda: branches)
    monkeypatch.setattr(relate, "_nodes", lambda *args, **kwargs: rows)

    result = relate._answer_ordinal_branch(object(), schema, 2)

    assert result["status"] == "ok"
    assert "2nd branch in chronological order is Bravo (1960)" in result["answer"]
    assert "current site" in result["answer"]
    assert "ordered alphabetically" in result["answer"]
    assert result["highlights"][0]["details"][0]["value"] == "2nd"


def test_ordinal_branch_answer_reports_out_of_range_rank(monkeypatch):
    schema = {"BranchGeneralInformation": {"branchcode": "BranchCode", "presentsiteyear": "PresentSiteYear"}}
    monkeypatch.setattr(relate, "_label_for_branch", lambda _schema: ("BranchGeneralInformation", schema["BranchGeneralInformation"]))
    monkeypatch.setattr(relate, "_eligible_codes", lambda: {"aa": {"code": "AA", "name": "Alpha"}})
    monkeypatch.setattr(relate, "_nodes", lambda *args, **kwargs: [{"BranchCode": "AA", "BranchName": "Alpha", "PresentSiteYear": "1950", "PhysicalBranch": "1"}])

    result = relate._answer_ordinal_branch(object(), schema, 5)

    assert result["status"] == "no_match"
    assert "outside the 1 physical branches" in result["answer"]


def test_overview_ask_routes_ordinal_opening_question_to_present_site_ranking(monkeypatch):
    import app.services.graph_enhancements as graph

    class Connection:
        def close(self):
            self.closed = True

    connection = Connection()
    expected = {"status": "ok", "answer": "ordinal answer", "direct_intent": True}
    monkeypatch.setattr(relate, "branch_records", lambda: [{"code": "AA", "name": "Alpha"}])
    monkeypatch.setattr(relate, "_open_connection", lambda: connection)
    monkeypatch.setattr(relate, "_cached_schema", lambda _connection: {"BranchGeneralInformation": {}})
    monkeypatch.setattr(graph, "answer_connected_question", lambda *args: None)
    monkeypatch.setattr(relate, "_answer_ordinal_branch", lambda _connection, _schema, rank: expected if rank == 5 else None)

    result = relate.ask("What was the 5th branch to open?")

    assert result == expected
    assert connection.closed is True
