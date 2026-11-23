from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_overview_removes_pearson_and_uses_an_annual_metric_main_tab():
    source = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    overview_start = source.index("async function renderOverview() {")
    overview_end = source.index("function branchPicker(", overview_start)
    overview = source[overview_start:overview_end]
    assert "Pearson correlation" not in overview
    assert "${correlation}" not in overview
    assert "Annual metric" in overview
    assert "Top 10 branches" not in overview  # Rankings render within metric panels below.


def test_each_annual_metric_panel_has_top_bottom_and_area_chart():
    source = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    assert "function rankingMetricPanel(data,metric,index)" in source
    assert "role=\"tabpanel\" aria-labelledby=\"annual-metric-tab-${index}\"" in source
    assert "Top 10 branches" in source
    assert "Bottom 10 branches" in source
    assert "Annual activity and branch area" in source
    assert "branchActivitySizeChart(data,metric,selectedYear)" in source


def test_activity_intensity_is_inserted_in_all_three_sections():
    source = (ROOT / "static/js/graph-enhancements.js").read_text(encoding="utf-8")
    assert "Activity Intensity" in source
    assert "#overview-panel-2 .ranking-metric-panel:not([hidden])" in source
    assert "#branch-panel-1" in source
    assert "#comparison-main-panel-0 > .tab-panel:not([hidden])" in source
    assert source.count("installIntensity(") >= 4


def test_activity_intensity_tables_have_accessible_headers_and_captions():
    source = (ROOT / "static/js/graph-enhancements.js").read_text(encoding="utf-8")
    assert '<caption class="visually-hidden">' in source
    assert 'scope="col"' in source
    assert 'scope="row"' in source
    assert 'aria-live="polite"' in source


def test_accessibility_validator_exists():
    assert (ROOT / "scripts/validate_accessibility.py").is_file()
    assert (ROOT / "ACCESSIBILITY_VALIDATION.md").is_file()
