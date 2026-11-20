"""Intent-aware, read-only question answering for the LibraryTO Relate graph.

The source graph currently imports CSV rows as labelled nodes. It does not
create explicit relationships, so branch-scoped lookups join metric/event
nodes to branch nodes by the shared BranchCode property. Cypher identifiers
come only from the discovered schema and all user values are parameters.
"""
from __future__ import annotations

from datetime import date, datetime, time
import importlib
import re
from typing import Any

from app.config import RELATE_FILE
from app.services.data_store import branch_records, is_physical_branch, number

METRIC_SPECS: dict[str, dict[str, Any]] = {
    "circulation": {
        "label_terms": ("circulation",),
        "question_terms": (r"\bcirculation\b", r"\bcheckouts?\b", r"\bborrowing\b", r"\bloans?\b"),
        "value_aliases": ("circulation", "totalcirculation", "value"),
        "noun": "circulation transactions",
    },
    "visits": {
        "label_terms": ("visits", "visitation"),
        "question_terms": (r"\bvisits?\b", r"\bvisitation\b", r"\bvisitors?\b"),
        "value_aliases": ("visits", "totalvisits", "value"),
        "noun": "visits",
    },
    "workstations": {
        "label_terms": ("workstation",),
        "question_terms": (r"\bworkstations?\b", r"\bcomputer sessions?\b", r"\bcomputer usage\b", r"\bcomputer use\b", r"\bsessions?\b"),
        "value_aliases": ("sessions", "workstationsessions", "workstationusage", "usage", "value"),
        "noun": "workstation sessions",
    },
    "registrations": {
        "label_terms": ("cardregistration", "registrations"),
        "question_terms": (r"\bcard registrations?\b", r"\bregistrations?\b", r"\bnew cards?\b", r"\bcards? issued\b"),
        "value_aliases": ("registrations", "cardregistrations", "newregistrations", "value"),
        "noun": "card registrations",
    },
}

BRANCH_CODE_ALIASES = ("branchcode", "tplbranchcode", "code")
YEAR_ALIASES = ("year", "fiscalyear", "calendaryear")
BRANCH_NAME_ALIASES = ("branchname", "libraryname", "name")
OPENED_YEAR_ALIASES = ("presentsiteyear", "yearopened", "openingyear", "openedyear", "dateopened")
TITLE_ALIASES = ("title", "eventtitle", "eventname", "programname", "name")
_SCHEMA_CACHE_KEY: tuple[str, int, int] | None = None
_SCHEMA_CACHE_VALUE: dict[str, dict[str, str]] | None = None

SERVICE_LABELS = {
    "kidsstop": "Kids Stop",
    "leadingreading": "Leading Reading",
    "clc": "Community-led services",
    "dih": "Digital Innovation Hub",
    "teencouncil": "Teen Council",
    "youthhub": "Youth Hub",
    "adultliteracyprogram": "Adult Literacy Program",
}
TRUE_VALUES = {"1", "1.0", "true", "yes", "y", "t", "available", "offered"}


class RelateUnavailable(RuntimeError):
    """The supplied Relate file or Python client cannot be opened or queried."""


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def _quote_identifier(value: Any) -> str:
    text = str(value or "")
    if not text or any(ord(character) < 32 for character in text):
        raise ValueError("Invalid graph identifier")
    return "`" + text.replace("`", "``") + "`"


def _load_module():
    try:
        return importlib.import_module("relate")
    except ImportError as exc:
        raise RelateUnavailable("The relate-db package is not installed in this environment.") from exc


def _open_connection():
    if not RELATE_FILE.is_file():
        raise RelateUnavailable(f"The graph file {RELATE_FILE.name} has not been added to data/.")
    try:
        return _load_module().connect(database=str(RELATE_FILE), read_only=True)
    except Exception as exc:
        raise RelateUnavailable(f"The graph file could not be opened read-only ({type(exc).__name__}).") from exc


