"""Intent-aware, read-only question answering for the LibraryTO Relate graph.

The source graph currently imports CSV rows as labelled nodes. It does not
create explicit relationships, so branch-scoped lookups join metric/event
nodes to branch nodes by the shared BranchCode property. Cypher identifiers
come only from the discovered schema and all user values are parameters.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
import importlib
import re
from typing import Any

from app.config import RELATE_FILE
from app.services.data_store import branch_records, is_physical_branch, number, load_dataset

METRIC_SPECS: dict[str, dict[str, Any]] = {
    "circulation": {
        "label_terms": ("circulation",),
        "question_terms": (r"\bcirculation\b", r"\bcheckouts?\b", r"\bborrowing\b", r"\bloans?\b", r"\bitems? borrowed\b"),
        "value_aliases": ("circulation", "totalcirculation", "value"),
        "noun": "circulation transactions",
    },
    "visits": {
        "label_terms": ("visits", "visitation"),
        "question_terms": (r"\bvisits?\b", r"\bvisited\b", r"\bvisitation\b", r"\bvisitors?\b", r"\bfoot traffic\b", r"\bpeople came\b", r"\bbranch traffic\b"),
        "value_aliases": ("visits", "totalvisits", "value"),
        "noun": "visits",
    },
    "workstations": {
        "label_terms": ("workstation",),
        "question_terms": (r"\bworkstation usage\b", r"\bcomputer sessions?\b", r"\bcomputer usage\b", r"\bcomputer use\b", r"\bpublic computer use\b", r"\bsessions?\b"),
        "value_aliases": ("sessions", "workstationsessions", "workstationusage", "usage", "value"),
        "noun": "workstation sessions",
    },
    "registrations": {
        "label_terms": ("cardregistration", "registrations"),
        "question_terms": (r"\bcard registrations?\b", r"\bregistrations?\b", r"\bnew cards?\b", r"\bcards? issued\b", r"\blibrary card sign ?ups?\b", r"\bnew library cards?\b"),
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
    """Resolve a branch by its full name or exact branch code in Overview Q&A."""
    normalized = f" {_normalise_question(question)} "
    matches: list[tuple[int, dict[str, Any]]] = []
    for branch in branches:
        name = _normalise_question(branch.get("name", ""))
        code = _normalise_question(branch.get("code", ""))
        if name and f" {name} " in normalized:
            matches.append((len(name), branch))
        if code and f" {code} " in normalized:
            matches.append((len(code), branch))
    return max(matches, key=lambda item: item[0])[1] if matches else None


def _metric_intent(question: str) -> str | None:
    for metric, spec in METRIC_SPECS.items():
        if any(re.search(pattern, question, flags=re.IGNORECASE) for pattern in spec["question_terms"]):
            return metric
    # "How many workstations does this branch have?" is a directory
    # attribute question, not a question about annual computer sessions.
    if re.search(r"\bworkstations?\b", question, re.IGNORECASE) and re.search(
        r"\b(how many|number of|available|has|have|count)\b", question, re.IGNORECASE
    ) and not re.search(r"\b(usage|sessions?|used)\b", question, re.IGNORECASE):
        return None
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


def _year_number(value: Any) -> int | None:
    """Read a year-like directory value without guessing from arbitrary text."""
    match = re.fullmatch(r"\s*((?:18|19|20)\d{2})(?:\.0+)?\s*", str(value or ""))
    return int(match.group(1)) if match else None


def _answer_oldest_branch(connection, schema: dict[str, dict[str, str]]) -> dict[str, Any]:
    """Return the branch with the earliest recorded PresentSiteYear.

    The source directory records the year of the present site, not necessarily
    the original founding year of the library service. The answer therefore
    labels the value explicitly as a present-site year.
    """
    found = _label_for_branch(schema)
    if not found:
        return _not_found("The Relate graph does not contain the branch directory needed to compare branch site years.")
    label, properties = found
    year_key = _first_key(properties, OPENED_YEAR_ALIASES)
    if not year_key:
        return _not_found("The Relate branch directory does not contain a present-site year field.")

    eligible = _eligible_codes()
    rows = _nodes(connection, label, properties, limit=max(1000, len(eligible) * 3))
    candidates: list[tuple[int, str, dict[str, Any]]] = []
    for props in rows:
        if not isinstance(props, dict) or not is_physical_branch(props):
            continue
        normalized = {_norm(key): value for key, value in props.items()}
        code = str(next((normalized.get(alias) for alias in BRANCH_CODE_ALIASES if normalized.get(alias) not in (None, "")), "")).strip()
        if not code or code.casefold() not in eligible:
            continue
        year = _year_number(normalized.get(_norm(year_key)))
        if year is None:
            continue
        directory_branch = eligible[code.casefold()]
        name = str(next((normalized.get(alias) for alias in BRANCH_NAME_ALIASES if normalized.get(alias)), directory_branch["name"])).strip()
        candidates.append((year, name, {**props, "BranchCode": directory_branch["code"], "BranchName": name}))

    if not candidates:
        return _not_found("No physical branch has a valid present-site year in the Relate directory.")

    oldest_year = min(item[0] for item in candidates)
    oldest = sorted((item for item in candidates if item[0] == oldest_year), key=lambda item: item[1].casefold())
    names = [item[1] for item in oldest]
    branch_list = ", ".join(names)
    noun = "branch" if len(names) == 1 else "branches"
    answer = (
        f"The oldest present-site year recorded in the physical branch directory is {oldest_year}, "
        f"listed for {branch_list}. The directory records the year of the current site; "
        "it does not establish when the library service first began."
    )
    details = [
        {"label": "Branch" if len(names) == 1 else "Branches", "value": branch_list},
        {"label": "Present-site year", "value": str(oldest_year)},
        {"label": "Records compared", "value": str(len(candidates))},
    ]
    return {
        "status": "ok",
        "answer": answer,
        "highlights": [{"title": "Oldest listed branch" if len(names) == 1 else "Oldest listed branches", "category": "Branch history", "details": details}],
        "evidence": [{"labels": [label], "properties": props, "connections": []} for _, _, props in oldest],
        "direct_intent": True,
        # This intent deliberately compares all eligible physical branches,
        # even when submitted from a branch-specific question panel.
        "scope_verified": True,
        "network_scope": True,
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


# Directory fields exposed in the branch CSV and imported into Relate. The
# aliases describe the user's language, while the graph schema supplies the
# authoritative property spelling at runtime.
DIRECTORY_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "Address": ("address", "street address", "location", "where is it located", "where is the branch", "where is this branch", "where is", "what is the address", "how do i get to"),
    "PostalCode": ("postal code", "postalcode", "postcode", "zip code", "zip"),
    "Website": ("website", "web site", "url", "online", "web address"),
    "Telephone": ("telephone", "phone number", "phone", "number to call", "contact number", "call this branch"),
    "SquareFootage": ("square footage", "floor area", "floor space", "building area", "building size", "branch size", "size of the branch", "how large is", "how big is", "largest branch", "biggest branch", "smallest branch", "largest library building"),
    "PublicParking": ("public parking", "parking spaces", "parking", "car parking", "parking lot", "parking availability"),
    "KidsStop": ("kids stop", "kidsstop"),
    "LeadingReading": ("leading reading", "leadingreading"),
    "CLC": ("community led services", "community-led services", "clc"),
    "DIH": ("digital innovation hub", "innovation hub", "dih"),
    "TeenCouncil": ("teen council", "teencouncil"),
    "YouthHub": ("youth hub", "youthhub"),
    "AdultLiteracyProgram": ("adult literacy", "adult literacy program", "adultliteracyprogram"),
    "Service Tier": ("service tier", "tier", "library tier", "district library", "district libraries", "neighbourhood library", "neighbourhood libraries", "neighborhood library", "neighborhood libraries", "research and reference library", "research and reference libraries"),
    "TypeOfLibrary": ("type of library", "library type", "branch type"),
    "NBHDName": ("neighbourhood", "neighborhood", "neighbourhood name", "neighborhood name"),
    "NBHDNo": ("neighbourhood number", "neighborhood number"),
    "TPLNIA": ("tpl nia", "nia", "neighbourhood improvement area", "neighborhood improvement area"),
    "WardName": ("ward", "ward name", "city ward", "municipal ward"),
    "WardNo": ("ward number", "ward no", "ward code"),
    "PresentSiteYear": ("present site year", "present-site year", "current site year", "year of the current site", "opening year", "year opened", "oldest", "earliest", "newest branch", "most recently relocated"),
    "PublicWashroom": ("public washroom", "washroom", "restroom", "bathroom", "public toilet", "public bathrooms"),
    "Hours": ("operating hours", "opening hours", "opening times", "opening time", "closing time", "closing hours", "hours", "when does it open", "when does it close", "what time does it open", "what time does it close", "when is the branch open", "weekly schedule", "weekly hours"),
    "Workstations": ("number of workstations", "workstation count", "workstations", "computer count", "number of computers", "computers available", "computers", "public computers"),
    "Lat": ("latitude",),
    "Long": ("longitude",),
}

DIRECTORY_BOOL_FIELDS = {
    "KidsStop", "LeadingReading", "CLC", "DIH", "TeenCouncil", "YouthHub",
    "AdultLiteracyProgram", "PublicWashroom", "TPLNIA",
}
SERVICE_FIELD_KEYS = {
    "kidsstop": "Kids Stop",
    "leadingreading": "Leading Reading",
    "clc": "Community-led services",
    "dih": "Digital Innovation Hub",
    "teencouncil": "Teen Council",
    "youthhub": "Youth Hub",
    "adultliteracyprogram": "Adult Literacy Program",
}
QUESTION_STOPWORDS = {
    "a", "about", "all", "an", "and", "are", "at", "branch", "branches", "can",
    "does", "do", "for", "from", "has", "have", "i", "in", "is", "it", "its",
    "library", "me", "of", "on", "or", "please", "the", "their", "this", "to",
    "was", "were", "what", "which", "who", "with", "would", "tell", "show", "list",
    "give", "find", "provide", "does", "there", "that", "these", "those", "any",
}


def _normalised_properties(properties: dict[str, Any]) -> dict[str, Any]:
    return {_norm(key): value for key, value in properties.items()}


def _directory_rows(connection, schema: dict[str, dict[str, str]], branch: dict[str, Any] | None = None) -> tuple[str, list[tuple[dict[str, Any], dict[str, Any]]]] | None:
    """Load branch-directory rows and retain only known physical branch codes."""
    found = _label_for_branch(schema)
    if not found:
        return None
    label, properties = found
    eligible = _eligible_codes()
    rows = _nodes(
        connection, label, properties,
        branch_code=branch["code"] if branch else None,
        limit=max(1000, min(len(eligible) * 3, 5000)),
    )
    output: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for props in rows:
        if not isinstance(props, dict) or not is_physical_branch(props):
            continue
        normalized = _normalised_properties(props)
        code = str(next((normalized.get(alias) for alias in BRANCH_CODE_ALIASES if normalized.get(alias) not in (None, "")), "")).strip()
        branch_record = eligible.get(code.casefold())
        if not branch_record:
            continue
        if branch and branch_record["code"].casefold() != branch["code"].casefold():
            continue
        output.append((branch_record, props))
    return label, output


def _field_intent(question: str, properties: dict[str, Any] | None = None) -> str | None:
    normalized_question = f" {_normalise_question(question)} "
    if re.search(r"\bward\s+(?:no\.?\s*)?\d+\b", question, re.IGNORECASE):
        return "WardNo"
    candidates: list[tuple[int, str]] = []
    for property_name, aliases in DIRECTORY_FIELD_ALIASES.items():
        for alias in aliases:
            normalized_alias = _normalise_question(alias)
            if normalized_alias and f" {normalized_alias} " in normalized_question:
                candidates.append((len(normalized_alias), property_name))
    if candidates:
        return max(candidates)[1]

    # Resolve named values such as a ward, neighbourhood or service tier to
    # their source column, so users do not need to know the CSV field name.
    if properties:
        query_compact = _norm(question)
        value_matches: list[tuple[int, str]] = []
        for row in load_dataset("branches"):
            if not is_physical_branch(row):
                continue
            for candidate_key in ("WardName", "WardNo", "NBHDName", "NBHDNo", "Service Tier"):
                value = next((row.get(key) for key in row if _norm(key) == _norm(candidate_key)), None)
                if value not in (None, "") and len(_norm(value)) >= 2 and _norm(value) in query_compact:
                    actual = next((key for key in properties if _norm(key) == _norm(candidate_key)), candidate_key)
                    value_matches.append((len(_norm(value)), actual))
        if value_matches:
            return max(value_matches)[1]

    # Accommodate a newly added directory column without requiring a code
    # change, provided the user actually names that column in the question.
    if properties:
        for property_name in properties:
            key = _norm(property_name)
            if key in {"_id", "physicalbranch", "branchcode", "branchname", "geometry"}:
                continue
            if len(key) >= 4 and key in _norm(question):
                return str(property_name)
    return None


def _property_value(properties: dict[str, Any], property_name: str) -> Any:
    normalized = _normalised_properties(properties)
    aliases = {_norm(property_name)}
    aliases.update(_norm(alias) for alias in DIRECTORY_FIELD_ALIASES.get(property_name, ()))
    for alias in aliases:
        if alias in normalized and normalized[alias] not in (None, ""):
            return normalized[alias]
    return None


WEEKDAY_CODES = {
    "monday": "mon", "mon": "mon",
    "tuesday": "tue", "tue": "tue", "tues": "tue",
    "wednesday": "wed", "wed": "wed",
    "thursday": "thu", "thu": "thu", "thur": "thu", "thurs": "thu",
    "friday": "fri", "fri": "fri",
    "saturday": "sat", "sat": "sat",
    "sunday": "sun", "sun": "sun",
}


def _requested_hour_days(question: str) -> tuple[str, ...]:
    q = _normalise_question(question)
    if re.search(r"\bweekdays?\b", q):
        return ("mon", "tue", "wed", "thu", "fri")
    if re.search(r"\bweekends?\b", q):
        return ("sat", "sun")
    return tuple(sorted({code for word, code in WEEKDAY_CODES.items() if re.search(rf"\b{word}\b", q)}, key=("mon", "tue", "wed", "thu", "fri", "sat", "sun").index))


def _hours_segments(value: Any, days: tuple[str, ...]) -> list[str]:
    """Return only the posted schedule segments for the requested weekdays."""
    if value is None:
        return []
    segments = [segment.strip() for segment in re.split(r"[;\n]+", str(value)) if segment.strip()]
    output = []
    for segment in segments:
        match = re.match(r"^\s*(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tue|Tues|Wed|Thu|Thur|Thurs|Fri|Sat|Sun)\b", segment, re.IGNORECASE)
        if match and WEEKDAY_CODES[match.group(1).casefold()] in days:
            output.append(segment)
    return output


def _value_is_mentioned(property_name: str, value: Any, question_compact: str) -> bool:
    normalized_value = _norm(value)
    if normalized_value and normalized_value in question_compact:
        return True
    if _norm(property_name) in {"servicetier", "tier", "servicetiercode"}:
        tier_synonyms = {
            "dl": ("districtlibrary", "districtlibraries"),
            "nl": ("neighbourhoodlibrary", "neighbourhoodlibraries", "neighborhoodlibrary", "neighborhoodlibraries"),
            "rr": ("researchandreferencelibrary", "researchandreferencelibraries"),
        }
        return any(alias in question_compact for alias in tier_synonyms.get(normalized_value, ()))
    return False


def _truth_state(value: Any) -> bool | None:
    if value is None or str(value).strip() == "":
        return None
    normalized = str(value).strip().casefold()
    if normalized in TRUE_VALUES:
        return True
    if normalized in {"0", "0.0", "false", "no", "n", "not available", "none"}:
        return False
    numeric = number(value)
    if numeric is not None:
        return numeric > 0
    return None


def _has_feature(property_name: str, value: Any) -> bool:
    if _norm(property_name) == "publicparking":
        if value is None or str(value).strip() == "":
            return False
        numeric = number(value)
        if numeric is not None:
            return numeric > 0
        return str(value).strip().casefold() not in {"0", "0.0", "false", "no", "n", "none", "not available"}
    return _truth_state(value) is True


def _pretty_value(property_name: str, value: Any) -> str:
    if value is None or str(value).strip() == "":
        return "Not reported"
    normalized = _norm(property_name)
    truth = _truth_state(value)
    if normalized in {_norm(key) for key in DIRECTORY_BOOL_FIELDS}:
        return "Yes" if truth is True else "No" if truth is False else str(value).strip()
    numeric = number(value)
    if numeric is not None:
        if normalized in {"squarefootage", "grossfloorarea", "areasqft"}:
            return f"{_display_number(numeric)} sq ft"
        if normalized == "publicparking":
            return f"{_display_number(numeric)} spaces" if numeric > 0 else "No public parking spaces listed"
        if normalized in {"presentsiteyear", "yearopened", "openingyear", "openedyear"}:
            return str(int(numeric)) if numeric.is_integer() else _display_number(numeric)
        return _display_number(numeric)
    tier_names = {"dl": "District Library", "nl": "Neighbourhood Library", "rr": "Research and Reference Library"}
    if normalized in {"servicetier", "tier", "servicetiercode"} and str(value).strip().casefold() in tier_names:
        return tier_names[str(value).strip().casefold()]
    return str(value).strip()


def _answer_directory_question(
    connection, schema: dict[str, dict[str, str]], question: str,
    branch: dict[str, Any] | None,
) -> dict[str, Any]:
    loaded = _directory_rows(connection, schema, branch)
    if loaded is None:
        return _not_found("The Relate graph does not contain the branch directory needed to answer that question.")
    label, branch_rows = loaded
    if not branch_rows:
        target = f" for {branch['name']}" if branch else " across physical branches"
        return _not_found(f"No branch-directory information was found{target}.")

    field_name = _field_intent(question, branch_rows[0][1])
    q = _normalise_question(question)
    requested_days = _requested_hour_days(question)
    asks_schedule = bool(requested_days and re.search(r"\b(open|opens|opening|close|closes|closing|hours|schedule)\b", q))
    if asks_schedule:
        schedule_rows = []
        for item, props in branch_rows:
            segments = _hours_segments(_property_value(props, "Hours"), requested_days)
            if segments:
                schedule_rows.append((item, props, segments))
        day_labels = ", ".join(day.title() for day in requested_days)
        if branch:
            if not schedule_rows:
                return _not_found(f"The directory does not list posted {day_labels} hours for {branch['name']}.")
            segments = schedule_rows[0][2]
            answer = f"Posted {day_labels} hours for {branch['name']}: {'; '.join(segments)}."
            details = [{"label": "Hours", "value": segment} for segment in segments]
            return {
                "status": "ok", "answer": answer,
                "highlights": [{"title": branch["name"], "category": f"Posted {day_labels} hours", "details": details}],
                "evidence": [{"labels": [label], "properties": schedule_rows[0][1], "connections": []}],
                "direct_intent": True, "scope_verified": True,
            }
        names = [item["name"] for item, _, _ in schedule_rows]
        if re.search(r"\b(how many|number of|count)\b", q):
            answer = f"The directory lists posted {day_labels} hours for {len(names)} of {len(branch_rows)} physical branches."
            details = [{"label": "Branches with listed hours", "value": str(len(names))}, {"label": "Physical branches checked", "value": str(len(branch_rows))}]
        else:
            answer = f"Physical branches with posted {day_labels} hours: " + "; ".join(f"{item['name']}: {'; '.join(segments)}" for item, _, segments in schedule_rows[:15])
            if len(schedule_rows) > 15:
                answer += f"; and {len(schedule_rows) - 15} more"
            answer += "."
            details = [{"label": item["name"], "value": "; ".join(segments)} for item, _, segments in schedule_rows[:15]]
        return {
            "status": "ok", "answer": answer,
            "highlights": [{"title": f"Posted {day_labels} hours", "category": "Physical branches", "details": details}],
            "evidence": [{"labels": [label], "properties": props, "connections": []} for _, props, _ in schedule_rows[:15]],
            "direct_intent": True, "scope_verified": True, "network_scope": True,
        }

    # An unqualified request for services means the tracked services as a
    # group. Individual service questions are handled like any other field.
    asks_all_services = bool(re.search(r"\bservices?\b", q)) and field_name is None
    asks_facilities = bool(re.search(r"\b(facilities|amenities)\b", q)) and field_name is None
    contact_question = bool(re.search(r"\b(contact details|contact information|how can i contact|how do i contact|reach the branch)\b", q))
    profile_question = bool(re.search(
        r"\b(tell me about|about this branch|branch profile|branch details|branch information|overview of|describe this branch|what information|show me the details|give me the details)\b",
        q,
    ))
    if asks_all_services:
        service_entries: list[tuple[str, list[str]]] = []
        for key, display in SERVICE_FIELD_KEYS.items():
            names = []
            for item, props in branch_rows:
                if _truth_state(_property_value(props, key)) is True:
                    names.append(item["name"])
            if names:
                service_entries.append((display, names))
        if branch:
            services = [display for display, names in service_entries if branch["name"] in names]
            answer = f"{branch['name']} has these reported services: {', '.join(services)}." if services else f"The directory does not list any of the tracked services for {branch['name']}."
            details = [{"label": "Service", "value": item} for item in services] or [{"label": "Reported services", "value": "None listed"}]
        else:
            answer = "Reported services across physical branches: " + "; ".join(
                f"{display} ({len(names)} branches): {', '.join(names[:8])}" + (f" and {len(names) - 8} more" if len(names) > 8 else "")
                for display, names in service_entries
            ) if service_entries else "The branch directory does not list any of the tracked services."
            details = [{"label": display, "value": f"{len(names)} branches"} for display, names in service_entries]
        return {
            "status": "ok", "answer": answer,
            "highlights": [{"title": branch["name"] if branch else "Physical branch services", "category": "Reported services", "details": details}],
            "evidence": [{"labels": [label], "properties": props, "connections": []} for item, props in branch_rows if not branch or item["code"].casefold() == branch["code"].casefold()],
            "direct_intent": True, "scope_verified": True, "network_scope": not bool(branch),
        }

    if contact_question and branch:
        props = branch_rows[0][1]
        contact_fields = (
            ("Address", "Address"), ("PostalCode", "Postal code"),
            ("Telephone", "Telephone"), ("Website", "Website"),
        )
        details = []
        for key, label_text in contact_fields:
            value = _property_value(props, key)
            if value not in (None, ""):
                details.append({"label": label_text, "value": str(value).strip()})
        if not details:
            return _not_found(f"The branch directory does not list contact details for {branch['name']}.")
        answer = f"Contact information listed for {branch['name']}: " + "; ".join(f"{item['label']}: {item['value']}" for item in details) + "."
        return {
            "status": "ok", "answer": answer,
            "highlights": [{"title": branch["name"], "category": "Contact information", "details": details}],
            "evidence": [{"labels": [label], "properties": props, "connections": []}],
            "direct_intent": True, "scope_verified": True,
        }

    if asks_facilities:
        if branch:
            facility_details = []
            for key, label_text in (("PublicParking", "Public parking"), ("PublicWashroom", "Public washroom"), ("Workstations", "Workstations"), ("SquareFootage", "Floor area")):
                value = _property_value(branch_rows[0][1], key)
                if value not in (None, ""):
                    facility_details.append({"label": label_text, "value": _pretty_value(key, value)})
            answer = f"The branch directory records these facilities and capacity details for {branch['name']}: " + "; ".join(f"{item['label']}: {item['value']}" for item in facility_details) + "." if facility_details else f"The directory does not report facility details for {branch['name']}."
            details = facility_details
            title = branch["name"]
        else:
            parking = [number(_property_value(props, "PublicParking")) or 0 for _, props in branch_rows]
            washrooms = sum(1 for _, props in branch_rows if _has_feature("PublicWashroom", _property_value(props, "PublicWashroom")))
            workstations = [number(_property_value(props, "Workstations")) for _, props in branch_rows]
            areas = [number(_property_value(props, "SquareFootage")) for _, props in branch_rows]
            details = [
                {"label": "Branches with public washrooms", "value": str(washrooms)},
                {"label": "Reported public parking spaces", "value": _display_number(sum(parking))},
                {"label": "Reported workstations", "value": _display_number(sum(value for value in workstations if value is not None))},
                {"label": "Physical branches checked", "value": str(len(branch_rows))},
            ]
            answer = "Network facility totals from the branch directory: " + "; ".join(f"{item['label']}: {item['value']}" for item in details) + "."
            title = "Physical branch facilities"
        return {
            "status": "ok", "answer": answer,
            "highlights": [{"title": title, "category": "Facilities", "details": details}],
            "evidence": [{"labels": [label], "properties": props, "connections": []} for _, props in branch_rows],
            "direct_intent": True, "scope_verified": True, "network_scope": not bool(branch),
        }

    if field_name is None and (profile_question or branch) and branch:
        props = branch_rows[0][1]
        values = []
        hidden = {"_id", "physicalbranch", "branchcode", "geometry", "lat", "long"}
        for key, value in props.items():
            if _norm(key) in hidden or value in (None, ""):
                continue
            values.append({"label": str(key).replace("_", " "), "value": _pretty_value(str(key), value)})
        answer = f"I couldn't match that wording to one specific directory field. The branch directory lists the following information for {branch['name']}: " + "; ".join(f"{item['label']}: {item['value']}" for item in values[:24]) + "."
        return {
            "status": "ok", "answer": answer,
            "highlights": [{"title": branch["name"], "category": "Branch information", "details": values[:24]}],
            "evidence": [{"labels": [label], "properties": props, "connections": []}],
            "direct_intent": True, "scope_verified": True,
        }

    if field_name is None:
        return _not_found(
            "I couldn't find that information in the branch directory. The Q&A can use the recorded branch attributes, "
            "annual circulation, visits, workstation sessions, card registrations and program/event records. "
            "It cannot verify information that is not present in those source records."
        )

    actual_key = next((key for key in branch_rows[0][1] if _norm(key) == _norm(field_name)), None)
    if actual_key is None:
        alias_norms = {_norm(alias) for alias in DIRECTORY_FIELD_ALIASES.get(field_name, ())}
        actual_key = next((key for key in branch_rows[0][1] if _norm(key) in alias_norms), None)
    if actual_key is None and field_name == "TypeOfLibrary":
        actual_key = next((key for key in branch_rows[0][1] if _norm(key) == "servicetier"), None)
    if actual_key is None:
        return _not_found(f"The branch directory does not contain a {field_name} field.")

    values = [
        (item, props, _property_value(props, actual_key))
        for item, props in branch_rows
        if _property_value(props, actual_key) not in (None, "")
    ]
    if not values:
        return _not_found(f"The directory does not report {actual_key} for the selected branch scope.")

    known_boolean = _norm(actual_key) in {_norm(key) for key in DIRECTORY_BOOL_FIELDS} or _norm(actual_key) == "publicparking"
    boolean_tokens = {"1", "1.0", "0", "0.0", "true", "false", "yes", "no", "y", "n", "available", "notavailable", "offered", "notoffered"}
    observed_tokens = {re.sub(r"[^a-z0-9.]", "", str(value).casefold()) for _, _, value in values}
    dynamic_boolean = bool(observed_tokens) and observed_tokens <= boolean_tokens
    is_boolean = known_boolean or dynamic_boolean
    asks_count = bool(re.search(r"\b(how many|number of|count)\b", q))
    asks_branch_count = bool(re.search(r"\b(how many branches|number of branches|count of branches)\b", q))
    asks_total = bool(re.search(r"\b(total|in total|combined|altogether)\b", q))
    asks_per_branch = bool(re.search(r"\b(per branch|each branch|for every branch|branch by branch)\b", q))
    asks_branches = bool(re.search(r"\b(which|what|list|show)\b", q)) and ("branch" in q or "branches" in q)
    ranking = bool(re.search(r"\b(most|highest|largest|biggest|greatest|longest|oldest|earliest|newest|latest|smallest|lowest|least|fewest)\b", q))
    rank_ascending = bool(re.search(r"\b(oldest|earliest|smallest|lowest|least|fewest)\b", q))

    # A single selected/named branch always wins over a network-level phrase:
    # Branch Insights must never drift to a different branch's data.
    if branch:
        item, props, value = values[0] if values else (branch, branch_rows[0][1], None)
        if value is None:
            return _not_found(f"The directory does not report {actual_key} for {branch['name']}.")
        display = _pretty_value(actual_key, value)
        if _norm(actual_key) == "presentsiteyear":
            answer = f"The branch directory lists {display} as the present-site year for {branch['name']}. This identifies the current site, not necessarily the year the library service first began."
        elif _norm(actual_key) == "publicparking":
            answer = f"The directory lists {display} for public parking at {branch['name']}."
        else:
            answer = f"The directory lists {display} for {actual_key.replace('_', ' ').lower()} at {branch['name']}."
        return {
            "status": "ok", "answer": answer,
            "highlights": [{"title": branch["name"], "category": actual_key.replace("_", " "), "details": [{"label": actual_key.replace("_", " "), "value": display}]}],
            "evidence": [{"labels": [label], "properties": props, "connections": []}],
            "direct_intent": True, "scope_verified": True,
        }

    # Overview questions about branch rankings are evaluated across the entire
    # eligible physical-branch directory. Virtual/non-physical rows never enter.
    if ranking:
        numeric_values = [(item, props, number(value)) for item, props, value in values]
        numeric_values = [entry for entry in numeric_values if entry[2] is not None]
        if numeric_values:
            numeric_values.sort(key=lambda entry: entry[2], reverse=not rank_ascending)
            top_match = re.search(r"\btop\s+(\d{1,2})\b", q)
            limit = max(1, min(int(top_match.group(1)), 10)) if top_match else 1
            selected = numeric_values[:limit]
            unit = " sq ft" if _norm(actual_key) == "squarefootage" else " spaces" if _norm(actual_key) == "publicparking" else ""
            order_word = "lowest" if rank_ascending else "highest"
            if _norm(actual_key) == "presentsiteyear":
                order_word = "earliest"
            items = [
                {"label": entry[0]["name"], "value": f"{_display_number(entry[2])}{unit}"}
                for entry in selected
            ]
            answer = f"By the recorded {actual_key.replace('_', ' ').lower()} values, the {order_word}-ranked physical branch" + ("es" if len(selected) != 1 else "") + ": " + "; ".join(f"{entry['label']} ({entry['value']})" for entry in items) + "."
            if _norm(actual_key) == "presentsiteyear":
                answer += " PresentSiteYear is the year of the current site and does not establish when the library service first began."
            return {
                "status": "ok", "answer": answer,
                "highlights": [{"title": f"Branch ranking by {actual_key.replace('_', ' ').lower()}", "category": "Physical branches", "details": items}],
                "evidence": [{"labels": [label], "properties": entry[1], "connections": []} for entry in selected],
                "direct_intent": True, "scope_verified": True, "network_scope": True,
            }

    if is_boolean:
        positive = [
            (item, props, value) for item, props, value in values
            if _has_feature(actual_key, value)
        ]
        if _norm(actual_key) == "publicparking" and (asks_total or "spaces" in q):
            total_spaces = sum(max(number(value) or 0, 0) for _, _, value in values)
            answer = f"The branch directory lists {_display_number(total_spaces)} public parking spaces across {len(positive)} physical branches with parking reported."
            details = [{"label": "Total public parking spaces", "value": _display_number(total_spaces)}, {"label": "Branches with parking reported", "value": str(len(positive))}]
            selected_rows = positive
        elif asks_count:
            answer = f"{len(positive)} of {len(branch_rows)} physical branches have {actual_key.replace('_', ' ').lower()} recorded as available."
            details = [{"label": "Branches with feature", "value": str(len(positive))}, {"label": "Physical branches checked", "value": str(len(branch_rows))}]
            selected_rows = positive
        elif re.search(r"\bpercentage|percent|share of branches\b", q):
            percentage = (len(positive) / len(branch_rows) * 100) if branch_rows else 0
            answer = f"{percentage:.1f}% of physical branches ({len(positive)} of {len(branch_rows)}) have {actual_key.replace('_', ' ').lower()} recorded as available."
            details = [{"label": "Percentage", "value": f"{percentage:.1f}%"}, {"label": "Branches with feature", "value": str(len(positive))}, {"label": "Physical branches checked", "value": str(len(branch_rows))}]
            selected_rows = positive
        elif re.search(r"\ball\s+(?:physical\s+)?branches\b", q):
            all_have = len(positive) == len(branch_rows)
            answer = f"{'All' if all_have else 'Not all'} physical branches have {actual_key.replace('_', ' ').lower()} recorded as available ({len(positive)} of {len(branch_rows)})."
            details = [{"label": "Branches with feature", "value": str(len(positive))}, {"label": "Physical branches checked", "value": str(len(branch_rows))}]
            selected_rows = positive
        elif asks_branches or re.search(r"\b(offer|offers|provide|provides|have|has|with)\b", q):
            names = [item["name"] for item, _, _ in positive]
            answer = f"{len(names)} physical branches have {actual_key.replace('_', ' ').lower()} listed: {', '.join(names[:15])}"
            if len(names) > 15:
                answer += f", and {len(names) - 15} more"
            answer += "."
            details = [{"label": "Branch", "value": name} for name in names[:15]] or [{"label": "Branches", "value": "None listed"}]
            selected_rows = positive
        else:
            answer = f"The directory records {len(positive)} of {len(branch_rows)} physical branches with {actual_key.replace('_', ' ').lower()} available."
            details = [{"label": "Available", "value": str(len(positive))}, {"label": "Checked", "value": str(len(branch_rows))}]
            selected_rows = positive
        return {
            "status": "ok", "answer": answer,
            "highlights": [{"title": actual_key.replace("_", " "), "category": "Branch directory", "details": details}],
            "evidence": [{"labels": [label], "properties": props, "connections": []} for _, props, _ in selected_rows],
            "direct_intent": True, "scope_verified": True, "network_scope": True,
        }

    # Categorical fields can be summarized as distributions, for example
    # the most common service tier or the number of branches per ward.
    if not is_boolean and ranking and re.search(r"\b(most common|most frequent|largest group|majority)\b", q):
        frequencies: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
        for item, props, value in values:
            frequencies.setdefault(str(value).strip(), []).append((item, props))
        if frequencies:
            ordered = sorted(frequencies.items(), key=lambda entry: (-len(entry[1]), entry[0].casefold()))
            value, entries = ordered[0]
            details = [{"label": category, "value": str(len(items))} for category, items in ordered[:10]]
            answer = f"The most common {actual_key.replace('_', ' ').lower()} is {value}, recorded for {len(entries)} physical branches."
            if len(ordered) > 1:
                answer += " Counts by value: " + "; ".join(f"{item['label']}: {item['value']}" for item in details) + "."
            return {
                "status": "ok", "answer": answer,
                "highlights": [{"title": f"Most common {actual_key.replace('_', ' ').lower()}", "category": "Physical branches", "details": details}],
                "evidence": [{"labels": [label], "properties": props, "connections": []} for _, props in entries[:12]],
                "direct_intent": True, "scope_verified": True, "network_scope": True,
            }

    # For ward, neighbourhood, tier and other text fields, a value named in
    # the question is treated as a filter rather than returning unrelated rows.
    query_compact = _norm(question)
    matching_values = [entry for entry in values if _value_is_mentioned(actual_key, entry[2], query_compact)]
    if matching_values:
        selected_rows = matching_values
    elif ranking:
        selected_rows = values
    else:
        selected_rows = values

    if asks_count and asks_branch_count and not is_boolean:
        count = len(selected_rows)
        answer = f"{count} physical branches match that directory condition."
        details = [{"label": "Matching physical branches", "value": str(count)}]
        if selected_rows:
            details.extend({"label": item[0]["name"], "value": _pretty_value(actual_key, item[2])} for item in selected_rows[:10])
        return {
            "status": "ok", "answer": answer,
            "highlights": [{"title": f"Branch count by {actual_key.replace('_', ' ').lower()}", "category": "Physical branches", "details": details}],
            "evidence": [{"labels": [label], "properties": props, "connections": []} for _, props, _ in selected_rows[:12]],
            "direct_intent": True, "scope_verified": True, "network_scope": True,
        }

    if asks_count and not is_boolean and not asks_per_branch:
        numeric_values = [number(value) for _, _, value in selected_rows]
        numeric_values = [value for value in numeric_values if value is not None]
        if numeric_values:
            total = sum(numeric_values)
            unit = " sq ft" if _norm(actual_key) == "squarefootage" else " workstations" if _norm(actual_key) == "workstations" else ""
            answer = f"The physical-branch directory reports {_display_number(total)}{unit} across {len(numeric_values)} branches."
            details = [{"label": "Network total", "value": f"{_display_number(total)}{unit}"}, {"label": "Branches with values", "value": str(len(numeric_values))}]
            return {
                "status": "ok", "answer": answer,
                "highlights": [{"title": actual_key.replace("_", " "), "category": "Physical branch total", "details": details}],
                "evidence": [{"labels": [label], "properties": props, "connections": []} for _, props, _ in selected_rows[:12]],
                "direct_intent": True, "scope_verified": True, "network_scope": True,
            }
    if asks_count:
        answer = f"{len(selected_rows)} physical branches have a reported {actual_key.replace('_', ' ').lower()} value in this result set."
    else:
        answer = f"Reported {actual_key.replace('_', ' ').lower()} by physical branch: " + "; ".join(
            f"{item['name']}: {_pretty_value(actual_key, value)}" for item, _, value in selected_rows[:12]
        )
        if len(selected_rows) > 12:
            answer += f"; and {len(selected_rows) - 12} more branches"
        answer += "."
    details = [{"label": item["name"], "value": _pretty_value(actual_key, value)} for item, _, value in selected_rows[:12]]
    return {
        "status": "ok", "answer": answer,
        "highlights": [{"title": actual_key.replace("_", " "), "category": "Branch directory", "details": details}],
        "evidence": [{"labels": [label], "properties": props, "connections": []} for _, props, _ in selected_rows[:12]],
        "direct_intent": True, "scope_verified": True, "network_scope": True,
    }


def _answer_metric_trend(connection, schema, metric: str, branch: dict[str, Any] | None) -> dict[str, Any]:
    found = _label_for_metric(schema, metric)
    if not found:
        return _not_found(f"The Relate graph does not contain annual {METRIC_SPECS[metric]['noun']} records.")
    label, properties = found
    branch_key = _first_key(properties, BRANCH_CODE_ALIASES)
    year_key = _first_key(properties, YEAR_ALIASES)
    value_key = _first_key(properties, METRIC_SPECS[metric]["value_aliases"])
    rows = _nodes(connection, label, properties, branch_code=branch["code"] if branch else None, limit=5000)
    eligible = _eligible_codes()
    by_year: dict[str, float] = {}
    evidence_by_year: dict[str, dict[str, Any]] = {}
    for props in rows:
        if not is_physical_branch(props):
            continue
        normalized = _normalised_properties(props)
        code = str(next((normalized.get(alias) for alias in BRANCH_CODE_ALIASES if normalized.get(alias) not in (None, "")), "")).strip()
        item = eligible.get(code.casefold())
        if not item or (branch and item["code"].casefold() != branch["code"].casefold()):
            continue
        year = str(next((normalized.get(alias) for alias in YEAR_ALIASES if normalized.get(alias) not in (None, "")), "")).strip()
        value = number(props.get(value_key))
        if not year or value is None:
            continue
        by_year[year] = by_year.get(year, 0.0) + float(value)
        evidence_by_year[year] = props
    if not by_year:
        target = f" for {branch['name']}" if branch else " across physical branches"
        return _not_found(f"No annual {METRIC_SPECS[metric]['noun']} history was found{target}.")
    years = sorted(by_year, key=lambda item: (int(item) if item.isdigit() else 0, item))
    series = [{"label": year, "value": _display_number(by_year[year])} for year in years]
    scope_text = branch["name"] if branch else "Toronto Public Library's physical branch network"
    answer = f"Annual {METRIC_SPECS[metric]['noun']} for {scope_text}: " + "; ".join(f"{year}: {_display_number(by_year[year])}" for year in years) + "."
    return {
        "status": "ok", "answer": answer,
        "highlights": [{"title": METRICS_LABELS[metric], "category": "Annual trend", "details": series}],
        "evidence": [{"labels": [label], "properties": evidence_by_year[year], "connections": []} for year in years],
        "direct_intent": True, "scope_verified": bool(branch), "network_scope": not bool(branch),
    }


def _answer_metric_ranking(connection, schema, metric: str, year: str | None, question: str = "") -> dict[str, Any]:
    """Rank annual branch observations across the requested reporting period.

    If a year is supplied, rank within that year. If the question explicitly
    requests the latest/most recent year, use the latest year. Otherwise a
    yearless question compares all available branch-year observations and
    reports the highest (or lowest) annual record with its reporting year.
    """
    found = _label_for_metric(schema, metric)
    if not found:
        return _not_found(f"The Relate graph does not contain annual {METRIC_SPECS[metric]['noun']} records.")
    label, properties = found
    value_key = _first_key(properties, METRIC_SPECS[metric]["value_aliases"])
    rows = _nodes(connection, label, properties, year=year, limit=5000)
    eligible = _eligible_codes()
    records_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    actual_years: set[str] = set()
    for props in rows:
        if not is_physical_branch(props):
            continue
        normalized = _normalised_properties(props)
        code = str(next((normalized.get(alias) for alias in BRANCH_CODE_ALIASES if normalized.get(alias) not in (None, "")), "")).strip()
        branch_item = eligible.get(code.casefold())
        value = number(props.get(value_key)) if value_key else None
        raw_year = next((normalized.get(alias) for alias in YEAR_ALIASES if normalized.get(alias) not in (None, "")), None)
        year_match = re.search(r"(?:19|20)\d{2}", str(raw_year or ""))
        record_year = year_match.group(0) if year_match else ""
        if not branch_item or value is None or not record_year:
            continue
        if year and record_year != str(year):
            continue
        actual_years.add(record_year)
        records_by_key[(branch_item["code"], record_year)] = {
            "code": branch_item["code"],
            "name": branch_item["name"],
            "year": record_year,
            "value": float(value),
            "properties": props,
        }
    if not records_by_key:
        return _not_found(f"No annual {METRIC_SPECS[metric]['noun']} values were found for {year or 'the available reporting years'}.")

    q = _normalise_question(question)
    latest_requested = bool(re.search(r"\b(latest|most recent|last reported|current year)\b", q))
    if year:
        chosen_year = str(year)
        period_records = [item for item in records_by_key.values() if item["year"] == chosen_year]
    elif latest_requested:
        chosen_year = max(actual_years, key=int)
        period_records = [item for item in records_by_key.values() if item["year"] == chosen_year]
    else:
        chosen_year = None
        period_records = list(records_by_key.values())

    lowest = bool(re.search(r"\b(lowest|least|fewest|smallest)\b", q))
    period_records.sort(key=lambda item: (item["value"], int(item["year"]), item["name"].casefold()), reverse=not lowest)
    top_match = re.search(r"\btop\s+(\d{1,2})\b", q)
    limit = max(1, min(int(top_match.group(1)), 10)) if top_match else 1
    selected = period_records[:limit]
    direction = "lowest" if lowest else "highest"
    noun = METRIC_SPECS[metric]["noun"]

    # Compute one branch leader for every reporting year so the user can see
    # how the answer changes over time, even when the overall maximum is in an
    # earlier year than the latest dataset year.
    yearly_leaders = []
    if not year and not latest_requested:
        for reporting_year in sorted(actual_years, key=int):
            year_rows = [item for item in records_by_key.values() if item["year"] == reporting_year]
            year_rows.sort(key=lambda item: (item["value"], item["name"].casefold()), reverse=not lowest)
            if year_rows:
                yearly_leaders.append(year_rows[0])

    if chosen_year:
        lead = selected[0]
        answer = (
            f"In {chosen_year}, the {direction} annual {noun} among physical branches was "
            f"{lead['name']} ({_display_number(lead['value'])})."
        )
        details = [{"label": "Branch", "value": lead["name"]},
                   {"label": "Annual value", "value": _display_number(lead["value"])},
                   {"label": "Reporting year", "value": chosen_year}]
    else:
        lead = selected[0]
        answer = (
            f"Across all available reporting years, the {direction} annual {noun} was "
            f"{lead['name']} ({_display_number(lead['value'])}) in {lead['year']}."
        )
        if yearly_leaders:
            annual_summary = "; ".join(
                f"{item['year']}: {item['name']} ({_display_number(item['value'])})"
                for item in yearly_leaders
            )
            answer += f" {direction.capitalize()} branch by reporting year: {annual_summary}."
        details = [{"label": "Branch with highest annual record" if not lowest else "Branch with lowest annual record", "value": lead["name"]},
                   {"label": "Annual value", "value": _display_number(lead["value"])},
                   {"label": "Reporting year", "value": lead["year"]}]
        details.extend({"label": f"{item['year']} annual leader", "value": f"{item['name']} · {_display_number(item['value'])}"} for item in yearly_leaders)

    if limit > 1:
        answer += " Ranked records: " + "; ".join(
            f"{item['name']} ({_display_number(item['value'])}, {item['year']})" for item in selected
        ) + "."
        details.extend({"label": f"Rank {index + 1}", "value": f"{item['name']} · {_display_number(item['value'])} · {item['year']}"} for index, item in enumerate(selected))

    return {
        "status": "ok",
        "answer": answer,
        "highlights": [{
            "title": f"{direction.capitalize()} {METRICS_LABELS[metric]}",
            "category": chosen_year or "All available reporting years",
            "details": details,
        }],
        "evidence": [{"labels": [label], "properties": item["properties"], "connections": []} for item in (yearly_leaders or selected)],
        "direct_intent": True,
        "scope_verified": True,
        "network_scope": True,
    }




def _answer_events(question: str, branch: dict[str, Any] | None) -> dict[str, Any]:
    """Answer program/event questions from the discovered Relate event nodes."""
    try:
        from app.services.relate_events import graph_event_records
        records = graph_event_records() or []
    except Exception:
        records = []
    if not records:
        return _not_found("No program or event records are currently available in the Relate graph.")
    eligible = _eligible_codes()
    candidates = []
    for event in records:
        code = str(event.get("branch_code") or "").strip()
        if code.casefold() not in eligible:
            continue
        if branch and code.casefold() != branch["code"].casefold():
            continue
        candidates.append(event)
    if not candidates:
        target = f" for {branch['name']}" if branch else " across physical branches"
        return _not_found(f"No program or event records were found{target}.")

    q = _normalise_question(question)
    terms = [token for token in q.split() if token not in QUESTION_STOPWORDS and len(token) > 2]
    branch_tokens = set(_normalise_question(branch["name"]).split()) if branch else set()
    terms = [term for term in terms if term not in branch_tokens and term not in {"program", "programs", "event", "events", "class", "classes", "upcoming", "future", "past"}]
    scored = []
    for event in candidates:
        searchable = " ".join(str(event.get(key) or "") for key in ("title", "description", "types", "audiences", "languages")).casefold()
        score = sum(1 for term in terms if term in searchable)
        scored.append((score, event))
    if terms and any(score for score, _ in scored):
        scored = [entry for entry in scored if entry[0] > 0]
    if re.search(r"\b(upcoming|future|next)\b", q):
        today = datetime.now(ZoneInfo("America/Toronto")).date().isoformat()
        scored = [entry for entry in scored if str(entry[1].get("start") or "")[:10] >= today]
    if re.search(r"\b(past|previous|last)\b", q):
        today = datetime.now(ZoneInfo("America/Toronto")).date().isoformat()
        scored = [entry for entry in scored if str(entry[1].get("start") or "")[:10] < today]
    scored.sort(key=lambda entry: (str(entry[1].get("start") or "9999"), str(entry[1].get("title") or "").casefold()))
    selected = [event for _, event in scored[:10]]
    if not selected:
        return _not_found("No program or event records matched that question in the selected branch scope.")
    branch_names = {item["code"].casefold(): item["name"] for item in _eligible_codes().values()}
    details = []
    for event in selected:
        date_text = str(event.get("start") or "Date not supplied")
        detail = f"{date_text} · {event.get('title') or 'Untitled event'}"
        if event.get("types"):
            detail += f" · {event['types']}"
        if event.get("audiences"):
            detail += f" · {event['audiences']}"
        if not branch and event.get("branch_code"):
            detail += f" · {branch_names.get(str(event['branch_code']).casefold(), event['branch_code'])}"
        details.append({"label": f"Program {len(details) + 1}", "value": detail})
    scope = branch["name"] if branch else "physical branches across the network"
    answer = f"I found {len(selected)} matching program/event record{'s' if len(selected) != 1 else ''} for {scope}: " + "; ".join(item["value"] for item in details) + "."
    return {
        "status": "ok", "answer": answer,
        "highlights": [{"title": "Programs and events", "category": branch["name"] if branch else "Network-wide", "details": details}],
        "evidence": [], "direct_intent": True, "scope_verified": bool(branch), "network_scope": not bool(branch),
    }


def _latest_metric_year(connection, schema: dict[str, dict[str, str]], metric: str, branch: dict[str, Any] | None = None) -> str | None:
    found = _label_for_metric(schema, metric)
    if not found:
        return None
    label, properties = found
    rows = _nodes(connection, label, properties, branch_code=branch["code"] if branch else None, limit=5000)
    eligible = _eligible_codes()
    years = set()
    for props in rows:
        if not is_physical_branch(props):
            continue
        normalized = _normalised_properties(props)
        code = str(next((normalized.get(alias) for alias in BRANCH_CODE_ALIASES if normalized.get(alias) not in (None, "")), "")).strip()
        item = eligible.get(code.casefold())
        if not item or (branch and item["code"].casefold() != branch["code"].casefold()):
            continue
        value = next((normalized.get(alias) for alias in YEAR_ALIASES if normalized.get(alias) not in (None, "")), None)
        if value is not None and re.fullmatch(r"(?:19|20)\d{2}(?:\.0+)?", str(value).strip()):
            years.add(str(int(float(value))))
    return max(years, key=int) if years else None


def ask(question: str, branch_code: str | None = None) -> dict[str, Any]:
    """Answer branch questions from all fields represented in the Relate graph.

    A supplied branch code is authoritative and limits every lookup to that
    branch. Without one, a branch name in the question narrows the query;
    otherwise the answer uses the full eligible physical-branch directory.
    """
    question = str(question or "").strip()
    if len(question) < 2:
        return _not_found("Enter a question about a Toronto Public Library branch or its reported activity.")
    branches = branch_records()
    selected_branch = None
    if branch_code:
        selected_branch = next((item for item in branches if item["code"].casefold() == branch_code.casefold()), None)
        if selected_branch is None:
            return _not_found("The selected branch is not in the physical branch directory.")
    else:
        selected_branch = _branch_from_question(question, branches)

    metric = _metric_intent(question)
    year = _year_intent(question)
    q = _normalise_question(question)
    oldest_branch_question = bool(
        re.search(r"\b(?:oldest|earliest)\b.{0,70}\b(?:branch(?:es)?|librar(?:y|ies))\b", q)
        or re.search(r"\b(?:branch(?:es)?|librar(?:y|ies))\b.{0,70}\b(?:oldest|earliest)\b", q)
        or re.search(r"\bwhich\s+(?:branch|library)\b.{0,70}\b(?:opened|started|began|first)\b", q)
        or re.search(r"\b(?:branch|library)\b.{0,70}\b(?:been around|around the longest)\b", q)
    )
    opening_question = bool(
        re.search(r"\bwhen\s+(?:was|did)\b.{0,80}\b(?:first\s+)?(?:open(?:ed)?|creat(?:ed|ion)|establish(?:ed)?|found(?:ed)?|start(?:ed)?|begin|built)\b", q)
        or re.search(r"\bwhat\s+year\b.{0,80}\b(?:open(?:ed)?|creat(?:ed|ion)|establish(?:ed)?|found(?:ed)?|start(?:ed)?|built)\b", q)
        or re.search(r"\b(?:opening|present site|creation|establishment|founding)\s+year\b", q)
        or re.search(r"\bfirst\s+opened\b|\bestablished\b|\bfounded\b", q)
    )
    asks_for_events = bool(re.search(r"\b(programs?|events?|classes|workshops|storytimes?)\b", q))
    asks_for_trend = bool(re.search(r"\b(trend|over time|year by year|each year|annually|changed|change over)\b", q))
    asks_for_ranking = bool(re.search(r"\b(which branch|highest|lowest|most|least|largest|biggest|greatest|smallest|fewest|top\s+\d+)\b", q))
    asks_open_status = bool(
        re.search(r"\b(is|are)\b.{0,35}\b(open now|open today|currently open)\b", q)
        or re.search(r"\b(is it open|are they open|currently open)\b", q)
    )
    if asks_open_status:
        return _not_found("The directory contains posted weekly hours, but it does not provide live opening status or holiday-closure information.")

    connection = _open_connection()
    try:
        schema = _cached_schema(connection)

        # Traverse actual Relate edges for ward, neighbourhood, service and peer questions.
        from app.services.graph_enhancements import answer_connected_question
        connected_answer = answer_connected_question(connection, schema, question, selected_branch)
        if connected_answer is not None:
            return connected_answer

        if oldest_branch_question:
            # A selected branch panel is never allowed to widen to a network
            # comparison. Its year is reported as a current-site year.
            if selected_branch:
                return _answer_branch_detail(connection, schema, selected_branch, "opened")
            return _answer_oldest_branch(connection, schema)

        if opening_question and selected_branch:
            return _answer_branch_detail(connection, schema, selected_branch, "opened")

        if asks_for_events:
            return _answer_events(question, selected_branch)

        if metric:
            if asks_for_trend:
                return _answer_metric_trend(connection, schema, metric, selected_branch)
            if asks_for_ranking and not selected_branch:
                return _answer_metric_ranking(connection, schema, metric, year, question)
            if not year:
                year = _latest_metric_year(connection, schema, metric, selected_branch)
                if not year:
                    return _not_found(f"No annual {METRIC_SPECS[metric]['noun']} years are available in the graph for this scope.")
            return _answer_metric(connection, schema, metric, year, selected_branch)

        # Generic directory lookup covers every imported branch property,
        # including hours, parking, washrooms, location, ward, tier and newer
        # fields that can be named directly in the question.
        return _answer_directory_question(connection, schema, question, selected_branch)
    except RelateUnavailable:
        raise
    except Exception as exc:
        raise RelateUnavailable(f"The graph question could not be answered ({type(exc).__name__}).") from exc
    finally:
        connection.close()
