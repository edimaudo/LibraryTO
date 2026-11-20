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
