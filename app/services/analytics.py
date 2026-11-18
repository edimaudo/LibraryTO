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
    "circulation": "Annual Circulation",
    "visits": "Annual Visitation",
    "workstations": "Annual Workstation Usage",
    "registrations": "Annual Card Registrations",
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
    """Build one process-cached overview payload for all overview visualizations."""
    branches = branch_records()
    branch_by_code = {branch["code"].casefold(): branch for branch in branches}
    all_observations = observations()
    trend_values: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    years_by_metric: dict[str, set[str]] = defaultdict(set)
    latest_totals: dict[str, float] = {}
    latest_years: dict[str, str] = {}
    unique: dict[tuple[str, str, str], float] = {}
    canonical_codes = {branch["code"].casefold(): branch["code"] for branch in branches}
    for item in all_observations:
        canonical_code = canonical_codes.get(item["branch_code"].casefold())
        if canonical_code:
            unique[(item["metric"], item["year"], canonical_code)] = item["value"]
    for (metric, year, code), value in unique.items():
        trend_values[metric][year] += value
        years_by_metric[metric].add(year)

    trend: dict[str, list[dict[str, Any]]] = {}
    annual_values: dict[str, list[dict[str, Any]]] = {}
    years: set[str] = set()
    for metric in METRICS:
        ordered_years = sorted(years_by_metric.get(metric, set()), key=_year_key)
        years.update(ordered_years)
        trend[metric] = [
            {"year": year, "value": round(trend_values[metric][year], 2)}
            for year in ordered_years
        ]
        annual_values[metric] = [
            {
                "year": year,
                "values": {
                    branch["code"]: unique.get((metric, year, branch["code"]))
                    for branch in branches
                },
            }
            for year in ordered_years
        ]
        if ordered_years:
            latest = ordered_years[-1]
            latest_years[metric] = latest
            latest_totals[metric] = round(trend_values[metric][latest], 2)

    tier_counts: dict[str, int] = defaultdict(int)
    for branch in branches:
        tier_counts[branch["service_tier_code"] or "Other"] += 1

    tier_trends: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for metric in METRICS:
        metric_rows = []
        for year_row in annual_values[metric]:
            tier_totals: dict[str, float] = defaultdict(float)
            tier_n: dict[str, int] = defaultdict(int)
            for branch in branches:
                value = year_row["values"].get(branch["code"])
                if value is None:
                    continue
                tier = branch["service_tier_code"] or "Other"
                tier_totals[tier] += value
                tier_n[tier] += 1
            metric_rows.append({
                "year": year_row["year"],
                "network": sum(value for value in year_row["values"].values() if value is not None),
                "tiers": {tier: {"value": round(tier_totals[tier], 2), "n": tier_n[tier]} for tier in sorted(tier_totals)},
            })
        tier_trends[metric] = metric_rows

    return {
        "branch_count": len(branches),
        "totals": latest_totals,
        "latest_years": latest_years,
        "trend": trend,
        "tiers": dict(sorted(tier_counts.items())),
        "metrics": METRICS,
        "branches": branches,
        "years": sorted(years, key=_year_key),
        "annual_values": annual_values,
        "tier_trends": tier_trends,
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
    clean_codes = tuple(dict.fromkeys(code.strip() for code in codes if code.strip()))[:5]
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
def event_filter_options() -> dict[str, Any]:
    events = event_records()
    unique_values = lambda key: sorted({str(item.get(key) or "").strip() for item in events if str(item.get(key) or "").strip()}, key=str.casefold)
    branches = [{"code": item["code"], "name": item["name"]} for item in branch_records()]
    return {
        "audiences": unique_values("audiences"),
        "languages": unique_values("languages"),
        "event_types": unique_values("types"),
        "branches": branches,
        "analysis": event_discovery_analysis(),
    }


def summarize_event_list(events: list[dict[str, Any]], branch_lookup: dict[str, str] | None = None) -> dict[str, Any]:
    branch_lookup = branch_lookup or {item["code"].casefold(): item["name"] for item in branch_records()}
    counts: dict[str, dict[str, int]] = {
        "types": defaultdict(int), "audiences": defaultdict(int),
        "languages": defaultdict(int), "branches": defaultdict(int),
    }

    def split_values(raw: Any) -> list[str]:
        values = re.split(r"[;,|]+", str(raw or ""))
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    for event in events:
        for key in ("types", "audiences", "languages"):
            for value in split_values(event.get(key)):
                counts[key][value] += 1
        code = str(event.get("branch_code") or "").casefold()
        branch_label = branch_lookup.get(code) or str(event.get("location") or "Not specified").strip()
        if branch_label:
            counts["branches"][branch_label] += 1

    def ordered(values: dict[str, int]) -> list[dict[str, Any]]:
        return [{"label": label, "count": count} for label, count in sorted(values.items(), key=lambda item: (-item[1], item[0].casefold()))]

    return {
        "total_upcoming": len(events),
        "types": ordered(counts["types"]),
        "audiences": ordered(counts["audiences"]),
        "languages": ordered(counts["languages"]),
        "branches": ordered(counts["branches"]),
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
        # Explicit categorical selections are filters, not ranking hints. Interests
        # remain relevance signals because they are free-text and can match loosely.
        matches_selected_categories = True
        for key, haystack, label in checks:
            target = requested[key]
            if target:
                if target not in str(haystack).casefold():
                    matches_selected_categories = False
                    break
                score += 2
                reasons.append(label)
        if not matches_selected_categories:
            continue
        if requested["branch"]:
            event_location = str(event.get("location") or "").casefold()
            event_code = str(event.get("branch_code") or "").casefold()
            branch_matches = requested["branch"] == event_code or (
                bool(selected_branch_name) and selected_branch_name in event_location
            )
            if not branch_matches:
                continue
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
    return {
        "events": candidates[:100],
        "total": len(candidates),
        "date": selected_date.isoformat() if selected_date else None,
        "analysis": summarize_event_list(candidates, {key: value["name"] for key, value in branch_lookup.items()}),
    }


@lru_cache(maxsize=1)
def event_discovery_analysis() -> dict[str, Any]:
    """Descriptive upcoming-event breakdowns based only on fields in the event feed."""
    today = _today()
    upcoming = []
    for event in event_records():
        when = _event_datetime(event)
        if when is not None and when.date() >= today:
            upcoming.append(event)
    return summarize_event_list(upcoming)


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
