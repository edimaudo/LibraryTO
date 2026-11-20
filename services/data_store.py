"""Cached, read-only CSV loading and normalization for LibraryTO."""
from __future__ import annotations

import csv
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import DATA_DIR

DATASETS: dict[str, dict[str, Any]] = {
    "branches": {"filename": "tpl-branch-general-information.csv", "label": "Branch general information", "required": [("branchcode", "code"), ("branchname", "name", "libraryname")]},
    "circulation": {"filename": "tpl-circulation-annual-by-branch.csv", "label": "Annual circulation by branch", "required": [("branchcode", "code"), ("year", "fiscalyear"), ("circulation", "value")]},
    "visits": {"filename": "tpl-visits-annual-by-branch.csv", "label": "Annual visits by branch", "required": [("branchcode", "code"), ("year", "fiscalyear"), ("visits", "value")]},
    "workstations": {"filename": "tpl-workstation-usage-annual-by-branch.csv", "label": "Annual workstation usage by branch", "required": [("branchcode", "code"), ("year", "fiscalyear"), ("sessions", "workstationusage", "value")]},
    "registrations": {"filename": "tpl-card-registrations-annual-by-branch.csv", "label": "Annual card registrations by branch", "required": [("branchcode", "code"), ("year", "fiscalyear"), ("registrations", "value")]},
    "events": {"filename": "tpl-events-feed.csv", "label": "Programs and events feed", "required": [("title", "eventtitle", "name")]},
}

METRIC_FIELDS = {
    "circulation": ("circulation", "totalcirculation", "value"),
    "visits": ("visits", "totalvisits", "value"),
    "workstations": ("sessions", "workstationsessions", "workstationusage", "usage", "value"),
    "registrations": ("registrations", "cardregistrations", "newregistrations", "value"),
}
SERVICE_FIELDS = {
    "kidsstop": "Kids Stop", "leadingreading": "Leading Reading",
    "clc": "Community-led services", "dih": "Digital Innovation Hub",
    "teencouncil": "Teen Council", "youthhub": "Youth Hub",
    "adultliteracyprogram": "Adult Literacy Program",
}
TRUE_VALUES = {"1", "1.0", "true", "yes", "y", "t", "available", "offered"}
FALSE_VALUES = {"0", "0.0", "false", "no", "n", "non-physical", "nonphysical", "virtual"}


def normalize_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def field(row: dict[str, Any], *names: str, default: Any = "") -> Any:
    lookup = {normalize_key(key): value for key, value in row.items()}
    for name in names:
        value = lookup.get(normalize_key(name))
        if value is not None and str(value).strip() != "":
            return value
    return default


