"""Descriptive analytics for the TPL branch and event source datasets."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time
from statistics import mean
from typing import Any
from zoneinfo import ZoneInfo
import re

from app.services.data_store import branch_records, observations, event_records

TORONTO_TZ = ZoneInfo("America/Toronto")


def _today() -> date:
    return datetime.now(TORONTO_TZ).date()


METRICS = {
    "circulation": "Circulation",
    "visits": "Visits",
    "workstations": "Workstation sessions",
    "registrations": "Card registrations",
}


def _year_key(value: str) -> tuple[int, str]:
    try:
        return int(value), value
    except (TypeError, ValueError):
        return 0, str(value)


def overview() -> dict[str, Any]:
    branches = branch_records()
    all_observations = observations()
    events = event_records()
    trend_values: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    trend_coverage: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    years_by_metric: dict[str, set[str]] = defaultdict(set)
    latest_totals: dict[str, float] = {}
    latest_years: dict[str, str] = {}
    coverage: dict[str, int] = {}

    # Duplicate source rows for the same branch/metric/year are consolidated
    # once; totals never sum the same branch-year twice.
    unique: dict[tuple[str, str, str], float] = {}
    for item in all_observations:
        unique[(item["metric"], item["year"], item["branch_code"])] = item["value"]
    for (metric, year, code), value in unique.items():
        trend_values[metric][year] += value
        trend_coverage[metric][year].add(code)
        years_by_metric[metric].add(year)

    trend = {}
    for metric in METRICS:
        ordered_years = sorted(years_by_metric.get(metric, set()), key=_year_key)
        trend[metric] = [
            {
                "year": year,
                "value": round(trend_values[metric][year], 2),
                "branches_covered": len(trend_coverage[metric][year]),
            }
            for year in ordered_years
        ]
        if ordered_years:
            latest = ordered_years[-1]
            latest_years[metric] = latest
            latest_totals[metric] = round(trend_values[metric][latest], 2)
            coverage[metric] = len(trend_coverage[metric][latest])

    tiers: dict[str, int] = defaultdict(int)
    for branch in branches:
        tiers[branch["service_tier"] or "Not specified"] += 1

    return {
        "branch_count": len(branches),
        "event_count": len(events),
        "totals": latest_totals,
        "latest_years": latest_years,
        "coverage": coverage,
        "trend": trend,
        "tiers": dict(sorted(tiers.items())),
        "metrics": METRICS,
        "observation_count": len(unique),
        "event_feed_has_upcoming": any(_event_date(e) and _event_date(e) >= _today() for e in events),
    }


def branch_detail(code: str) -> dict[str, Any] | None:
    branch = next(
        (item for item in branch_records() if item["code"].casefold() == code.casefold()),
        None,
    )
    if branch is None:
        return None

    rows = [
        item for item in observations()
        if item["branch_code"].casefold() == code.casefold()
    ]
    unique = {
        (item["metric"], item["year"]): item["value"]
        for item in rows
    }
    history: dict[str, list[dict[str, Any]]] = {}
    for metric in METRICS:
        metric_rows = [
            {"year": year, "value": value}
            for (metric_key, year), value in unique.items()
            if metric_key == metric
        ]
        history[metric] = sorted(metric_rows, key=lambda item: _year_key(item["year"]))

    hosted = []
    for event in event_records():
        event_code = event.get("branch_code", "")
        location = event.get("location", "")
        code_match = bool(event_code) and event_code.casefold() == code.casefold()
        name_match = bool(branch["name"]) and branch["name"].casefold() in location.casefold()
        if code_match or name_match:
            hosted.append(event)
    hosted.sort(key=lambda item: _event_sort_key(item))

    return {"branch": branch, "history": history, "events": hosted}


def compare(codes: list[str]) -> dict[str, Any]:
    clean_codes = list(dict.fromkeys(code.strip() for code in codes if code.strip()))[:6]
    branch_lookup = {item["code"].casefold(): item for item in branch_records()}
    selected = [branch_lookup[code.casefold()] for code in clean_codes if code.casefold() in branch_lookup]
    selected_codes = {item["code"].casefold() for item in selected}

    data: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    unique: dict[tuple[str, str, str], float] = {}
    for row in observations():
        if row["branch_code"].casefold() in selected_codes:
            unique[(row["metric"], row["year"], row["branch_code"])] = row["value"]
    canonical_codes = {item["code"].casefold(): item["code"] for item in selected}
    for (metric, year, code), value in unique.items():
        canonical = canonical_codes.get(code.casefold())
        if canonical:
            data[metric][year][canonical] = value

    metrics = {}
    for metric in METRICS:
        metrics[metric] = [
            {
                "year": year,
                "values": {branch["code"]: data[metric][year].get(branch["code"]) for branch in selected},
                "coverage": sum(data[metric][year].get(branch["code"]) is not None for branch in selected),
            }
            for year in sorted(data.get(metric, {}), key=_year_key)
        ]
    return {"branches": selected, "metrics": metrics, "metric_labels": METRICS}


def _event_datetime(event: dict[str, Any]) -> datetime | None:
    raw = str(event.get("start") or "").strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    candidates = [normalized, normalized.replace(" ", "T", 1)]
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
        except ValueError:
            continue
    for pattern in ("%Y-%m-%d %H:%M", "%Y-%m-%d %I:%M %p", "%Y-%m-%d %I:%M%p", "%Y-%m-%d", "%m/%d/%Y %H:%M", "%m/%d/%Y %I:%M %p", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, pattern)
        except ValueError:
            continue
    return None


def _event_date(event: dict[str, Any]) -> date | None:
    parsed = _event_datetime(event)
    return parsed.date() if parsed else None


def _event_sort_key(event: dict[str, Any]) -> tuple[int, str]:
    parsed = _event_datetime(event)
    return (0 if parsed else 1, parsed.isoformat() if parsed else str(event.get("start", "")))


def recommend_events(preferences: dict[str, Any]) -> dict[str, Any]:
    """Rank upcoming events using only fields present in the event feed."""
    today = _today()
    start_date = _parse_date(preferences.get("start_date")) or today
    end_date = _parse_date(preferences.get("end_date"))
    time_from = _parse_time(preferences.get("time_from"))
    time_to = _parse_time(preferences.get("time_to"))

    requested = {
        "audience": str(preferences.get("audience") or "").strip().casefold(),
        "language": str(preferences.get("language") or "").strip().casefold(),
        "event_type": str(preferences.get("event_type") or "").strip().casefold(),
        "branch": str(preferences.get("branch") or "").strip().casefold(),
        "interest": str(preferences.get("interest") or "").strip().casefold(),
    }
    available_only = str(preferences.get("registration") or "").strip().casefold() in {"available", "open", "true", "1"}

    candidates = []
    for event in event_records():
        when = _event_datetime(event)
        if when is None or when.date() < start_date:
            continue
        if end_date and when.date() > end_date:
            continue
        if time_from and when.time() < time_from:
            continue
        if time_to and when.time() > time_to:
            continue

        is_unavailable = bool(event["full"] or event["closed"])
        if available_only and not event.get("registration_open"):
            continue

        score = 0
        reasons = []
        checks = (
            ("audience", event["audiences"], "Audience matches"),
            ("language", event["languages"], "Language matches"),
            ("event_type", event["types"], "Event type matches"),
            ("branch", f'{event["location"]} {event.get("branch_code", "")}', "Branch or location matches"),
        )
        for key, haystack, reason in checks:
            target = requested[key]
            if target and target in str(haystack).casefold():
                score += 2
                reasons.append(reason)
        interest = requested["interest"]
        text_blob = " ".join((event["title"], event["description"], event["types"])).casefold()
        if interest:
            terms = [term for term in re.findall(r"[\w'-]+", interest) if len(term) > 1]
            matched_terms = [term for term in terms if term in text_blob]
            if matched_terms:
                score += 3 * len(matched_terms)
                reasons.append("Interest terms: " + ", ".join(matched_terms[:4]))
        if is_unavailable:
            reasons.append("Registration is full or closed; shown as an alternative")
        if not reasons:
            reasons.append("Upcoming event within the selected date range")
        candidates.append({
            **event,
            "match_score": score,
            "match_reasons": reasons,
            "registration_status": "Full" if event["full"] else "Closed" if event["closed"] else "Registration open" if event.get("registration_open") else "Status not supplied",
            "available_for_registration": bool(event.get("registration_open")),
            "start_iso": when.isoformat(),
        })

    candidates.sort(key=lambda item: (-item["match_score"], item["start_iso"], item["title"].casefold()))
    return {
        "events": candidates[:100],
        "total": len(candidates),
        "date_range": {"start": start_date.isoformat(), "end": end_date.isoformat() if end_date else None},
        "available_only": available_only,
    }


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _parse_time(value: Any) -> time | None:
    if not value:
        return None
    try:
        return time.fromisoformat(str(value))
    except ValueError:
        return None


def branch_forecasts(code: str, horizon: int = 3) -> dict[str, Any] | None:
    """Create a transparent linear-trend baseline with expanding-window backtest.

    Six annual observations are required. This is a reference forecast only; it
    is not a causal model and no statistical confidence interval is implied.
    """
    detail = branch_detail(code)
    if detail is None:
        return None

    output: dict[str, Any] = {}
    for metric, rows in detail["history"].items():
        points_map: dict[int, float] = {}
        for row in rows:
            try:
                points_map[int(row["year"])] = float(row["value"])
            except (TypeError, ValueError):
                continue
        points = sorted(points_map.items())
        if len(points) < 6:
            output[metric] = {
                "available": False,
                "reason": "At least six annual observations are required for a baseline forecast and expanding-window backtest.",
                "observations": len(points),
            }
            continue

        def fit(train: list[tuple[int, float]], target_year: int) -> float:
            xs = [float(year) for year, _ in train]
            ys = [value for _, value in train]
            x_bar, y_bar = mean(xs), mean(ys)
            denom = sum((x - x_bar) ** 2 for x in xs)
            slope = sum((x - x_bar) * (y - y_bar) for x, y in zip(xs, ys)) / denom if denom else 0.0
            return max(0.0, y_bar + slope * (target_year - x_bar))

        errors_model: list[float] = []
        errors_naive: list[float] = []
        for index in range(4, len(points)):
            train = points[:index]
            actual_year, actual_value = points[index]
            errors_model.append(abs(actual_value - fit(train, actual_year)))
            errors_naive.append(abs(actual_value - train[-1][1]))

        last_year, last_value = points[-1]
        forecasts = []
        for step in range(1, max(1, min(int(horizon), 5)) + 1):
            future_year = last_year + step
            estimate = fit(points, future_year)
            forecasts.append({"year": future_year, "value": round(estimate, 2)})

        all_fit_errors = [value - fit(points, year) for year, value in points]
        residual_scale = mean(abs(error) for error in all_fit_errors) if all_fit_errors else 0.0
        slope_per_year = (forecasts[0]["value"] - last_value) if forecasts else 0.0
        output[metric] = {
            "available": True,
            "method": "Linear trend baseline",
            "observations": len(points),
            "historical_start": points[0][0],
            "historical_end": last_year,
            "last_observed_value": round(last_value, 2),
            "direction": "increasing" if slope_per_year > 0 else "decreasing" if slope_per_year < 0 else "stable",
            "backtest_mae": round(mean(errors_model), 2) if errors_model else None,
            "naive_baseline_mae": round(mean(errors_naive), 2) if errors_naive else None,
            "mean_absolute_in_sample_residual": round(residual_scale, 2),
            "forecasts": forecasts,
            "uncertainty_note": "Point estimates only. Compare the backtest MAE with the naive baseline; this model does not provide a calibrated prediction interval.",
        }
    return output