def _fetchall(connection, statement: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return connection.execute(statement, params or {}).fetchall()


def _schema(connection) -> dict[str, dict[str, str]]:
    """Discover graph labels and properties before building any Cypher query."""
    labels = [
        str(row["label"])
        for row in _fetchall(connection, "CALL db.labels() YIELD label RETURN label")
        if row.get("label") and _safe_identifier(str(row["label"]))
    ]
    props: dict[str, dict[str, str]] = {label: {} for label in labels}
    rows = _fetchall(
        connection,
        "CALL db.schema.nodeTypeProperties() YIELD nodeLabels, propertyName "
        "RETURN nodeLabels, propertyName LIMIT 1000",
    )
    for row in rows:
        names = row.get("nodeLabels") or []
        if isinstance(names, str):
            names = [names]
        property_name = str(row.get("propertyName") or "")
        if not property_name or not _safe_identifier(property_name):
            continue
        for label in names:
            if label in props:
                props[str(label)][_norm(property_name)] = property_name

    # Some stores omit property metadata for a label. Inspect one node rather
    # than attempting a text search across every node property.
    for label in labels:
        if props[label]:
            continue
        sample = _fetchall(
            connection,
            f"MATCH (n:{_quote_identifier(label)}) RETURN properties(n) AS properties LIMIT 1",
        )
        if sample and isinstance(sample[0].get("properties"), dict):
            for key in sample[0]["properties"]:
                if isinstance(key, str) and _safe_identifier(key):
                    props[label][_norm(key)] = key
    return props


def _safe_identifier(value: str) -> bool:
    return bool(value) and not any(ord(character) < 32 for character in value)


def _cached_schema(connection) -> dict[str, dict[str, str]]:
    """Cache the immutable graph schema per deployed file revision."""
    global _SCHEMA_CACHE_KEY, _SCHEMA_CACHE_VALUE
    try:
        stat = RELATE_FILE.stat()
        key = (str(RELATE_FILE), stat.st_mtime_ns, stat.st_size)
    except OSError:
        key = (str(RELATE_FILE), 0, 0)
    if _SCHEMA_CACHE_KEY == key and _SCHEMA_CACHE_VALUE is not None:
        return _SCHEMA_CACHE_VALUE
    value = _schema(connection)
    _SCHEMA_CACHE_KEY, _SCHEMA_CACHE_VALUE = key, value
    return value


def graph_schema() -> dict[str, Any]:
    connection = _open_connection()
    try:
        properties = _cached_schema(connection)
        relationships = [
            str(row.get("relationshipType"))
            for row in _fetchall(connection, "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType")
            if row.get("relationshipType")
        ]
        return {
            "available": True,
            "file": RELATE_FILE.name,
            "labels": sorted(properties),
            "relationship_types": sorted(set(relationships)),
            "node_properties": {label: sorted(values.values()) for label, values in sorted(properties.items())},
        }
    except Exception as exc:
        if isinstance(exc, RelateUnavailable):
            raise
        raise RelateUnavailable(f"The graph schema could not be read ({type(exc).__name__}).") from exc
    finally:
        connection.close()


def graph_status() -> dict[str, Any]:
    status = {"filename": RELATE_FILE.name, "file_present": RELATE_FILE.is_file(), "client_available": False, "ready": False, "message": ""}
    if not status["file_present"]:
        status["message"] = f"Add {RELATE_FILE.name} to the data/ directory to enable graph-backed retrieval."
        return status
    try:
        _load_module()
        status["client_available"] = True
        schema = graph_schema()
        status.update(ready=True, labels=schema["labels"], relationship_types=schema["relationship_types"], message="Graph file opened successfully in read-only mode.")
    except RelateUnavailable as exc:
        status["message"] = str(exc)
    return status


def _first_key(properties: dict[str, str], aliases: tuple[str, ...]) -> str | None:
    return next((properties[key] for key in aliases if key in properties), None)


def _label_for_metric(schema: dict[str, dict[str, str]], metric: str) -> tuple[str, dict[str, str]] | None:
    spec = METRIC_SPECS[metric]
    for label, props in schema.items():
        normalized_label = _norm(label)
        if not any(term in normalized_label for term in spec["label_terms"]):
            continue
        if _first_key(props, BRANCH_CODE_ALIASES) and _first_key(props, YEAR_ALIASES) and _first_key(props, spec["value_aliases"]):
            return label, props
    return None


def _label_for_branch(schema: dict[str, dict[str, str]]) -> tuple[str, dict[str, str]] | None:
    for label, props in schema.items():
        if _first_key(props, BRANCH_CODE_ALIASES) and _first_key(props, BRANCH_NAME_ALIASES):
            return label, props
    return None


def _nodes(
    connection,
    label: str,
    properties: dict[str, str],
    *,
    branch_code: str | None = None,
    year: str | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """Fetch bounded rows with exact branch/year predicates and bound values."""
    predicates: list[str] = []
    parameters: dict[str, Any] = {}
    branch_key = _first_key(properties, BRANCH_CODE_ALIASES)
    year_key = _first_key(properties, YEAR_ALIASES)
    if branch_code and branch_key:
        predicates.append(f"toLower(toString(n.{_quote_identifier(branch_key)})) = $branch_code")
        parameters["branch_code"] = branch_code.casefold()
    if year and year_key:
        predicates.append(f"toString(n.{_quote_identifier(year_key)}) = $year")
        parameters["year"] = str(year)
    where = f" WHERE {' AND '.join(predicates)}" if predicates else ""
    statement = (
        f"MATCH (n:{_quote_identifier(label)}){where} "
        f"RETURN properties(n) AS properties LIMIT {max(1, min(int(limit), 5000))}"
    )
    rows = _fetchall(connection, statement, parameters)
    return [row.get("properties") or {} for row in rows if isinstance(row.get("properties"), dict)]


def _normalise_question(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.casefold())).strip()


def _branch_from_question(question: str, branches: list[dict[str, Any]]) -> dict[str, Any] | None:
    normalized = f" {_normalise_question(question)} "
    matches = []
    for branch in branches:
        name = _normalise_question(branch.get("name", ""))
        if name and f" {name} " in normalized:
            matches.append(branch)
    return max(matches, key=lambda item: len(_normalise_question(item.get("name", "")))) if matches else None


def _metric_intent(question: str) -> str | None:
    for metric, spec in METRIC_SPECS.items():
        if any(re.search(pattern, question, flags=re.IGNORECASE) for pattern in spec["question_terms"]):
            return metric
    return None


def _year_intent(question: str) -> str | None:
    match = re.search(r"\b((?:19|20)\d{2})\b", question)
    return match.group(1) if match else None


def _display_number(value: float) -> str:
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"


def _eligible_codes() -> dict[str, dict[str, Any]]:
    return {str(branch["code"]).casefold(): branch for branch in branch_records()}


def _answer_metric(connection, schema, metric: str, year: str, branch: dict[str, Any] | None) -> dict[str, Any]:
    found = _label_for_metric(schema, metric)
    if not found:
        return _not_found(f"The Relate graph does not contain annual {METRIC_SPECS[metric]['noun']} records.")
    label, properties = found
    branch_key = _first_key(properties, BRANCH_CODE_ALIASES)
    year_key = _first_key(properties, YEAR_ALIASES)
    value_key = _first_key(properties, METRIC_SPECS[metric]["value_aliases"])
    if not branch_key or not year_key or not value_key:
        return _not_found("The annual measure is missing its branch, year or value field in the graph schema.")

    rows = _nodes(connection, label, properties, branch_code=branch["code"] if branch else None, year=year, limit=1000)
    eligible = _eligible_codes()
    values_by_code: dict[str, float] = {}
    source_rows: dict[str, dict[str, Any]] = {}
    for props in rows:
        if not is_physical_branch(props):
            continue
        normalized_props = {_norm(key): value for key, value in props.items()}
        code = str(next((normalized_props.get(alias) for alias in BRANCH_CODE_ALIASES if normalized_props.get(alias) not in (None, "")), "")).strip()
        if not code or code.casefold() not in eligible:
            continue
        if branch and code.casefold() != branch["code"].casefold():
            continue
        if str(next((normalized_props.get(alias) for alias in YEAR_ALIASES if normalized_props.get(alias) not in (None, "")), "")).strip() != year:
            continue
        value = number(props.get(value_key))
        if value is None:
            continue
        values_by_code[eligible[code.casefold()]["code"]] = float(value)
        source_rows[eligible[code.casefold()]["code"]] = props

    if not values_by_code:
        target = f" for {branch['name']}" if branch else " across physical branches"
        return _not_found(f"No annual {METRIC_SPECS[metric]['noun']} record was found for {year}{target}.")

    total = sum(values_by_code.values())
    label_text = METRIC_SPECS[metric]["noun"].capitalize()
    display = _display_number(total)
    if branch:
        answer = f"In {year}, {branch['name']} recorded {display} {METRIC_SPECS[metric]['noun']}."
        details = [
            {"label": "Branch", "value": branch["name"]},
            {"label": "Reporting year", "value": year},
            {"label": "Measure", "value": METRICS_LABELS[metric]},
            {"label": "Reported total", "value": display},
        ]
        evidence = [{"labels": [label], "properties": {**source_rows[branch["code"]], "BranchCode": branch["code"]}, "connections": []}]
    else:
        branch_word = "branch" if len(values_by_code) == 1 else "branches"
        answer = f"In {year}, Toronto Public Library recorded {display} {METRIC_SPECS[metric]['noun']} across {len(values_by_code)} physical {branch_word}."
        details = [
            {"label": "Reporting year", "value": year},
            {"label": "Measure", "value": METRICS_LABELS[metric]},
            {"label": "Network total", "value": display},
            {"label": "Branches with reported values", "value": str(len(values_by_code))},
        ]
        evidence = [{"labels": [label], "properties": props, "connections": []} for props in source_rows.values()]
    return {
        "status": "ok",
        "answer": answer,
        "highlights": [{"title": METRICS_LABELS[metric], "category": "Annual measure", "details": details}],
        "evidence": evidence,
        "direct_intent": True,
        "scope_verified": bool(branch),
    }


METRICS_LABELS = {
    "circulation": "Annual Circulation",
    "visits": "Annual Visitation",
    "workstations": "Annual Workstation Usage",
    "registrations": "Annual Card Registrations",
}


def _answer_branch_detail(connection, schema, branch: dict[str, Any], intent: str) -> dict[str, Any]:
    found = _label_for_branch(schema)
    if not found:
        return _not_found("The Relate graph does not contain the branch directory details needed to answer that question.")
    label, properties = found
    branch_key = _first_key(properties, BRANCH_CODE_ALIASES)
    rows = _nodes(connection, label, properties, branch_code=branch["code"], limit=5)
    matching = []
    for props in rows:
        normalized_props = {_norm(key): value for key, value in props.items()}
        record_code = next((normalized_props.get(alias) for alias in BRANCH_CODE_ALIASES if normalized_props.get(alias) not in (None, "")), "")
        if is_physical_branch(props) and str(record_code).casefold() == branch["code"].casefold():
            matching.append(props)
    if not matching:
        return _not_found(f"The Relate branch directory has no record for {branch['name']}.")
    props = matching[0]
    normalized = {_norm(key): value for key, value in props.items()}
    if intent == "opened":
        raw_year = next((normalized[key] for key in OPENED_YEAR_ALIASES if normalized.get(key) not in (None, "")), None)
        if raw_year is None:
            return _not_found(f"The directory does not include an opening-year field for {branch['name']}.")
        year = str(raw_year).strip()
        if re.fullmatch(r"\d{4}(?:\.0)?", year):
            year = str(int(float(year)))
        answer = (
            f"The branch directory lists {year} as the present-site year for {branch['name']}. "
            "It does not state when the branch first opened at an earlier location."
        )
        title = "Present site year"
        details = [{"label": "Present site year", "value": year}]
    elif intent == "services":
        service_values = []
        for key, label_text in SERVICE_LABELS.items():
            value = normalized.get(key)
            if str(value).strip().casefold() in TRUE_VALUES:
                service_values.append(label_text)
        answer = f"The directory lists these services for {branch['name']}: {', '.join(service_values)}." if service_values else f"The directory does not list any of the tracked service flags for {branch['name']}."
        title = "Reported services"
        details = [{"label": "Service", "value": item} for item in service_values] or [{"label": "Reported services", "value": "None listed"}]
    else:
        mapping = {
            "address": ("address", "streetaddress", "location"),
            "telephone": ("telephone", "phone", "telephonenumber"),
            "website": ("website", "url", "branchwebsite"),
        }
        field_aliases = mapping.get(intent, ("branchname",))
        value = next((normalized[key] for key in field_aliases if normalized.get(key) not in (None, "")), None)
        if value is None:
            return _not_found(f"The directory does not list {intent} information for {branch['name']}.")
        title = intent.capitalize()
        details = [{"label": title, "value": str(value)}]
        answer = f"The directory lists {branch['name']}'s {intent} as {value}."
    return {
        "status": "ok",
        "answer": answer,
        "highlights": [{"title": branch["name"], "category": title, "details": details}],
        "evidence": [{"labels": [label], "properties": {**props, "BranchCode": branch["code"]}, "connections": []}],
        "direct_intent": True,
        "scope_verified": True,
    }


def _not_found(message: str) -> dict[str, Any]:
    return {"status": "no_match", "answer": message, "highlights": [], "evidence": [], "direct_intent": True, "scope_verified": True}


def ask(question: str, branch_code: str | None = None) -> dict[str, Any]:
    """Answer a recognized question using a bounded, intent-specific Cypher query.

    Supported intents are annual metrics by year, branch present-site year,
    branch services, and basic branch contact/location fields. Unrecognized
    prompts are not converted into broad keyword searches or branch-name lists.
    """
    question = str(question or "").strip()
    if len(question) < 2:
        return _not_found("Enter a more specific question about a branch or annual measure.")
    branches = branch_records()
    branch = None
    if branch_code:
        branch = next((item for item in branches if item["code"].casefold() == branch_code.casefold()), None)
        if branch is None:
            return _not_found("The selected branch is not in the physical branch directory.")
    else:
        branch = _branch_from_question(question, branches)

    metric = _metric_intent(question)
    year = _year_intent(question)
    q = _normalise_question(question)
    branch_detail_intent = None
    opening_question = (
        re.search(r"\bwhen\s+(?:was|did)\b.{0,60}\b(?:first\s+)?open(?:ed)?\b", q)
        or re.search(r"\bwhat\s+year\b.{0,60}\bopen(?:ed)?\b", q)
        or re.search(r"\b(?:opening|present site)\s+year\b", q)
        or re.search(r"\bfirst\s+opened\b|\bestablished\b", q)
    )
    if opening_question:
        branch_detail_intent = "opened"
    elif re.search(r"\bservices?\b", q):
        branch_detail_intent = "services"
    elif re.search(r"\b(address|located|location)\b", q):
        branch_detail_intent = "address"
    elif re.search(r"\b(phone|telephone|number to call)\b", q):
        branch_detail_intent = "telephone"
    elif re.search(r"\b(website|web site|url)\b", q):
        branch_detail_intent = "website"

    if not metric and not branch_detail_intent:
        return _not_found(
            "I can answer questions about annual circulation, visitation, workstation usage, card registrations, "
            "a branch's present-site year, reported services and branch contact details. Include a reporting year "
            "for an annual measure, or select/name a branch for branch-specific information."
        )
    if metric and not year:
        return _not_found(f"Please include a reporting year for {METRICS_LABELS[metric].lower()}.")
    if branch_detail_intent and branch is None:
        return _not_found("Name a branch or select one in Branch Insights so I can answer with the correct branch record.")

    connection = _open_connection()
    try:
        schema = _cached_schema(connection)
        if metric:
            return _answer_metric(connection, schema, metric, year, branch)
        return _answer_branch_detail(connection, schema, branch, branch_detail_intent or "")
    except RelateUnavailable:
        raise
    except Exception as exc:
        raise RelateUnavailable(f"The graph question could not be answered ({type(exc).__name__}).") from exc
    finally:
        connection.close()
