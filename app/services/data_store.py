"""Read-only CSV loading, field normalization, and source-file diagnostics."""
from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import DATA_DIR

DATASETS: dict[str, dict[str, Any]] = {
    "branches": {
        "filename": "tpl-branch-general-information.csv",
        "label": "Branch general information",
        "required": [("branchcode", "code"), ("branchname", "physicalbranch", "name")],
    },
    "circulation": {
        "filename": "tpl-circulation-annual-by-branch.csv",
        "label": "Annual circulation by branch",
        "required": [("branchcode", "code"), ("year", "fiscalyear"), ("circulation", "value", "totalcirculation")],
    },
    "visits": {
        "filename": "tpl-visits-annual-by-branch.csv",
        "label": "Annual visits by branch",
        "required": [("branchcode", "code"), ("year", "fiscalyear"), ("visits", "value", "totalvisits")],
    },
    "workstations": {
        "filename": "tpl-workstation-usage-annual-by-branch.csv",
        "label": "Annual workstation usage by branch",
        "required": [("branchcode", "code"), ("year", "fiscalyear"), ("sessions", "value", "workstationsessions", "workstationusage")],
    },
    "registrations": {
        "filename": "tpl-card-registrations-annual-by-branch.csv",
        "label": "Annual card registrations by branch",
        "required": [("branchcode", "code"), ("year", "fiscalyear"), ("registrations", "value", "cardregistrations", "newregistrations")],
    },
    "events": {
        "filename": "tpl-events-feed.csv",
        "label": "Programs and events feed",
        "required": [("title", "eventtitle", "name")],
    },
}

METRIC_FIELDS = {
    "circulation": ("circulation", "totalcirculation", "value"),
    "visits": ("visits", "totalvisits", "value"),
    "workstations": ("sessions", "workstationsessions", "workstationusage", "usage", "value"),
    "registrations": ("registrations", "cardregistrations", "newregistrations", "value"),
}

SERVICE_FIELDS = {
    "kidsstop": "KidsStop",
    "leadingreading": "Leading Reading",
    "clc": "Community-led services",
    "dih": "Digital Innovation Hub",
    "teencouncil": "Teen Council",
    "youthhub": "Youth Hub",
    "adultliteracyprogram": "Adult Literacy Program",
}

TRUE_VALUES = {"1", "true", "yes", "y", "t", "available", "offered"}


def normalize_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def field(row: dict[str, Any], *names: str, default: Any = "") -> Any:
    lookup = {normalize_key(k): v for k, v in row.items()}
    for name in names:
        value = lookup.get(normalize_key(name))
        if value is not None and str(value).strip() != "":
            return value
    return default


def number(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    cleaned = str(value).strip().replace(",", "").replace("$", "")
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]
    cleaned = cleaned.replace("%", "")
    try:
        parsed = float(cleaned)
        return parsed if parsed == parsed and abs(parsed) != float("inf") else default
    except (TypeError, ValueError):
        return default


def _read_csv(path: Path | None) -> list[dict[str, str]]:
    if path is None or not path.is_file():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                return []
            return [
                {(key or "").strip(): (value or "").strip() for key, value in row.items()}
                for row in reader
            ]
    except (OSError, csv.Error, UnicodeDecodeError):
        return []


@lru_cache(maxsize=1)
def load_all() -> dict[str, list[dict[str, str]]]:
    return {
        key: _read_csv(DATA_DIR / spec["filename"])
        for key, spec in DATASETS.items()
    }


def refresh_data_cache() -> None:
    load_all.cache_clear()


def dataset_path(key: str) -> Path:
    return DATA_DIR / DATASETS[key]["filename"]


