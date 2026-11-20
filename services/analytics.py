"""Cached descriptive analytics, Relate-backed comparisons and ARIMA forecasts."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo
import math
import re
import warnings

from app.services.data_store import branch_records, observations, event_records

TORONTO_TZ = ZoneInfo("America/Toronto")
METRICS = {"circulation": "Annual Circulation", "visits": "Annual Visitation", "workstations": "Annual Workstation Usage", "registrations": "Annual Card Registrations"}


def _today() -> date:
    return datetime.now(TORONTO_TZ).date()


def _year_key(value: str) -> tuple[int, str]:
    try:
        return int(value), value
    except (TypeError, ValueError):
        return 0, str(value)


def _event_datetime(event: dict[str, Any]) -> datetime | None:
    raw = str(event.get("start") or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        for pattern in ("%Y-%m-%d %H:%M", "%Y-%m-%d %I:%M %p", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw, pattern)
            except ValueError:
                pass
    return None


def _event_end_datetime(event: dict[str, Any]) -> datetime | None:
    raw = str(event.get("end") or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        for pattern in ("%Y-%m-%d %H:%M", "%Y-%m-%d %I:%M %p", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw, pattern)
            except ValueError:
                pass
    return None


def _event_sort_key(event: dict[str, Any]) -> tuple[int, str]:
    parsed = _event_datetime(event)
    return (0 if parsed else 1, parsed.isoformat() if parsed else "")


@lru_cache(maxsize=1)
def overview() -> dict[str, Any]:
    """Build one cached payload containing every reporting year and physical branch."""
    branches = branch_records()
    branch_codes = {branch["code"].casefold(): branch["code"] for branch in branches}
    unique: dict[tuple[str, str, str], float] = {}
    for item in observations():
        code = branch_codes.get(item["branch_code"].casefold())
        if code:
            unique[(item["metric"], str(item["year"]), code)] = float(item["value"])
    years_by_metric: dict[str, set[str]] = defaultdict(set)
    totals_by_metric_year: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for (metric, year, code), value in unique.items():
        years_by_metric[metric].add(year)
        totals_by_metric_year[metric][year] += value
    trends, annual_values, latest_totals, latest_years = {}, {}, {}, {}
    all_years: set[str] = set()
    for metric in METRICS:
        years = sorted(years_by_metric[metric], key=_year_key)
        all_years.update(years)
        trends[metric] = [{"year": year, "value": round(totals_by_metric_year[metric][year], 2)} for year in years]
        annual_values[metric] = [{"year": year, "values": {branch["code"]: unique.get((metric, year, branch["code"])) for branch in branches}} for year in years]
        if years:
            latest_years[metric] = years[-1]
            latest_totals[metric] = round(totals_by_metric_year[metric][years[-1]], 2)
    tier_counts: dict[str, int] = defaultdict(int)
    tier_trends: dict[str, list[dict[str, Any]]] = {}
    for branch in branches:
        tier_counts[branch["service_tier_code"] or "Other"] += 1
    for metric in METRICS:
        series = []
        for record in annual_values[metric]:
            tier_totals: dict[str, float] = defaultdict(float)
            tier_n: dict[str, int] = defaultdict(int)
            for branch in branches:
                value = record["values"].get(branch["code"])
                if value is not None:
                    tier = branch["service_tier_code"] or "Other"
                    tier_totals[tier] += float(value)
                    tier_n[tier] += 1
            series.append({"year": record["year"], "tiers": {tier: {"value": round(tier_totals[tier], 2), "n": tier_n[tier]} for tier in sorted(tier_totals)}})
        tier_trends[metric] = series
    return {"branch_count": len(branches), "totals": latest_totals, "latest_years": latest_years, "trend": trends,
            "tiers": dict(sorted(tier_counts.items())), "metrics": METRICS, "branches": branches,
            "years": sorted(all_years, key=_year_key), "annual_values": annual_values, "tier_trends": tier_trends}


@lru_cache(maxsize=100)
def branch_detail(code: str) -> dict[str, Any] | None:
    branch = next((item for item in branch_records() if item["code"].casefold() == code.casefold()), None)
    if branch is None:
        return None
    rows = [item for item in observations() if item["branch_code"].casefold() == code.casefold()]
    unique = {(item["metric"], item["year"]): item["value"] for item in rows}
    history = {}
    for metric in METRICS:
        history[metric] = sorted([{"year": year, "value": value} for (key, year), value in unique.items() if key == metric], key=lambda row: _year_key(row["year"]))
    hosted = []
    today = _today()
    for event in event_records():
        event_code = event.get("branch_code", "")
        location = event.get("location", "")
        when = _event_datetime(event)
        if when is not None and when.date() >= today and ((event_code and event_code.casefold() == code.casefold()) or branch["name"].casefold() in location.casefold()):
            hosted.append(event)
    hosted.sort(key=_event_sort_key)
    return {"branch": branch, "history": history, "events": hosted}


def _csv_compare(clean_codes: tuple[str, ...]) -> dict[str, Any]:
    lookup = {item["code"].casefold(): item for item in branch_records()}
    selected = [lookup[code.casefold()] for code in clean_codes if code.casefold() in lookup]
    selected_codes = {item["code"].casefold() for item in selected}
    values: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    for row in observations():
        if row["branch_code"].casefold() in selected_codes:
            values[row["metric"]][row["year"]][row["branch_code"]] = float(row["value"])
    metrics = {metric: [{"year": year, "values": {branch["code"]: values[metric][year].get(branch["code"]) for branch in selected}} for year in sorted(values[metric], key=_year_key)] for metric in METRICS}
    return {"branches": selected, "metrics": metrics, "metric_labels": METRICS, "data_source": "Relate graph if available; CSV snapshot fallback"}


def compare(codes: list[str]) -> dict[str, Any]:
    return _compare_cached(tuple(dict.fromkeys(code.strip() for code in codes if code.strip()))[:5])


@lru_cache(maxsize=256)
def _compare_cached(clean_codes: tuple[str, ...]) -> dict[str, Any]:
    """Use Relate graph metric nodes when the graph is available, then CSV fallback."""
    if not clean_codes:
        return {"branches": [], "metrics": {metric: [] for metric in METRICS}, "metric_labels": METRICS, "data_source": "Relate graph"}
    try:
        from app.services.relate_compare import compare_from_relate
        graph_result = compare_from_relate(clean_codes)
        if graph_result and graph_result.get("metrics"):
            return graph_result
    except Exception:
        # A read-only CSV snapshot remains a deterministic fallback if the .rl
        # file is absent or its schema does not expose annual observations.
        pass
    return _csv_compare(clean_codes)


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def _parse_time(value: Any) -> time | None:
    try:
        return time.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def _split_values(raw: Any) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in re.split(r"[;,|]+", str(raw or "")) if value.strip()))


def summarize_event_list(events: list[dict[str, Any]], branch_lookup: dict[str, str] | None = None) -> dict[str, Any]:
    branch_lookup = branch_lookup or {item["code"].casefold(): item["name"] for item in branch_records()}
    counts: dict[str, dict[str, int]] = {key: defaultdict(int) for key in ("types", "audiences", "languages", "branches")}
    for event in events:
        for key in ("types", "audiences", "languages"):
            for value in _split_values(event.get(key)):
                counts[key][value] += 1
        code = str(event.get("branch_code") or "").casefold()
        label = branch_lookup.get(code) or str(event.get("location") or "Not specified").strip()
        if label:
            counts["branches"][label] += 1
    order = lambda values: [{"label": label, "count": count} for label, count in sorted(values.items(), key=lambda item: (-item[1], item[0].casefold()))]
    return {"total_upcoming": len(events), **{key: order(values) for key, values in counts.items()}}


@lru_cache(maxsize=1)
def event_discovery_analysis() -> dict[str, Any]:
    today = _today()
    events = [event for event in event_records() if (when := _event_datetime(event)) is not None and when.date() >= today]
    return summarize_event_list(events)


@lru_cache(maxsize=1)
def event_filter_options() -> dict[str, Any]:
    events = event_records()
    unique = lambda key: sorted({str(item.get(key) or "").strip() for item in events if str(item.get(key) or "").strip()}, key=str.casefold)
    return {"audiences": unique("audiences"), "languages": unique("languages"), "event_types": unique("types"),
            "branches": [{"code": item["code"], "name": item["name"]} for item in branch_records()], "analysis": event_discovery_analysis()}


def recommend_events(preferences: dict[str, Any]) -> dict[str, Any]:
    key = tuple(sorted((str(name), str(value or "")) for name, value in preferences.items()))
    return _recommend_events_cached(key)


@lru_cache(maxsize=512)
def _recommend_events_cached(cache_key: tuple[tuple[str, str], ...]) -> dict[str, Any]:
    prefs = dict(cache_key)
    selected_date, start_time, end_time = _parse_date(prefs.get("date")), _parse_time(prefs.get("start_time")), _parse_time(prefs.get("end_time"))
    requested = {key: str(prefs.get(key) or "").strip().casefold() for key in ("audience", "language", "event_type", "branch", "interest")}
    available_only = str(prefs.get("registration") or "").casefold() in {"available", "open", "true", "1"}
    branch_lookup = {item["code"].casefold(): item for item in branch_records()}
    selected_branch = branch_lookup.get(requested["branch"])
    candidates = []
    today = _today()
    for event in event_records():
        start = _event_datetime(event)
        if start is None or start.date() < today:
            continue
        if selected_date and start.date() != selected_date:
            continue
        if start_time and start.time() < start_time:
            continue
        end = _event_end_datetime(event)
        if end_time and (end is None or end.time() > end_time):
            continue
        checks = (("audience", event.get("audiences", "")), ("language", event.get("languages", "")), ("event_type", event.get("types", "")))
        if any(requested[key] and requested[key] not in str(value).casefold() for key, value in checks):
            continue
        if requested["branch"]:
            event_code = str(event.get("branch_code") or "").casefold()
            location = str(event.get("location") or "").casefold()
            if requested["branch"] != event_code and not (selected_branch and selected_branch["name"].casefold() in location):
                continue
        full_or_closed = bool(event.get("full") or event.get("closed"))
        if available_only and (not event.get("registration_open") or full_or_closed):
            continue
        score, reasons = 0, []
        for key, value in checks:
            if requested[key]:
                score += 2
                reasons.append(key.replace("_", " ").title())
        interest = requested["interest"]
        if interest:
            words = [word for word in re.findall(r"[\w'-]+", interest) if len(word) > 1]
            blob = " ".join(str(event.get(key) or "") for key in ("title", "description", "types")).casefold()
            matches = [word for word in words if word in blob]
            score += 3 * len(matches)
            reasons.extend(matches[:3])
        if requested["branch"]:
            score += 2
            reasons.append("Branch")
        if full_or_closed:
            reasons.append("Full or closed")
        candidates.append({**event, "match_score": score, "match_reasons": reasons,
                           "registration_status": "Full" if event.get("full") else "Closed" if event.get("closed") else "Registration open" if event.get("registration_open") else "Availability not supplied",
                           "available_for_registration": bool(event.get("registration_open")),
                           "start_iso": start.isoformat(), "end_iso": end.isoformat() if end else None})
    candidates.sort(key=lambda event: (-event["match_score"], event["start_iso"], event["title"].casefold()))
    return {"events": candidates[:100], "total": len(candidates), "date": selected_date.isoformat() if selected_date else None,
            "analysis": summarize_event_list(candidates, {code: branch["name"] for code, branch in branch_lookup.items()})}


@lru_cache(maxsize=100)
def branch_forecasts(code: str) -> dict[str, Any] | None:
    """Fit an ARIMA model and forecast exactly one year after the final observation."""
    detail = branch_detail(code)
    if detail is None:
        return None
    output = {}
    for metric, rows in detail["history"].items():
        points = sorted({int(row["year"]): float(row["value"]) for row in rows if str(row["year"]).isdigit()}.items())
        if len(points) < 6:
            output[metric] = {"available": False, "reason": "At least six annual observations are needed for a forecast.", "forecasts": []}
            continue
        years = [year for year, _ in points]
        if years != list(range(years[0], years[-1] + 1)):
            output[metric] = {"available": False, "reason": "The annual record has gaps, so a forecast is not available.", "forecasts": []}
            continue
        try:
            from statsmodels.tsa.arima.model import ARIMA
            import numpy as np
            values = np.asarray([value for _, value in points], dtype=float)
            candidates = ((0, 1, 0), (1, 1, 0), (0, 1, 1), (1, 1, 1), (2, 1, 0), (0, 1, 2))
            best, best_aic = None, math.inf
            for order in candidates:
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        fitted = ARIMA(values, order=order, enforce_stationarity=False, enforce_invertibility=False).fit()
                    if math.isfinite(float(fitted.aic)) and float(fitted.aic) < best_aic:
                        best, best_aic = fitted, float(fitted.aic)
                except Exception:
                    continue
            if best is None:
                raise RuntimeError("No ARIMA candidate could be fitted")
            estimate = float(best.get_forecast(steps=1).predicted_mean[0])
            target_year = years[-1] + 1
            output[metric] = {"available": True, "method": "ARIMA", "observations": len(points), "historical_end": years[-1],
                              "forecasts": [{"year": target_year, "value": round(max(0, estimate), 2)}]}
        except Exception:
            output[metric] = {"available": False, "reason": "A forecast could not be calculated from the available annual records.", "forecasts": []}
    return output
