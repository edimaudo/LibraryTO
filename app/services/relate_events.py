"""Read event/program records from the embedded Relate graph.

The source graph stores event rows as labelled nodes. This adapter discovers the
actual schema at runtime, reads only event-like labels, normalizes supplied
fields, and applies the same future-date and physical-branch rules as the CSV
path. No graph writes or user-provided query text are executed.
"""
from __future__ import annotations

from datetime import date, datetime, time
from functools import lru_cache
import re
from typing import Any
from zoneinfo import ZoneInfo

from app.config import RELATE_FILE
from app.services.data_store import branch_records, field, is_physical_branch, _combine_feed_datetime

TORONTO = ZoneInfo("America/Toronto")


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def _quote(value: str) -> str:
    if not value or any(ord(ch) < 32 for ch in value):
        raise ValueError("Unsafe Relate schema identifier")
    return "`" + value.replace("`", "``") + "`"


def _parse_datetime(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None)
    except ValueError:
        pass
    for pattern in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %I:%M %p", "%Y-%m-%d", "%m/%d/%Y %H:%M"):
        try:
            return datetime.strptime(raw, pattern)
        except ValueError:
            continue
    return None


def _split(value: Any) -> list[str]:
    return [part.strip() for part in re.split(r"[;,|]+", str(value or "")) if part.strip()]


def _event_from_properties(props: dict[str, Any], index: int, eligible: dict[str, dict[str, Any]], eligible_names: dict[str, str]) -> dict[str, Any] | None:
    if not is_physical_branch(props):
        return None
    title = str(field(props, "Title", "EventTitle", "EventName", "ProgramName", "Name")).strip()
    if not title:
        return None
    code = str(field(props, "BranchCode", "Branch Code", "TPLBranchCode")).strip()
    location = str(field(props, "LocationName", "BranchName", "Location", "Venue")).strip()
    if code and code.casefold() not in eligible:
        return None
    if not code and location.casefold() in eligible_names:
        code = eligible_names[location.casefold()]
    start_date = field(props, "StartDateLocal", "StartDate", "Date")
    start_clock = field(props, "StartTimeLocal", "StartTime", "Time")
    start_full = field(props, "StartDateTime", "EventDateTime")
    if not start_full and re.search(r"\d{4}-\d{2}-\d{2}[T ]\d{1,2}:\d{2}", str(start_clock or "")):
        start_full = start_clock
    start = _combine_feed_datetime(start_date, start_clock, start_full)
    end_date = field(props, "EndDateLocal", "EndDate") or (start[:10] if start else "")
    end_clock = field(props, "EndTimeLocal", "EndTime")
    end_full = field(props, "EndDateTime")
    if not end_full and re.search(r"\d{4}-\d{2}-\d{2}[T ]\d{1,2}:\d{2}", str(end_clock or "")):
        end_full = end_clock
    end = _combine_feed_datetime(end_date, end_clock, end_full)
    if not start or _parse_datetime(start) is None:
        return None
    end_dt = _parse_datetime(end)
    status = str(field(props, "RegistrationStatus", "RegistrationAvailability", "Registration")).strip()
    full = str(field(props, "IsFull", "RegistrationIsFull")).casefold() in {"1", "true", "yes"} or status.casefold() == "full"
    closed = str(field(props, "RegistrationClosed", "IsRegistrationClosed")).casefold() in {"1", "true", "yes"} or status.casefold() == "closed"
    open_registration = str(field(props, "RegistrationOpen", "IsRegistrationOpen", "RegistrationAvailable")).casefold() in {"1", "true", "yes", "open", "available"} or status.casefold() in {"open", "available", "registration open"}
    return {
        "id": str(field(props, "EventID", "EventId", "_id", "ID", default=index + 1)),
        "title": title,
        "start": start,
        "end": end,
        "location": location,
        "branch_code": code,
        "audiences": str(field(props, "Audiences", "Audience", "TargetAudience")),
        "languages": str(field(props, "Languages", "Language")),
        "types": str(field(props, "EventTypes", "EventType", "ProgramType", "Category", "Type")),
        "description": str(field(props, "Description", "ShortDescription", "Summary")),
        "registration_url": str(field(props, "RegistrationURL", "RegistrationUrl", "RegisterURL")),
        "event_url": str(field(props, "EventURL", "EventUrl", "URL", "Link")),
        "full": full,
        "closed": closed,
        "registration_open": open_registration,
        "start_iso": _parse_datetime(start).isoformat(),
        "end_iso": end_dt.isoformat() if end_dt else None,
        "registration_status": "Full" if full else "Closed" if closed else "Registration open" if open_registration else "Availability not supplied",
    }


def _today() -> date:
    return datetime.now(TORONTO).date()


def _summary(events: list[dict[str, Any]], branch_names: dict[str, str]) -> dict[str, Any]:
    counts = {key: {} for key in ("types", "audiences", "languages", "branches")}
    for event in events:
        for key in ("types", "audiences", "languages"):
            for label in _split(event.get(key)):
                counts[key][label] = counts[key].get(label, 0) + 1
        code = str(event.get("branch_code") or "").casefold()
        label = branch_names.get(code) or event.get("location") or "Not specified"
        counts["branches"][label] = counts["branches"].get(label, 0) + 1
    return {"total_upcoming": len(events), **{key: [{"label": label, "count": count} for label, count in sorted(values.items(), key=lambda pair: (-pair[1], pair[0].casefold()))] for key, values in counts.items()}}