def branch_records() -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in load_all()["branches"]:
        code = str(field(row, "BranchCode", "Branch Code", "Code")).strip()
        if not code:
            continue
        services = []
        for key, label in SERVICE_FIELDS.items():
            raw_flag = str(field(row, key)).strip().lower()
            if raw_flag in TRUE_VALUES:
                services.append(label)
        tier_raw = str(field(row, "ServiceTier", "Service Tier", "ServiceTierCode", "Tier")).strip()
        tier_names = {
            "DL": "District Library",
            "NL": "Neighbourhood Library",
            "RR": "Research & Reference Library",
        }
        tier = tier_names.get(tier_raw.upper(), tier_raw)
        output.append({
            "code": code,
            "name": str(field(row, "BranchName", "Branch Name", "PhysicalBranch", "Name", default=code)).strip(),
            "address": str(field(row, "Address", "StreetAddress", "AddressLine1")).strip(),
            "postal_code": str(field(row, "PostalCode", "Postal Code")).strip(),
            "service_tier": tier,
            "service_tier_code": tier_raw.upper(),
            "square_footage": number(field(row, "SquareFootage", "Square Footage", "GrossFloorArea", "AreaSqFt")),
            "workstations": number(field(row, "Workstations", "NumberOfWorkstations", "WorkstationCount")),
            "lat": number(field(row, "Lat", "Latitude", "Y")),
            "lon": number(field(row, "Long", "Longitude", "Lon", "X")),
            "website": str(field(row, "Website", "URL", "BranchWebsite")).strip(),
            "telephone": str(field(row, "Telephone", "Phone", "TelephoneNumber")).strip(),
            "services": services,
        })
    output.sort(key=lambda item: item["name"].casefold())
    return output


def observations(metric: str | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for metric_key, aliases in METRIC_FIELDS.items():
        if metric and metric != metric_key:
            continue
        for row in load_all()[metric_key if metric_key != "workstations" else "workstations"]:
            code = str(field(row, "BranchCode", "Branch Code", "Code")).strip()
            year_value = field(row, "Year", "FiscalYear", "CalendarYear")
            year_text = str(year_value).strip()
            year_match = re.search(r"(?:19|20)\d{2}", year_text)
            year = year_match.group(0) if year_match else year_text
            value = number(field(row, *aliases))
            if code and year and value is not None:
                rows.append({"branch_code": code, "year": year, "metric": metric_key, "value": value})
    return rows


def _truthy(row: dict[str, Any], *fields: str) -> bool:
    return str(field(row, *fields)).strip().lower() in TRUE_VALUES


def event_records() -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for index, row in enumerate(load_all()["events"]):
        title = str(field(row, "Title", "EventTitle", "EventName", "Name")).strip()
        if not title:
            continue
        start = str(field(row, "StartDateLocal", "StartDateTime", "StartDate", "Date", "start")).strip()
        start_time = str(field(row, "StartTimeLocal", "StartTime", "Time")).strip()
        if start and start_time and "T" not in start and " " not in start:
            start = f"{start} {start_time}"
        end = str(field(row, "EndDateLocal", "EndDateTime", "EndDate", "EndTime")).strip()
        registration_status = str(field(row, "RegistrationStatus", "RegistrationAvailability", "Registration")).strip()
        registration_open = _truthy(row, "RegistrationOpen", "IsRegistrationOpen", "RegistrationAvailable", "IsRegistrationAvailable") or registration_status.casefold() in {"open", "available", "registration open"}
        output.append({
            "id": str(field(row, "EventID", "EventId", "_id", "ID", default=index + 1)).strip(),
            "title": title,
            "start": start,
            "end": end,
            "location": str(field(row, "LocationName", "BranchName", "Location", "Venue")).strip(),
            "branch_code": str(field(row, "BranchCode", "Branch Code")).strip(),
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


def _present_headers(key: str) -> set[str]:
    rows = load_all()[key]
    if not rows:
        return set()
    return {normalize_key(k) for k in rows[0].keys()}


def dataset_status() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for key, spec in DATASETS.items():
        path = dataset_path(key)
        rows = load_all()[key]
        headers = _present_headers(key)
        missing = [
            " or ".join(group)
            for group in spec["required"]
            if not any(alias in headers for alias in group)
        ]
        years: list[int] = []
        if key in {"circulation", "visits", "workstations", "registrations"}:
            for row in rows:
                raw_year = field(row, "Year", "FiscalYear", "CalendarYear")
                match = re.search(r"(?:19|20)\d{2}", str(raw_year))
                if match:
                    years.append(int(match.group(0)))
        result[key] = {
            "label": spec["label"],
            "filename": spec["filename"],
            "exists": path.is_file(),
            "loaded": bool(rows) and not missing,
            "rows": len(rows),
            "missing_fields": missing,
            "first_year": min(years) if years else None,
            "last_year": max(years) if years else None,
            "size_bytes": path.stat().st_size if path.is_file() else 0,
        }
    return result
