from app.services import relate as relate_service


def _fake_observations():
    return [
        {"BranchCode": "A1", "Year": 2018, "Circulation": 1800},
        {"BranchCode": "B2", "Year": 2018, "Circulation": 1300},
        {"BranchCode": "A1", "Year": 2023, "Circulation": 900},
        {"BranchCode": "B2", "Year": 2023, "Circulation": 1600},
        {"BranchCode": "A1", "Year": 2024, "Circulation": 1000},
        {"BranchCode": "B2", "Year": 2024, "Circulation": 1200},
    ]


def _patch_ranking(monkeypatch):
    monkeypatch.setattr(relate_service, "_label_for_metric", lambda schema, metric: (
        "CirculationAnnualByBranch", {"branchcode": "BranchCode", "year": "Year", "circulation": "Circulation"}
    ))
    monkeypatch.setattr(relate_service, "_nodes", lambda *args, **kwargs: _fake_observations())
    monkeypatch.setattr(relate_service, "_eligible_codes", lambda: {
        "a1": {"code": "A1", "name": "Alpha Branch"},
        "b2": {"code": "B2", "name": "Beta Branch"},
    })
    monkeypatch.setattr(relate_service, "is_physical_branch", lambda props: True)


def test_yearless_highest_annual_circulation_checks_all_available_years(monkeypatch):
    _patch_ranking(monkeypatch)
    result = relate_service._answer_metric_ranking(
        object(), {}, "circulation", None, "What branch had the highest annual circulation?"
    )
    assert "across all available reporting years" in result["answer"].lower()
    assert "Alpha Branch (1,800) in 2018" in result["answer"]
    assert "2024 annual leader" in [item["label"] for item in result["highlights"][0]["details"]]


def test_explicit_year_still_limits_annual_circulation_ranking(monkeypatch):
    _patch_ranking(monkeypatch)
    result = relate_service._answer_metric_ranking(
        object(), {}, "circulation", "2024", "What branch had the highest annual circulation in 2024?"
    )
    assert "In 2024" in result["answer"]
    assert "Beta Branch (1,200)" in result["answer"]
    assert "2018" not in result["answer"]