@lru_cache(maxsize=1)
def _graph_records() -> list[dict[str, Any]] | None:
    if not RELATE_FILE.is_file():
        return None
    try:
        import relate
        connection = relate.connect(database=str(RELATE_FILE), read_only=True)
    except Exception:
        return None
    try:
        schema = connection.execute(
            "CALL db.schema.nodeTypeProperties() YIELD nodeLabels, propertyName RETURN nodeLabels, propertyName LIMIT 1000"
        ).fetchall()
        by_label: dict[str, set[str]] = {}
        for row in schema:
            labels = row.get("nodeLabels") or []
            if isinstance(labels, str):
                labels = [labels]
            for label in labels:
                by_label.setdefault(str(label), set()).add(str(row.get("propertyName") or ""))
        candidate_labels = []
        for label, props in by_label.items():
            normalized = {_norm(name) for name in props}
            has_title = bool(normalized.intersection({"title", "eventtitle", "eventname", "programname", "name"}))
            has_date = any("start" in name and ("date" in name or "time" in name) for name in normalized)
            if ("event" in label.casefold() or "program" in label.casefold()) and has_title and has_date:
                candidate_labels.append(label)
        if not candidate_labels:
            return None
        output = []
        eligible = {branch["code"].casefold(): branch for branch in branch_records()}
        eligible_names = {branch["name"].casefold(): branch["code"] for branch in branch_records()}
        for label in candidate_labels[:8]:
            try:
                rows = connection.execute(f"MATCH (n:{_quote(label)}) RETURN properties(n) AS properties LIMIT 20000").fetchall()
            except Exception:
                continue
            for row in rows:
                props = row.get("properties") or {}
                if not isinstance(props, dict):
                    continue
                event = _event_from_properties(props, len(output) + 1, eligible, eligible_names)
                if event:
                    output.append(event)
        return output
    finally:
        connection.close()


def graph_event_records() -> list[dict[str, Any]] | None:
    """Expose the cached normalized graph event records to filter-option builders."""
    return _graph_records()


def recommend_from_relate(preferences: dict[str, Any], limit: int = 10) -> dict[str, Any] | None:
    """Return filtered event results from Relate; None means graph schema unavailable."""
    records = _graph_records()
    if records is None:
        return None
    branch_names = {branch["code"].casefold(): branch["name"] for branch in branch_records()}
    branch = str(preferences.get("branch") or "").strip().casefold()
    audience = str(preferences.get("audience") or "").strip().casefold()
    language = str(preferences.get("language") or "").strip().casefold()
    event_type = str(preferences.get("event_type") or "").strip().casefold()
    interest = str(preferences.get("interest") or "").strip().casefold()
    selected_date = None
    try:
        selected_date = date.fromisoformat(str(preferences.get("date"))) if preferences.get("date") else None
    except ValueError:
        pass
    start_time = None
    end_time = None
    try:
        start_time = time.fromisoformat(str(preferences.get("start_time"))) if preferences.get("start_time") else None
    except ValueError:
        pass
    try:
        end_time = time.fromisoformat(str(preferences.get("end_time"))) if preferences.get("end_time") else None
    except ValueError:
        pass
    available_only = str(preferences.get("registration") or "").casefold() in {"available", "open", "true", "1"}
    candidates = []
    for event in records:
        when = _parse_datetime(event.get("start"))
        if when is None or when.date() < _today():
            continue
        if selected_date and when.date() != selected_date:
            continue
        if start_time and when.time() < start_time:
            continue
        end_when = _parse_datetime(event.get("end"))
        if end_time and (end_when is None or end_when.time() > end_time):
            continue
        if audience and audience not in event["audiences"].casefold():
            continue
        if language and language not in event["languages"].casefold():
            continue
        if event_type and event_type not in event["types"].casefold():
            continue
        if branch:
            event_code = event["branch_code"].casefold()
            event_location = event["location"].casefold()
            branch_name = branch_names.get(branch, "").casefold()
            if branch != event_code and (not branch_name or branch_name not in event_location):
                continue
        if available_only and (not event["registration_open"] or event["full"] or event["closed"]):
            continue
        text = " ".join((event["title"], event["description"], event["types"])).casefold()
        words = [word for word in re.findall(r"[\w'-]+", interest) if len(word) > 1]
        matches = [word for word in words if word in text]
        score = 3 * len(matches)
        candidates.append({**event, "match_score": score, "match_reasons": matches})
    candidates.sort(key=lambda item: (-item["match_score"], item["start_iso"], item["title"].casefold()))
    shown = candidates[:max(1, min(int(limit), 10))]
    return {"events": shown, "total": len(shown), "matching_count": len(candidates),
            "date": selected_date.isoformat() if selected_date else None,
            "analysis": _summary(shown, branch_names), "data_source": "Relate graph"}
