"""Cached descriptive analytics, comparisons, event matching and ARIMA forecasts."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time
from functools import lru_cache
from statistics import mean
from typing import Any
from zoneinfo import ZoneInfo
import math
import re
import warnings

from app.services.data_store import branch_records, observations, event_records

TORONTO_TZ = ZoneInfo("America/Toronto")
METRICS = {
    "circulation": "Circulation",
    "visits": "Visits",
    "workstations": "Workstation sessions",
    "registrations": "Card registrations",
}


def _today() -> date:
    return datetime.now(TORONTO_TZ).date()


def _year_key(value: str) -> tuple[int, str]:
    try:
        return int(value), value
    except (TypeError, ValueError):
        return 0, str(value)


@lru_cache(maxsize=1)
def overview() -> dict[str, Any]:
    branches = branch_records()
    all_observations = observations()
    trend_values: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    years_by_metric: dict[str, set[str]] = defaultdict(set)
    latest_totals: dict[str, float] = {}
    latest_years: dict[str, str] = {}

    # Deduplicate branch/metric/year before aggregation.
    unique: dict[tuple[str, str, str], float] = {}
    for item in all_observations:
        unique[(item["metric"], item["year"], item["branch_code"])] = item["value"]
    for (metric, year, code), value in unique.items():
        trend_values[metric][year] += value
        years_by_metric[metric].add(year)

    trend: dict[str, list[dict[str, Any]]] = {}
    for metric in METRICS:
        ordered_years = sorted(years_by_metric.get(metric, set()), key=_year_key)
        trend[metric] = [
            {"year": year, "value": round(trend_values[metric][year], 2)}
            for year in ordered_years
        ]
        if ordered_years:
            latest = ordered_years[-1]
            latest_years[metric] = latest
            latest_totals[metric] = round(trend_values[metric][latest], 2)

    tiers: dict[str, int] = defaultdict(int)
    for branch in branches:
        tiers[branch["service_tier"] or "Not specified"] += 1
    return {
        "branch_count": len(branches),
        "totals": latest_totals,
        "latest_years": latest_years,
        "trend": trend,
        "tiers": dict(sorted(tiers.items())),
        "metrics": METRICS,
    }


def _parse_event_datetime(raw: str) -> datetime | None:
    value = str(raw or "").strip()
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    candidates = [normalized, normalized.replace(" ", "T", 1)]
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
        except ValueError:
            pass
    patterns = (
        "%Y-%m-%d %H:%M", "%Y-%m-%d %I:%M %p", "%Y-%m-%d %I:%M%p", "%Y-%m-%d",
        "%m/%d/%Y %H:%M", "%m/%d/%Y %I:%M %p", "%m/%d/%Y",
    )
    for pattern in patterns:
        try:
            return datetime.strptime(value, pattern)
        except ValueError:
            pass
    return None


def _event_datetime(event: dict[str, Any]) -> datetime | None:
    return _parse_event_datetime(str(event.get("start") or ""))


def _event_end_datetime(event: dict[str, Any]) -> datetime | None:
    return _parse_event_datetime(str(event.get("end") or ""))


def _event_date(event: dict[str, Any]) -> date | None:
    parsed = _event_datetime(event)
    return parsed.date() if parsed else None


def _event_sort_key(event: dict[str, Any]) -> tuple[int, str]:
    parsed = _event_datetime(event)
    return (0 if parsed else 1, parsed.isoformat() if parsed else str(event.get("start", "")))


@lru_cache(maxsize=100)
def branch_detail(code: str) -> dict[str, Any] | None:
    branch = next((item for item in branch_records() if item["code"].casefold() == code.casefold()), None)
    if branch is None:
        return None
    rows = [item for item in observations() if item["branch_code"].casefold() == code.casefold()]
    unique = {(item["metric"], item["year"]): item["value"] for item in rows}
    history: dict[str, list[dict[str, Any]]] = {}
    for metric in METRICS:
        metric_rows = [
            {"year": year, "value": value}
            for (metric_key, year), value in unique.items() if metric_key == metric
        ]
        history[metric] = sorted(metric_rows, key=lambda item: _year_key(item["year"]))

    hosted = []
    today = _today()
    for event in event_records():
        event_code = event.get("branch_code", "")
        location = event.get("location", "")
        code_match = bool(event_code) and event_code.casefold() == code.casefold()
        name_match = bool(branch["name"]) and branch["name"].casefold() in location.casefold()
        event_date = _event_date(event)
        if (code_match or name_match) and (event_date is None or event_date >= today):
            hosted.append(event)
    hosted.sort(key=_event_sort_key)
    return {"branch": branch, "history": history, "events": hosted}


def compare(codes: list[str]) -> dict[str, Any]:
    clean_codes = tuple(dict.fromkeys(code.strip() for code in codes if code.strip()))[:6]
    return _compare_cached(clean_codes)


@lru_cache(maxsize=256)
def _compare_cached(clean_codes: tuple[str, ...]) -> dict[str, Any]:
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
            }
            for year in sorted(data.get(metric, {}), key=_year_key)
        ]
    return {"branches": selected, "metrics": metrics, "metric_labels": METRICS}


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


@lru_cache(maxsize=1)
def event_filter_options() -> dict[str, list[dict[str, str]] | list[str]]:
    events = event_records()
    unique_values = lambda key: sorted({str(item.get(key) or "").strip() for item in events if str(item.get(key) or "").strip()}, key=str.casefold)
    branches = [{"code": item["code"], "name": item["name"]} for item in branch_records()]
    return {
        "audiences": unique_values("audiences"),
        "languages": unique_values("languages"),
        "event_types": unique_values("types"),
        "branches": branches,
    }


def recommend_events(preferences: dict[str, Any]) -> dict[str, Any]:
    """Find upcoming events using only supplied event-feed attributes."""
    cache_key = tuple(sorted((str(key), str(value or "")) for key, value in preferences.items()))
    return _recommend_events_cached(cache_key)


@lru_cache(maxsize=512)
def _recommend_events_cached(cache_key: tuple[tuple[str, str], ...]) -> dict[str, Any]:
    preferences = dict(cache_key)
    selected_date = _parse_date(preferences.get("date"))
    start_time = _parse_time(preferences.get("start_time"))
    end_time = _parse_time(preferences.get("end_time"))
    requested = {
        "audience": str(preferences.get("audience") or "").strip().casefold(),
        "language": str(preferences.get("language") or "").strip().casefold(),
        "event_type": str(preferences.get("event_type") or "").strip().casefold(),
        "branch": str(preferences.get("branch") or "").strip().casefold(),
        "interest": str(preferences.get("interest") or "").strip().casefold(),
    }
    available_only = str(preferences.get("registration") or "").strip().casefold() in {"available", "open", "true", "1"}
    branch_lookup = {item["code"].casefold(): item for item in branch_records()}
    selected_branch = branch_lookup.get(requested["branch"])
    selected_branch_name = selected_branch["name"].casefold() if selected_branch else ""
    candidates = []
    for event in event_records():
        when = _event_datetime(event)
        if when is None or when.date() < _today():
            continue
        if selected_date and when.date() != selected_date:
            continue
        if start_time and when.time() < start_time:
            continue
        event_end = _event_end_datetime(event)
        if end_time and (event_end is None or event_end.time() > end_time):
            continue
        is_unavailable = bool(event["full"] or event["closed"])
        if available_only and (not event.get("registration_open") or event["full"] or event["closed"]):
            continue
        score = 0
        reasons = []
        checks = (
            ("audience", event["audiences"] or "", "Audience"),
            ("language", event["languages"] or "", "Language"),
            ("event_type", event["types"] or "", "Type"),
        )
        for key, haystack, label in checks:
            target = requested[key]
            if target and target in str(haystack).casefold():
                score += 2
                reasons.append(label)
        if requested["branch"]:
            event_location = str(event.get("location") or "").casefold()
            event_code = str(event.get("branch_code") or "").casefold()
            if requested["branch"] == event_code or (selected_branch_name and selected_branch_name in event_location):
                score += 2
                reasons.append("Branch")
        interest = requested["interest"]
        text_blob = " ".join((event["title"], event["description"], event["types"])).casefold()
        if interest:
            terms = [term for term in re.findall(r"[\w'-]+", interest) if len(term) > 1]
            matched_terms = [term for term in terms if term in text_blob]
            if matched_terms:
                score += 3 * len(matched_terms)
                reasons.extend(matched_terms[:3])
        if is_unavailable:
            reasons.append("Full or closed")
        candidates.append({
            **event,
            "match_score": score,
            "match_reasons": reasons,
            "registration_status": "Full" if event["full"] else "Closed" if event["closed"] else "Registration open" if event.get("registration_open") else "Availability not supplied",
            "available_for_registration": bool(event.get("registration_open")),
            "start_iso": when.isoformat(),
            "end_iso": event_end.isoformat() if event_end else None,
        })
    candidates.sort(key=lambda item: (-item["match_score"], item["start_iso"], item["title"].casefold()))
    return {"events": candidates[:100], "total": len(candidates), "date": selected_date.isoformat() if selected_date else None}


@lru_cache(maxsize=100)
def branch_forecasts(code: str) -> dict[str, Any] | None:
    """Fit a small ARIMA candidate set and return estimates for 2025 and 2026 only."""
    detail = branch_detail(code)
    if detail is None:
        return None
    output: dict[str, Any] = {}
    for metric, rows in detail["history"].items():
        point_map: dict[int, float] = {}
        for row in rows:
            try:
                point_map[int(row["year"])] = float(row["value"])
            except (TypeError, ValueError):
                continue
        points = sorted(point_map.items())
        targets = [year for year in (2025, 2026) if not points or year > points[-1][0]]
        if len(points) < 6:
            output[metric] = {"available": False, "reason": "Not enough historical data to estimate this measure.", "observations": len(points), "forecasts": []}
            continue
        years = [year for year, _ in points]
        if years != list(range(years[0], years[-1] + 1)):
            output[metric] = {"available": False, "reason": "Annual records contain gaps, so a reliable annual forecast cannot be calculated.", "observations": len(points), "forecasts": []}
            continue
        if not targets:
            output[metric] = {"available": False, "reason": "Historical records already include both forecast years.", "observations": len(points), "forecasts": []}
            continue
        try:
            from statsmodels.tsa.arima.model import ARIMA
            import numpy as np
            values = np.asarray([value for _, value in points], dtype=float)
            candidates = [(0, 1, 0), (1, 1, 0), (0, 1, 1), (1, 1, 1), (2, 1, 0), (0, 1, 2)]
            best_fit = None
            best_aic = math.inf
            for order in candidates:
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        fitted = ARIMA(values, order=order, enforce_stationarity=False, enforce_invertibility=False).fit()
                    if math.isfinite(float(fitted.aic)) and float(fitted.aic) < best_aic:
                        best_fit, best_aic = fitted, float(fitted.aic)
                except Exception:
                    continue
            if best_fit is None:
                raise RuntimeError("No ARIMA model could be fitted to this history.")
            steps = 2026 - years[-1]
            predicted = best_fit.get_forecast(steps=steps).predicted_mean
            forecast_points = []
            for offset, estimate in enumerate(predicted, start=1):
                target_year = years[-1] + offset
                if target_year in targets:
                    forecast_points.append({"year": target_year, "value": round(max(0.0, float(estimate)), 2)})
            output[metric] = {
                "available": bool(forecast_points),
                "method": "ARIMA",
                "observations": len(points),
                "historical_start": years[0],
                "historical_end": years[-1],
                "forecasts": forecast_points,
            }
            if not forecast_points:
                output[metric]["reason"] = "No forecast years remain after the latest reporting year."
        except Exception:
            output[metric] = {"available": False, "reason": "A forecast could not be produced from the available annual records.", "observations": len(points), "forecasts": []}
    return output