def number(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    text = str(value).strip().replace(",", "").replace("$", "").replace("%", "")
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    try:
        parsed = float(text)
        return parsed if parsed == parsed and abs(parsed) != float("inf") else default
    except (TypeError, ValueError):
        return default


def is_physical_branch(row: dict[str, Any]) -> bool:
    raw = field(row, "PhysicalBranch", default=None)
    if raw is None or not str(raw).strip():
        return True
    normalized = str(raw).strip().casefold()
    if normalized in FALSE_VALUES:
        return False
    return number(normalized) != 0


def _read_csv(path: Path | None) -> list[dict[str, str]]:
    if path is None or not path.is_file():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                return []
            return [{(key or "").strip(): (value or "").strip() for key, value in row.items()} for row in reader]
    except (OSError, csv.Error, UnicodeDecodeError):
        return []


@lru_cache(maxsize=6)
def load_dataset(key: str) -> list[dict[str, str]]:
    """Load only the CSV needed by a request, once per process."""
    if key not in DATASETS:
        raise KeyError(f"Unknown dataset: {key}")
    return _read_csv(DATA_DIR / DATASETS[key]["filename"])


def load_all() -> dict[str, list[dict[str, str]]]:
    """Compatibility helper; regular request paths use load_dataset lazily."""
    return {key: load_dataset(key) for key in DATASETS}


def dataset_path(key: str) -> Path:
    return DATA_DIR / DATASETS[key]["filename"]


def data_revision() -> str:
    parts = []
    for path in [DATA_DIR / "tpl_library_graph.rl", *(DATA_DIR / spec["filename"] for spec in DATASETS.values())]:
        try:
            stat = path.stat()
            parts.append(f"{path.name}:{stat.st_mtime_ns}:{stat.st_size}")
        except OSError:
            parts.append(f"{path.name}:missing")
    return "|".join(parts)


@lru_cache(maxsize=1)
def branch_records() -> list[dict[str, Any]]:
    """Return the eligible physical branch directory; PhysicalBranch=0 is excluded."""
    by_code: dict[str, dict[str, Any]] = {}
    tier_names = {"DL": "District Library", "NL": "Neighbourhood Library", "RR": "Research and Reference Library"}
    for row in load_dataset("branches"):
        if not is_physical_branch(row):
            continue
        code = str(field(row, "BranchCode", "Branch Code", "Code")).strip()
        if not code:
            continue
        services = [label for key, label in SERVICE_FIELDS.items() if str(field(row, key)).strip().casefold() in TRUE_VALUES]
        raw_tier = str(field(row, "ServiceTier", "Service Tier", "ServiceTierCode", "Tier")).strip()
        tier = tier_names.get(raw_tier.upper(), raw_tier or "Not specified")
        by_code[code.casefold()] = {
            "code": code,
            "name": str(field(row, "BranchName", "Branch Name", "Name", "LibraryName", default=code)).strip(),
            "type_of_library": str(field(row, "TypeOfLibrary", "LibraryType", "BranchType", "Type", default=tier)).strip() or tier,
            "year_opened": str(field(row, "YearOpened", "Year Opened", "OpeningYear", "OpenedYear", "PresentSiteYear")).strip(),
            "address": str(field(row, "Address", "StreetAddress", "Location")).strip(),
            "postal_code": str(field(row, "PostalCode", "Postal Code")).strip(),
            "service_tier": tier,
            "service_tier_code": raw_tier.upper(),
            "square_footage": number(field(row, "SquareFootage", "Square Footage", "GrossFloorArea", "AreaSqFt")),
            "workstations": number(field(row, "Workstations", "NumberOfWorkstations", "WorkstationCount")),
            "lat": number(field(row, "Lat", "Latitude", "Y")),
            "lon": number(field(row, "Long", "Longitude", "Lon", "X")),
            "website": str(field(row, "Website", "URL", "BranchWebsite")).strip(),
            "telephone": str(field(row, "Telephone", "Phone", "TelephoneNumber")).strip(),
            "services": services,
        }
    result = list(by_code.values())
    result.sort(key=lambda branch: branch["name"].casefold())
    return result


@lru_cache(maxsize=1)
def _eligible_branch_codes() -> frozenset[str]:
    return frozenset(branch["code"].casefold() for branch in branch_records())


@lru_cache(maxsize=5)
def observations(metric: str | None = None) -> list[dict[str, Any]]:
    """Return metric observations matched to the physical-branch directory."""
    output: list[dict[str, Any]] = []
    eligible = _eligible_branch_codes()
    for metric_key, aliases in METRIC_FIELDS.items():
        if metric and metric != metric_key:
            continue
        for row in load_dataset(metric_key):
            if not is_physical_branch(row):
                continue
            code = str(field(row, "BranchCode", "Branch Code", "Code")).strip()
            if not code or code.casefold() not in eligible:
                continue
            year_raw = str(field(row, "Year", "FiscalYear", "CalendarYear")).strip()
            year_match = re.search(r"(?:19|20)\d{2}", year_raw)
            year = year_match.group(0) if year_match else ""
            value = number(field(row, *aliases))
            if year and value is not None:
                output.append({"branch_code": code, "year": year, "metric": metric_key, "value": value})
    return output


def _parse_feed_datetime(value: Any) -> str:
    """Normalize a feed timestamp to YYYY-MM-DD HH:MM without duplicating date fields."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    candidate = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
        has_time = bool(re.search(r"[T ]\d{1,2}:\d{2}", raw))
        return parsed.strftime("%Y-%m-%d %H:%M") if has_time else parsed.strftime("%Y-%m-%d")
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %I:%M %p", "%m/%d/%Y %H:%M", "%m/%d/%Y %I:%M %p", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(raw, fmt)
            return parsed.strftime("%Y-%m-%d %H:%M") if "%H" in fmt or "%I" in fmt else parsed.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def _combine_feed_datetime(date_value: Any, time_value: Any, full_value: Any = None) -> str:
    """Prefer a complete timestamp; otherwise combine a date with a time-only value."""
    full = _parse_feed_datetime(full_value)
    if full:
        return full
    date_text = _parse_feed_datetime(date_value)
    if not date_text:
        return ""
    # Some source exports put a complete ISO timestamp in StartTime. Do not
    # append it to StartDateLocal; use it as the authoritative complete value.
    time_raw = str(time_value or "").strip()
    if not time_raw:
        return date_text
    parsed_time = None
    for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M%p"):
        try:
            parsed_time = datetime.strptime(time_raw, fmt).time()
            break
        except ValueError:
            pass
    if parsed_time is None:
        return date_text
    date_part = date_text[:10]
    return f"{date_part} {parsed_time.strftime('%H:%M')}"


def _truthy(row: dict[str, Any], *names: str) -> bool:
    return str(field(row, *names)).strip().casefold() in TRUE_VALUES


@lru_cache(maxsize=1)
def event_records() -> list[dict[str, Any]]:
    """Normalize events and reject malformed, non-physical or orphaned branch records."""
    output: list[dict[str, Any]] = []
    eligible = _eligible_branch_codes()
    branch_lookup = {branch["code"].casefold(): branch["name"] for branch in branch_records()}
    name_to_code = {name.casefold(): code for code, name in branch_lookup.items()}
    for index, row in enumerate(load_dataset("events")):
        if not is_physical_branch(row):
            continue
        title = str(field(row, "Title", "EventTitle", "EventName", "Name")).strip()
        if not title:
            continue
        branch_code = str(field(row, "BranchCode", "Branch Code")).strip()
        location = str(field(row, "LocationName", "BranchName", "Location", "Venue")).strip()
        if branch_code and branch_code.casefold() not in eligible:
            continue
        if not branch_code and location.casefold() in name_to_code:
            branch_code = name_to_code[location.casefold()]
        start_full = field(row, "StartDateTime", "StartTime")
        start_date = field(row, "StartDateLocal", "StartDate", "Date", "start")
        start_clock = field(row, "StartTimeLocal", "Time", "StartTime")
        start = _combine_feed_datetime(start_date, start_clock, start_full)
        end_full = field(row, "EndDateTime", "EndTime")
        end_date = field(row, "EndDateLocal", "EndDate")
        end_clock = field(row, "EndTimeLocal", "EndTime")
        end = _combine_feed_datetime(end_date or start[:10], end_clock, end_full)
        registration_status = str(field(row, "RegistrationStatus", "RegistrationAvailability", "Registration")).strip()
        registration_open = _truthy(row, "RegistrationOpen", "IsRegistrationOpen", "RegistrationAvailable", "IsRegistrationAvailable") or registration_status.casefold() in {"open", "available", "registration open"}
        output.append({
            "id": str(field(row, "EventID", "EventId", "_id", "ID", default=index + 1)).strip(),
            "title": title, "start": start, "end": end, "location": location,
            "branch_code": branch_code,
            "audiences": str(field(row, "Audiences", "Audience", "AgeGroup", "TargetAudience")).strip(),
            "languages": str(field(row, "Languages", "Language")).strip(),
            "types": str(field(row, "EventTypes", "EventType", "Type", "Category")).strip(),
            "description": str(field(row, "Description", "ShortDescription", "Summary")).strip(),
            "registration_url": str(field(row, "RegistrationURL", "RegistrationUrl", "RegisterURL")).strip(),
            "event_url": str(field(row, "EventURL", "EventUrl", "URL", "Link")).strip(),
            "full": _truthy(row, "IsFull", "RegistrationIsFull", "IsRegistrationFull") or registration_status.casefold() == "full",
            "closed": _truthy(row, "RegistrationClosed", "IsRegistrationClosed", "Closed") or registration_status.casefold() == "closed",
            "registration_open": registration_open,
            "recurring": _truthy(row, "IsRecurring", "Recurring"),
            "raw": row,
        })
    return output


@lru_cache(maxsize=6)
def _present_headers(key: str) -> frozenset[str]:
    rows = load_dataset(key)
    return frozenset(normalize_key(name) for name in rows[0].keys()) if rows else frozenset()


@lru_cache(maxsize=1)
def dataset_status() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for key, spec in DATASETS.items():
        path, rows, headers = dataset_path(key), load_all()[key], _present_headers(key)
        missing = [" or ".join(group) for group in spec["required"] if not any(normalize_key(alias) in headers for alias in group)]
        years: list[int] = []
        if key in {"circulation", "visits", "workstations", "registrations"}:
            for row in rows:
                if not is_physical_branch(row):
                    continue
                code = str(field(row, "BranchCode", "Branch Code", "Code")).strip()
                if code.casefold() not in _eligible_branch_codes():
                    continue
                match = re.search(r"(?:19|20)\d{2}", str(field(row, "Year", "FiscalYear", "CalendarYear")))
                if match:
                    years.append(int(match.group(0)))
        result[key] = {"label": spec["label"], "filename": spec["filename"], "exists": path.is_file(), "loaded": bool(rows) and not missing,
                       "rows": len(rows), "missing_fields": missing, "first_year": min(years) if years else None,
                       "last_year": max(years) if years else None, "size_bytes": path.stat().st_size if path.is_file() else 0}
    return result


def refresh_data_cache() -> None:
    """Clear all source and derived caches after replacing a deployment snapshot."""
    for cache in (dataset_status, _present_headers, event_records, observations, _eligible_branch_codes, branch_records, load_dataset):
        cache.cache_clear()
    try:
        from app.services import analytics
        for name in ("overview", "branch_detail", "branch_forecasts", "event_filter_options", "event_discovery_analysis", "_compare_cached", "_recommend_events_cached"):
            cached = getattr(analytics, name, None)
            if cached is not None and hasattr(cached, "cache_clear"):
                cached.cache_clear()
    except ImportError:
        pass
