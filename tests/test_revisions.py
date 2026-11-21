from __future__ import annotations

import csv
from types import SimpleNamespace

import pytest

from app.services import data_store, analytics, relate_compare
from main import _enrich_question_answer, _graph_timestamp


def _write_csv(path, headers, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


@pytest.fixture()
def snapshots(tmp_path, monkeypatch):
    monkeypatch.setattr(data_store, "DATA_DIR", tmp_path)
    _write_csv(tmp_path / "tpl-branch-general-information.csv",
               ["BranchCode", "BranchName", "PhysicalBranch", "ServiceTier", "Address", "SquareFootage", "Workstations", "Lat", "Long", "Telephone", "Website", "KidsStop", "PresentSiteYear"],
               [["P1", "Physical One", 1, "DL", "1 Main St", 10000, 20, 43.7, -79.4, "416-555-0100", "https://example.org", 1, 1990],
                ["V1", "Virtual One", 0, "NL", "Online", 5000, 2, "", "", "", "", 1, 2020]])
    metric_files = {
        "circulation": ("tpl-circulation-annual-by-branch.csv", "Circulation", 1000),
        "visits": ("tpl-visits-annual-by-branch.csv", "Visits", 800),
        "workstations": ("tpl-workstation-usage-annual-by-branch.csv", "Sessions", 300),
        "registrations": ("tpl-card-registrations-annual-by-branch.csv", "Registrations", 100),
    }
    for filename, value_field, value in metric_files.values():
        rows = [["P1", year, value + year - 2017] for year in range(2017, 2023)]
        rows.append(["V1", 2022, 999999])
        _write_csv(tmp_path / filename, ["BranchCode", "Year", value_field], rows)
    _write_csv(tmp_path / "tpl-events-feed.csv",
               ["EventID", "Title", "StartDateLocal", "StartTime", "EndTime", "LocationName", "BranchCode", "Audiences", "Languages", "EventTypes", "PhysicalBranch"],
               [["E1", "Future program", "2099-03-06", "2099-03-06T14:00:00", "2099-03-06T16:00:00", "Physical One", "P1", "Adults", "English", "Workshop", 1],
                ["E2", "Past program", "2000-03-06", "2000-03-06T14:00:00", "2000-03-06T16:00:00", "Physical One", "P1", "Adults", "English", "Workshop", 1],
                ["E3", "Invalid timestamp", "not-a-date", "not-a-time", "", "Physical One", "P1", "Adults", "English", "Workshop", 1],
                ["E4", "Virtual event", "2099-03-06", "2099-03-06T14:00:00", "2099-03-06T16:00:00", "Virtual One", "V1", "Adults", "English", "Workshop", 0]])
    data_store.refresh_data_cache()
    analytics.overview.cache_clear()
    yield tmp_path
    data_store.refresh_data_cache()
    analytics.overview.cache_clear()


def test_only_physical_branches_and_matching_metrics_are_used(snapshots):
    branches = data_store.branch_records()
    assert [branch["code"] for branch in branches] == ["P1"]
    values = data_store.observations()
    assert values
    assert {row["branch_code"] for row in values} == {"P1"}
    payload = analytics.overview()
    assert payload["branch_count"] == 1
    assert payload["totals"]["circulation"] == 1000 + 2022 - 2017


def test_iso_event_start_and_end_are_not_combined_twice(snapshots):
    records = {item["id"]: item for item in data_store.event_records()}
    assert records["E1"]["start"] == "2099-03-06 14:00"
    assert records["E1"]["end"] == "2099-03-06 16:00"
    assert data_store._parse_feed_datetime("2099-03-06T00:00:00") == "2099-03-06 00:00"
    assert "E4" not in records


def test_invalid_and_past_events_never_appear_as_upcoming(snapshots, monkeypatch):
    monkeypatch.setattr(analytics, "_today", lambda: analytics.date(2099, 1, 1))
    result = analytics.recommend_events({})
    assert [event["id"] for event in result["events"]] == ["E1"]
    assert analytics.branch_detail("P1")["events"][0]["id"] == "E1"


def test_forecast_is_exactly_one_year_after_last_observation(snapshots, monkeypatch):
    import statsmodels.tsa.arima.model

    class FakeARIMA:
        def __init__(self, values, **kwargs):
            self.aic = 1.0
        def fit(self):
            return self
        def get_forecast(self, steps):
            assert steps == 1
            return SimpleNamespace(predicted_mean=[123.0])

    monkeypatch.setattr(statsmodels.tsa.arima.model, "ARIMA", FakeARIMA)
    result = analytics.branch_forecasts("P1")
    forecast = result["circulation"]["forecasts"]
    assert forecast == [{"year": 2023, "value": 123.0}]


def test_comparison_selection_is_capped_at_five(snapshots, monkeypatch):
    monkeypatch.setattr(relate_compare, "RELATE_FILE", snapshots / "missing-graph.rl")
    data = analytics.compare(["P1", "P1", "V1", "X1", "X2", "X3", "X4"])
    assert len(data["branches"]) == 1
    assert data["branches"][0]["code"] == "P1"


def test_graph_question_summaries_use_readable_start_and_end_times():
    assert _graph_timestamp("2026-03-06T14:00:00") == "2026-03-06 14:00"
    assert _graph_timestamp("16:00:00", "2026-03-06") == "2026-03-06 16:00"
    answer = {
        "highlights": [{"title": "Tea & Entertainment", "category": "Program", "details": []}],
        "evidence": [{"labels": ["EventsFeed"], "properties": {
            "Title": "Tea & Entertainment", "StartDateLocal": "2026-03-06",
            "StartTime": "2026-03-06T14:00:00", "EndTime": "2026-03-06T16:00:00"
        }}]
    }
    result = _enrich_question_answer(answer)
    assert "evidence" not in result
    assert result["highlights"][0]["details"] == [
        {"label": "Starts", "value": "2026-03-06 14:00"},
        {"label": "Ends", "value": "2026-03-06 16:00"}
    ]


def test_event_finder_caps_displayed_programs_at_ten(snapshots, monkeypatch):
    future_events = []
    for index in range(15):
        future_events.append({
            "id": f"F{index}", "title": f"Future program {index}",
            "start": f"2099-04-{index + 1:02d} 10:00", "end": f"2099-04-{index + 1:02d} 11:00",
            "location": "Physical One", "branch_code": "P1", "audiences": "Adults",
            "languages": "English", "types": "Workshop", "description": "A future program",
            "registration_url": "", "event_url": "", "full": False, "closed": False,
            "registration_open": False, "recurring": False,
        })
    monkeypatch.setattr(analytics, "event_records", lambda: future_events)
    monkeypatch.setattr(analytics, "_today", lambda: analytics.date(2099, 1, 1))
    analytics._recommend_events_cached.cache_clear()
    result = analytics.recommend_events({})
    assert len(result["events"]) == 10
    assert result["total"] == 10
    assert result["analysis"]["total_upcoming"] == 10
    analytics._recommend_events_cached.cache_clear()


def test_comparison_supplements_missing_relate_metrics_with_csv(snapshots, monkeypatch):
    from app.services import relate_compare
    physical = data_store.branch_records()[0]
    graph = {
        "branches": [physical],
        "metric_labels": analytics.METRICS,
        "metrics": {
            "circulation": [{"year": "2022", "values": {physical["code"]: 777}}],
            "visits": [], "workstations": [], "registrations": [],
        },
    }
    monkeypatch.setattr(relate_compare, "compare_from_relate", lambda codes: graph)
    analytics._compare_cached.cache_clear()
    result = analytics.compare([physical["code"]])
    circulation_2022 = next(row for row in result["metrics"]["circulation"] if row["year"] == "2022")
    assert circulation_2022["values"][physical["code"]] == 777
    for metric in ("visits", "workstations", "registrations"):
        assert result["metrics"][metric]
        assert result["metrics"][metric][0]["values"][physical["code"]] is not None
    analytics._compare_cached.cache_clear()


def test_branch_question_scope_rejects_other_branch_evidence(snapshots):
    from main import _scope_question_answer
    answer = {
        "answer": "Two branch matches",
        "highlights": [
            {"title": "Physical One", "category": "Branch", "details": []},
            {"title": "Virtual One", "category": "Branch", "details": []},
        ],
        "evidence": [
            {"labels": ["BranchGeneralInformation"], "properties": {"BranchCode": "P1", "BranchName": "Physical One"}, "connections": []},
            {"labels": ["BranchGeneralInformation"], "properties": {"BranchCode": "V1", "BranchName": "Virtual One"}, "connections": []},
        ],
    }
    scoped = _scope_question_answer(answer, "P1")
    assert len(scoped["evidence"]) == 1
    assert scoped["evidence"][0]["properties"]["BranchCode"] == "P1"
    assert [item["title"] for item in scoped["highlights"]] == ["Physical One"]


def test_program_finder_reads_relate_event_nodes(snapshots, monkeypatch):
    import sys
    from app.services import relate_events

    graph_path = snapshots / "library.rl"
    graph_path.write_bytes(b"graph-placeholder")
    monkeypatch.setattr(relate_events, "RELATE_FILE", graph_path)

    properties = {
        "Title": "Tea and Entertainment",
        "EventID": "REL-1",
        "StartDateLocal": "2099-03-06",
        "StartTime": "2099-03-06T14:00:00",
        "EndTime": "2099-03-06T16:00:00",
        "LocationName": "Physical One",
        "BranchCode": "P1",
        "Audiences": "Adults",
        "Languages": "English",
        "EventTypes": "Culture",
        "PhysicalBranch": 1,
    }

    class Cursor:
        def __init__(self, rows):
            self.rows = rows
        def fetchall(self):
            return self.rows

    class Connection:
        def execute(self, statement, params=None):
            if "db.schema.nodeTypeProperties" in statement:
                return Cursor([
                    {"nodeLabels": ["EventsFeed"], "propertyName": key}
                    for key in properties
                ])
            if "MATCH (n:`EventsFeed`)" in statement:
                return Cursor([{"properties": properties}])
            raise AssertionError(f"Unexpected graph query: {statement}")
        def close(self):
            pass

    class RelateModule:
        @staticmethod
        def connect(database, read_only=True):
            assert read_only is True
            return Connection()

    monkeypatch.setitem(sys.modules, "relate", RelateModule)
    relate_events._graph_records.cache_clear()
    result = relate_events.recommend_from_relate({}, limit=10)
    relate_events._graph_records.cache_clear()
    assert result is not None
    assert result["data_source"] == "Relate graph"
    assert result["total"] == 1
    assert result["events"][0]["start"] == "2099-03-06 14:00"
    assert result["events"][0]["end"] == "2099-03-06 16:00"


def _mock_relate_for_questions(monkeypatch, graph_path, nodes_by_label, query_log):
    import sys
    from app.services import relate as relate_service

    graph_path.write_bytes(b"read-only graph placeholder")
    monkeypatch.setattr(relate_service, "RELATE_FILE", graph_path)
    labels = list(nodes_by_label)
    schema_rows = []
    for label, rows in nodes_by_label.items():
        if rows:
            schema_rows.extend({"nodeLabels": [label], "propertyName": key} for key in rows[0])

    class Cursor:
        def __init__(self, rows):
            self.rows = rows
        def fetchall(self):
            return self.rows

    class Connection:
        def execute(self, statement, params=None):
            params = params or {}
            query_log.append((statement, dict(params)))
            if "CALL db.labels()" in statement:
                return Cursor([{"label": label} for label in labels])
            if "CALL db.schema.nodeTypeProperties()" in statement:
                return Cursor(schema_rows)
            for label, rows in nodes_by_label.items():
                if f"MATCH (n:`{label}`)" not in statement:
                    continue
                selected = rows
                if "branch_code" in params:
                    selected = [row for row in selected if str(row.get("BranchCode", "")).casefold() == params["branch_code"]]
                if "year" in params:
                    selected = [row for row in selected if str(row.get("Year", "")) == params["year"]]
                return Cursor([{"properties": row} for row in selected[:1000]])
            raise AssertionError(f"Unexpected Relate query: {statement}")
        def close(self):
            pass

    class RelateModule:
        @staticmethod
        def connect(database, read_only=True):
            assert read_only is True
            assert str(database) == str(graph_path)
            return Connection()

    monkeypatch.setitem(sys.modules, "relate", RelateModule)
    return relate_service


def test_relate_workstation_question_uses_selected_branch_and_year(snapshots, monkeypatch):
    from app.services import relate as relate_service
    graph = {
        "BranchGeneralInformation": [
            {"BranchCode": "P1", "BranchName": "Physical One", "PhysicalBranch": 1, "PresentSiteYear": 1990},
        ],
        "WorkstationUsageAnnualByBranch": [
            {"BranchCode": "P1", "Year": 2014, "Sessions": 834, "PhysicalBranch": 1},
            {"BranchCode": "V1", "Year": 2014, "Sessions": 999999, "PhysicalBranch": 0},
        ],
    }
    calls = []
    relate_service = _mock_relate_for_questions(monkeypatch, snapshots / "tpl_library_graph.rl", graph, calls)
    result = relate_service.ask("What was the workstation usage in 2014?", "P1")
    assert result["status"] == "ok", result
    assert result["answer"] == "In 2014, Physical One recorded 834 workstation sessions."
    assert result["highlights"][0]["details"][-1] == {"label": "Reported total", "value": "834"}
    assert result["scope_verified"] is True
    metric_query = next((statement, params) for statement, params in calls if "WorkstationUsageAnnualByBranch" in statement)
    assert "n.`BranchCode`" in metric_query[0]
    assert metric_query[1] == {"branch_code": "p1", "year": "2014"}
    assert all("999999" not in str(item) for item in result["highlights"])


def test_relate_network_metric_question_sums_physical_branches_only(snapshots, monkeypatch):
    from app.services import relate as relate_service
    graph = {
        "BranchGeneralInformation": [
            {"BranchCode": "P1", "BranchName": "Physical One", "PhysicalBranch": 1, "PresentSiteYear": 1990},
        ],
        "WorkstationUsageAnnualByBranch": [
            {"BranchCode": "P1", "Year": 2014, "Sessions": 834, "PhysicalBranch": 1},
            {"BranchCode": "V1", "Year": 2014, "Sessions": 999999, "PhysicalBranch": 0},
        ],
    }
    calls = []
    relate_service = _mock_relate_for_questions(monkeypatch, snapshots / "tpl_library_graph.rl", graph, calls)
    result = relate_service.ask("What was the workstation usage in 2014?")
    assert result["status"] == "ok", result
    assert result["answer"] == "In 2014, Toronto Public Library recorded 834 workstation sessions across 1 physical branch."
    metric_query = next((statement, params) for statement, params in calls if "WorkstationUsageAnnualByBranch" in statement)
    assert "branch_code" not in metric_query[1]
    assert metric_query[1] == {"year": "2014"}


def test_relate_first_opened_question_uses_present_site_year_not_branch_name(snapshots, monkeypatch):
    from app.services import relate as relate_service
    graph = {
        "BranchGeneralInformation": [
            {"BranchCode": "P1", "BranchName": "Physical One", "PhysicalBranch": 1, "PresentSiteYear": 1990},
        ],
    }
    calls = []
    relate_service = _mock_relate_for_questions(monkeypatch, snapshots / "tpl_library_graph.rl", graph, calls)
    result = relate_service.ask("When was the branch first opened?", "P1")
    assert result["status"] == "ok", result
    assert "1990 as the present-site year" in result["answer"]
    assert "does not state when the branch first opened" in result["answer"]
    assert result["highlights"][0]["details"] == [{"label": "Present site year", "value": "1990"}]
    assert all("MATCH (n:`BranchGeneralInformation`)" in statement for statement, _ in calls if "MATCH" in statement)


def test_ask_route_preserves_direct_answer_details(snapshots, monkeypatch):
    import main
    expected = {
        "status": "ok", "answer": "In 2014, Physical One recorded 834 workstation sessions.",
        "highlights": [{"title": "Annual Workstation Usage", "category": "Annual measure", "details": [
            {"label": "Branch", "value": "Physical One"}, {"label": "Reporting year", "value": "2014"},
            {"label": "Reported total", "value": "834"},
        ]}],
        "evidence": [], "direct_intent": True, "scope_verified": True,
    }
    monkeypatch.setattr(main, "relate_ask", lambda question, branch_code: expected)
    result = main.branch_question(main.AskRequest(question="What was workstation usage in 2014?", branch_code="P1"))
    assert result["answer"] == expected["answer"]
    assert result["highlights"] == expected["highlights"]


def test_opening_year_intent_does_not_match_open_now_question(snapshots, monkeypatch):
    from app.services import relate as relate_service
    graph = {
        "BranchGeneralInformation": [
            {"BranchCode": "P1", "BranchName": "Physical One", "PhysicalBranch": 1, "PresentSiteYear": 1990},
        ],
    }
    calls = []
    relate_service = _mock_relate_for_questions(monkeypatch, snapshots / "tpl_library_graph.rl", graph, calls)
    result = relate_service.ask("Is this branch open today?", "P1")
    assert result["status"] == "no_match"
    assert result["highlights"] == []
    assert not any("MATCH (n:`BranchGeneralInformation`)" in statement for statement, _ in calls)


def test_overview_oldest_branch_question_compares_all_physical_branches(snapshots, monkeypatch):
    from app.services import relate as relate_service

    graph = {
        "BranchGeneralInformation": [
            {"BranchCode": "P1", "BranchName": "Physical One", "PhysicalBranch": 1, "PresentSiteYear": 1900},
            {"BranchCode": "P2", "BranchName": "Physical Two", "PhysicalBranch": 1, "PresentSiteYear": 1888},
            {"BranchCode": "V1", "BranchName": "Virtual One", "PhysicalBranch": 0, "PresentSiteYear": 1700},
        ],
    }
    monkeypatch.setattr(relate_service, "branch_records", lambda: [
        {"code": "P1", "name": "Physical One"},
        {"code": "P2", "name": "Physical Two"},
    ])
    calls = []
    service = _mock_relate_for_questions(monkeypatch, snapshots / "tpl_library_graph.rl", graph, calls)

    result = service.ask("What was the oldest branch?")

    assert result["status"] == "ok"
    assert "1888" in result["answer"]
    assert "Physical Two" in result["answer"]
    assert "present-site year" in result["answer"]
    assert "Virtual One" not in result["answer"]
    assert result["network_scope"] is True
    graph_query = next(statement for statement, _ in calls if "MATCH (n:`BranchGeneralInformation`)" in statement)
    assert "branch_code" not in graph_query


def test_selected_branch_question_accepts_created_as_present_site_year_intent(snapshots, monkeypatch):
    from app.services import relate as relate_service

    graph = {
        "BranchGeneralInformation": [
            {"BranchCode": "P1", "BranchName": "Physical One", "PhysicalBranch": 1, "PresentSiteYear": 1990},
        ],
    }
    calls = []
    service = _mock_relate_for_questions(monkeypatch, snapshots / "tpl_library_graph.rl", graph, calls)

    result = service.ask("When was the branch created?", "P1")

    assert result["status"] == "ok"
    assert "1990 as the present-site year" in result["answer"]
    assert "does not state when the branch first opened" in result["answer"]
    query = next((statement, params) for statement, params in calls if "MATCH (n:`BranchGeneralInformation`)" in statement)
    assert query[1] == {"branch_code": "p1"}


def test_overview_qna_can_rank_all_physical_branches_by_any_directory_field(snapshots, monkeypatch):
    from app.services import relate as relate_service

    graph = {
        "BranchGeneralInformation": [
            {"BranchCode": "P1", "BranchName": "Physical One", "PhysicalBranch": 1, "PublicParking": 14, "PublicWashroom": 1, "Hours": "Mon 9 a.m. to 5 p.m."},
            {"BranchCode": "P2", "BranchName": "Physical Two", "PhysicalBranch": 1, "PublicParking": 82, "PublicWashroom": 0, "Hours": "Tue 10 a.m. to 6 p.m."},
            {"BranchCode": "V1", "BranchName": "Virtual One", "PhysicalBranch": 0, "PublicParking": 900, "PublicWashroom": 1, "Hours": "Online"},
        ],
    }
    monkeypatch.setattr(relate_service, "branch_records", lambda: [
        {"code": "P1", "name": "Physical One"},
        {"code": "P2", "name": "Physical Two"},
    ])
    calls = []
    service = _mock_relate_for_questions(monkeypatch, snapshots / "tpl_library_graph.rl", graph, calls)

    result = service.ask("Which branch has the most public parking?")

    assert result["status"] == "ok"
    assert "Physical Two" in result["answer"]
    assert "82 spaces" in result["answer"]
    assert "Virtual One" not in result["answer"]
    assert result["network_scope"] is True
    query = next((statement, params) for statement, params in calls if "MATCH (n:`BranchGeneralInformation`)" in statement)
    assert "branch_code" not in query[1]


def test_overview_qna_lists_all_physical_branches_with_a_washroom(snapshots, monkeypatch):
    from app.services import relate as relate_service

    graph = {
        "BranchGeneralInformation": [
            {"BranchCode": "P1", "BranchName": "Physical One", "PhysicalBranch": 1, "PublicWashroom": 1},
            {"BranchCode": "P2", "BranchName": "Physical Two", "PhysicalBranch": 1, "PublicWashroom": 0},
            {"BranchCode": "V1", "BranchName": "Virtual One", "PhysicalBranch": 0, "PublicWashroom": 1},
        ],
    }
    monkeypatch.setattr(relate_service, "branch_records", lambda: [
        {"code": "P1", "name": "Physical One"},
        {"code": "P2", "name": "Physical Two"},
    ])
    service = _mock_relate_for_questions(monkeypatch, snapshots / "tpl_library_graph.rl", graph, [])

    result = service.ask("Which branches have a public washroom?")

    assert result["status"] == "ok"
    assert "Physical One" in result["answer"]
    assert "Physical Two" not in result["answer"]
    assert "Virtual One" not in result["answer"]


def test_branch_qna_returns_posted_hours_for_named_branch(snapshots, monkeypatch):
    from app.services import relate as relate_service

    graph = {
        "BranchGeneralInformation": [
            {"BranchCode": "P1", "BranchName": "Physical One", "PhysicalBranch": 1, "Hours": "Mon 9 a.m. to 8:30 p.m.; Sat 9 a.m. to 5 p.m."},
            {"BranchCode": "V1", "BranchName": "Virtual One", "PhysicalBranch": 0, "Hours": "Online"},
        ],
    }
    service = _mock_relate_for_questions(monkeypatch, snapshots / "tpl_library_graph.rl", graph, [])

    result = service.ask("What are the opening hours for Physical One?")

    assert result["status"] == "ok"
    assert "Mon 9 a.m. to 8:30 p.m." in result["answer"]
    assert result["highlights"][0]["title"] == "Physical One"


def test_branch_qna_is_locked_to_selected_branch_even_if_question_names_another(snapshots, monkeypatch):
    from app.services import relate as relate_service

    graph = {
        "BranchGeneralInformation": [
            {"BranchCode": "P1", "BranchName": "Physical One", "PhysicalBranch": 1, "Hours": "Monday 9 to 5"},
            {"BranchCode": "P2", "BranchName": "Physical Two", "PhysicalBranch": 1, "Hours": "Tuesday 10 to 6"},
        ],
    }
    monkeypatch.setattr(relate_service, "branch_records", lambda: [
        {"code": "P1", "name": "Physical One"},
        {"code": "P2", "name": "Physical Two"},
    ])
    calls = []
    service = _mock_relate_for_questions(monkeypatch, snapshots / "tpl_library_graph.rl", graph, calls)

    result = service.ask("What are the hours for Physical Two?", "P1")

    assert result["status"] == "ok"
    assert "Monday 9 to 5" in result["answer"]
    assert "Tuesday 10 to 6" not in result["answer"]
    query = next((statement, params) for statement, params in calls if "MATCH (n:`BranchGeneralInformation`)" in statement)
    assert query[1] == {"branch_code": "p1"}


def test_selected_branch_qna_answers_workstation_count_not_annual_sessions(snapshots, monkeypatch):
    from app.services import relate as relate_service

    graph = {
        "BranchGeneralInformation": [
            {"BranchCode": "P1", "BranchName": "Physical One", "PhysicalBranch": 1, "Workstations": 24},
            {"BranchCode": "P2", "BranchName": "Physical Two", "PhysicalBranch": 1, "Workstations": 90},
        ],
        "WorkstationUsageAnnualByBranch": [
            {"BranchCode": "P1", "Year": 2022, "Sessions": 300, "PhysicalBranch": 1},
            {"BranchCode": "P2", "Year": 2022, "Sessions": 900, "PhysicalBranch": 1},
        ],
    }
    monkeypatch.setattr(relate_service, "branch_records", lambda: [
        {"code": "P1", "name": "Physical One"},
        {"code": "P2", "name": "Physical Two"},
    ])
    service = _mock_relate_for_questions(monkeypatch, snapshots / "tpl_library_graph.rl", graph, [])

    result = service.ask("How many workstations does this branch have?", "P1")

    assert result["status"] == "ok"
    assert "24" in result["answer"]
    assert "900" not in result["answer"]


def test_branch_metric_question_uses_latest_available_year_when_omitted(snapshots, monkeypatch):
    from app.services import relate as relate_service

    graph = {
        "BranchGeneralInformation": [
            {"BranchCode": "P1", "BranchName": "Physical One", "PhysicalBranch": 1},
        ],
        "CirculationAnnualByBranch": [
            {"BranchCode": "P1", "Year": 2022, "Circulation": 1200, "PhysicalBranch": 1},
            {"BranchCode": "P1", "Year": 2023, "Circulation": 1350, "PhysicalBranch": 1},
        ],
    }
    service = _mock_relate_for_questions(monkeypatch, snapshots / "tpl_library_graph.rl", graph, [])

    result = service.ask("What is the circulation for this branch?", "P1")

    assert result["status"] == "ok"
    assert "In 2023" in result["answer"]
    assert "1,350" in result["answer"]


def test_overview_metric_ranking_uses_latest_common_reporting_year(snapshots, monkeypatch):
    from app.services import relate as relate_service

    graph = {
        "BranchGeneralInformation": [
            {"BranchCode": "P1", "BranchName": "Physical One", "PhysicalBranch": 1},
            {"BranchCode": "P2", "BranchName": "Physical Two", "PhysicalBranch": 1},
        ],
        "CirculationAnnualByBranch": [
            {"BranchCode": "P1", "Year": 2022, "Circulation": 2000, "PhysicalBranch": 1},
            {"BranchCode": "P2", "Year": 2022, "Circulation": 2100, "PhysicalBranch": 1},
            {"BranchCode": "P1", "Year": 2023, "Circulation": 2300, "PhysicalBranch": 1},
            {"BranchCode": "P2", "Year": 2023, "Circulation": 2200, "PhysicalBranch": 1},
        ],
    }
    monkeypatch.setattr(relate_service, "branch_records", lambda: [
        {"code": "P1", "name": "Physical One"},
        {"code": "P2", "name": "Physical Two"},
    ])
    service = _mock_relate_for_questions(monkeypatch, snapshots / "tpl_library_graph.rl", graph, [])

    result = service.ask("Which branch had the most circulation?")

    assert result["status"] == "ok"
    assert "In 2023" in result["answer"]
    assert "Physical One" in result["answer"]
    assert "2,300" in result["answer"]


def test_branch_qna_does_not_answer_live_open_status_from_posted_hours(snapshots, monkeypatch):
    from app.services import relate as relate_service

    graph = {
        "BranchGeneralInformation": [
            {"BranchCode": "P1", "BranchName": "Physical One", "PhysicalBranch": 1, "Hours": "Mon 9 a.m. to 5 p.m."},
        ],
    }
    calls = []
    service = _mock_relate_for_questions(monkeypatch, snapshots / "tpl_library_graph.rl", graph, calls)

    result = service.ask("Is this branch open today?", "P1")

    assert result["status"] == "no_match"
    assert "does not provide live opening status" in result["answer"]
    assert not any("MATCH (n:`BranchGeneralInformation`)" in statement for statement, _ in calls)


def test_overview_qna_resolves_branch_by_code_and_answers_directory_fields(snapshots, monkeypatch):
    from app.services import relate as relate_service

    graph = {
        "BranchGeneralInformation": [
            {"BranchCode": "P1", "BranchName": "Physical One", "PhysicalBranch": 1, "Telephone": "416-555-0101"},
            {"BranchCode": "P2", "BranchName": "Physical Two", "PhysicalBranch": 1, "Telephone": "416-555-0102"},
            {"BranchCode": "V1", "BranchName": "Virtual One", "PhysicalBranch": 0, "Telephone": "416-555-0199"},
        ],
    }
    monkeypatch.setattr(relate_service, "branch_records", lambda: [
        {"code": "P1", "name": "Physical One"},
        {"code": "P2", "name": "Physical Two"},
    ])
    calls = []
    service = _mock_relate_for_questions(monkeypatch, snapshots / "tpl_library_graph.rl", graph, calls)

    result = service.ask("What is the phone number for branch P2?")

    assert result["status"] == "ok"
    assert "416-555-0102" in result["answer"]
    assert result["highlights"][0]["title"] == "Physical Two"
    query = next((statement, params) for statement, params in calls if "MATCH (n:`BranchGeneralInformation`)" in statement)
    assert query[1] == {"branch_code": "p2"}


def test_overview_qna_recognizes_new_boolean_directory_attributes(snapshots, monkeypatch):
    from app.services import relate as relate_service

    graph = {
        "BranchGeneralInformation": [
            {"BranchCode": "P1", "BranchName": "Physical One", "PhysicalBranch": 1, "AccessibleEntrance": "Yes"},
            {"BranchCode": "P2", "BranchName": "Physical Two", "PhysicalBranch": 1, "AccessibleEntrance": "No"},
            {"BranchCode": "V1", "BranchName": "Virtual One", "PhysicalBranch": 0, "AccessibleEntrance": "Yes"},
        ],
    }
    monkeypatch.setattr(relate_service, "branch_records", lambda: [
        {"code": "P1", "name": "Physical One"},
        {"code": "P2", "name": "Physical Two"},
    ])
    calls = []
    service = _mock_relate_for_questions(monkeypatch, snapshots / "tpl_library_graph.rl", graph, calls)

    result = service.ask("Which physical branches have an accessible entrance?")

    assert result["status"] == "ok"
    assert "Physical One" in result["answer"]
    assert "Physical Two" not in result["answer"]
    assert "Virtual One" not in result["answer"]
    query = next((statement, params) for statement, params in calls if "MATCH (n:`BranchGeneralInformation`)" in statement)
    assert "branch_code" not in query[1]


def test_branch_qna_unknown_wording_returns_selected_branch_profile_not_network(snapshots, monkeypatch):
    from app.services import relate as relate_service

    graph = {
        "BranchGeneralInformation": [
            {"BranchCode": "P1", "BranchName": "Physical One", "PhysicalBranch": 1, "Address": "1 Main St", "Telephone": "416-555-0101", "WardName": "Ward A"},
            {"BranchCode": "P2", "BranchName": "Physical Two", "PhysicalBranch": 1, "Address": "2 Main St", "Telephone": "416-555-0102", "WardName": "Ward B"},
        ],
    }
    monkeypatch.setattr(relate_service, "branch_records", lambda: [
        {"code": "P1", "name": "Physical One"},
        {"code": "P2", "name": "Physical Two"},
    ])
    calls = []
    service = _mock_relate_for_questions(monkeypatch, snapshots / "tpl_library_graph.rl", graph, calls)

    result = service.ask("Can you give me an overview of this branch?", "P1")

    assert result["status"] == "ok"
    assert "Physical One" in result["answer"]
    assert "1 Main St" in result["answer"]
    assert "Physical Two" not in result["answer"]
    query = next((statement, params) for statement, params in calls if "MATCH (n:`BranchGeneralInformation`)" in statement)
    assert query[1] == {"branch_code": "p1"}


def test_branch_qna_program_questions_are_restricted_to_selected_branch(snapshots, monkeypatch):
    from app.services import relate as relate_service
    from app.services import relate_events

    monkeypatch.setattr(relate_service, "branch_records", lambda: [
        {"code": "P1", "name": "Physical One"},
        {"code": "P2", "name": "Physical Two"},
    ])
    monkeypatch.setattr(relate_events, "graph_event_records", lambda: [
        {"title": "Storytime", "start": "2099-03-06 10:00", "branch_code": "P1", "types": "Storytime", "audiences": "Children", "languages": "English", "description": "Reading for children"},
        {"title": "Computer Workshop", "start": "2099-03-06 11:00", "branch_code": "P2", "types": "Workshop", "audiences": "Adults", "languages": "English", "description": "Computer basics"},
    ])
    graph = {"BranchGeneralInformation": [
        {"BranchCode": "P1", "BranchName": "Physical One", "PhysicalBranch": 1},
        {"BranchCode": "P2", "BranchName": "Physical Two", "PhysicalBranch": 1},
    ]}
    _mock_relate_for_questions(monkeypatch, snapshots / "tpl_library_graph.rl", graph, [])

    result = relate_service.ask("What programs are available at this branch?", "P1")

    assert result["status"] == "ok"
    assert "Storytime" in result["answer"]
    assert "Computer Workshop" not in result["answer"]
    assert result["highlights"][0]["category"] == "Physical One"


def test_overview_qna_counts_branches_in_numeric_ward_without_adding_ward_numbers(snapshots, monkeypatch):
    from app.services import relate as relate_service

    graph = {
        "BranchGeneralInformation": [
            {"BranchCode": "P1", "BranchName": "Physical One", "PhysicalBranch": 1, "WardNo": 20},
            {"BranchCode": "P2", "BranchName": "Physical Two", "PhysicalBranch": 1, "WardNo": 20},
            {"BranchCode": "P3", "BranchName": "Physical Three", "PhysicalBranch": 1, "WardNo": 19},
            {"BranchCode": "V1", "BranchName": "Virtual One", "PhysicalBranch": 0, "WardNo": 20},
        ],
    }
    monkeypatch.setattr(relate_service, "branch_records", lambda: [
        {"code": "P1", "name": "Physical One"},
        {"code": "P2", "name": "Physical Two"},
        {"code": "P3", "name": "Physical Three"},
    ])
    service = _mock_relate_for_questions(monkeypatch, snapshots / "tpl_library_graph.rl", graph, [])

    result = service.ask("How many branches are in Ward 20?")

    assert result["status"] == "ok"
    assert "2 physical branches" in result["answer"]
    assert "40" not in result["answer"]
    assert "Virtual One" not in result["answer"]


def test_branch_qna_answers_day_specific_posted_hours(snapshots, monkeypatch):
    from app.services import relate as relate_service

    graph = {
        "BranchGeneralInformation": [
            {"BranchCode": "P1", "BranchName": "Physical One", "PhysicalBranch": 1, "Hours": "Mon 9 a.m. to 8 p.m.; Sat 9 a.m. to 5 p.m.; Sun 12 p.m. to 5 p.m."},
            {"BranchCode": "P2", "BranchName": "Physical Two", "PhysicalBranch": 1, "Hours": "Mon 10 a.m. to 6 p.m.; Sat 10 a.m. to 4 p.m."},
        ],
    }
    monkeypatch.setattr(relate_service, "branch_records", lambda: [
        {"code": "P1", "name": "Physical One"},
        {"code": "P2", "name": "Physical Two"},
    ])
    service = _mock_relate_for_questions(monkeypatch, snapshots / "tpl_library_graph.rl", graph, [])

    result = service.ask("Is this branch open on Sunday?", "P1")

    assert result["status"] == "ok"
    assert "Sun 12 p.m. to 5 p.m." in result["answer"]
    assert "Physical Two" not in result["answer"]


def test_overview_qna_lists_branches_with_posted_hours_for_requested_day(snapshots, monkeypatch):
    from app.services import relate as relate_service

    graph = {
        "BranchGeneralInformation": [
            {"BranchCode": "P1", "BranchName": "Physical One", "PhysicalBranch": 1, "Hours": "Mon 9 a.m. to 8 p.m.; Sun 12 p.m. to 5 p.m."},
            {"BranchCode": "P2", "BranchName": "Physical Two", "PhysicalBranch": 1, "Hours": "Mon 10 a.m. to 6 p.m.; Sat 10 a.m. to 4 p.m."},
            {"BranchCode": "V1", "BranchName": "Virtual One", "PhysicalBranch": 0, "Hours": "Sun 24 hours"},
        ],
    }
    monkeypatch.setattr(relate_service, "branch_records", lambda: [
        {"code": "P1", "name": "Physical One"},
        {"code": "P2", "name": "Physical Two"},
    ])
    service = _mock_relate_for_questions(monkeypatch, snapshots / "tpl_library_graph.rl", graph, [])

    result = service.ask("Which branches have posted hours on Sunday?")

    assert result["status"] == "ok"
    assert "Physical One" in result["answer"]
    assert "Physical Two" not in result["answer"]
    assert "Virtual One" not in result["answer"]


def test_overview_qna_filters_branch_count_by_human_readable_service_tier(snapshots, monkeypatch):
    from app.services import relate as relate_service

    graph = {
        "BranchGeneralInformation": [
            {"BranchCode": "P1", "BranchName": "Physical One", "PhysicalBranch": 1, "Service Tier": "DL"},
            {"BranchCode": "P2", "BranchName": "Physical Two", "PhysicalBranch": 1, "Service Tier": "NL"},
            {"BranchCode": "P3", "BranchName": "Physical Three", "PhysicalBranch": 1, "Service Tier": "DL"},
            {"BranchCode": "V1", "BranchName": "Virtual One", "PhysicalBranch": 0, "Service Tier": "DL"},
        ],
    }
    monkeypatch.setattr(relate_service, "branch_records", lambda: [
        {"code": "P1", "name": "Physical One"},
        {"code": "P2", "name": "Physical Two"},
        {"code": "P3", "name": "Physical Three"},
    ])
    service = _mock_relate_for_questions(monkeypatch, snapshots / "tpl_library_graph.rl", graph, [])

    result = service.ask("How many branches are District Libraries?")

    assert result["status"] == "ok"
    assert "2 physical branches" in result["answer"]
    assert "Physical Two" not in result["answer"]
    assert "Virtual One" not in result["answer"]


def test_overview_prompt_and_pearson_correlation_copy_are_clean():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    js = (root / "static/js/app.js").read_text(encoding="utf-8")
    assert "Ask across physical branches or name one" not in js
    assert "chart('Correlation'" in js
    assert "colorbar:{title:'Pearson correlation'}" in js
    assert "Pearson correlation: %{z:.2f}" in js
    assert "<h2>Pearson correlation</h2>" in js
    assert "Understanding r." not in js
    assert "r is Pearson's correlation coefficient" not in js
    assert "It describes the direction and strength of a linear relationship between two measures." in js


def test_branch_insights_has_loading_spinner_for_initial_data_and_chart_rendering():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    js = (root / "static/js/app.js").read_text(encoding="utf-8")
    css = (root / "static/css/app.css").read_text(encoding="utf-8")
    template = (root / "templates/index.html").read_text(encoding="utf-8")
    assert "Loading branch directory…" in template
    assert "Loading branch information…" in js
    assert "Preparing branch insights…" in js
    assert "aria-busy','true'" in js
    assert ".loading-spinner" in css
    assert ".profile-loading-overlay" in css
