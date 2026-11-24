"""Relate graph exploration, connected-context answers and activity intensity.

All graph content is derived from the CSV snapshots already shipped with LibraryTO.
No external data provider is queried by this module.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import re
from typing import Any

from app.config import RELATE_FILE
from app.services.data_store import branch_records

BRANCH_LABEL_FALLBACK = "BranchGeneralInformation"
BRANCH_EDGE_TYPES = {
    "HAS_CIRCULATION_RECORD", "HAS_VISITS_RECORD", "HAS_WORKSTATION_RECORD",
    "HAS_REGISTRATION_RECORD", "HOSTS_EVENT", "IN_NEIGHBOURHOOD",
    "IN_WARD", "OFFERS_SERVICE", "HAS_FACILITY",
}
NEIGHBOURHOOD_LABEL = "LibraryNeighbourhood"
WARD_LABEL = "LibraryWard"
SERVICE_LABEL = "LibraryService"
FACILITY_LABEL = "LibraryFacility"

RELATIONSHIP_LABELS = {
    "HAS_CIRCULATION_RECORD": "Annual circulation records",
    "HAS_VISITS_RECORD": "Annual visit records",
    "HAS_WORKSTATION_RECORD": "Annual workstation records",
    "HAS_REGISTRATION_RECORD": "Annual card registration records",
    "HOSTS_EVENT": "Programs and events",
    "IN_NEIGHBOURHOOD": "Neighbourhood membership",
    "IN_WARD": "Ward membership",
    "OFFERS_SERVICE": "Reported services",
    "HAS_FACILITY": "Reported facilities",
    "HAS_GEOGRAPHY_RECORD": "Neighbourhood geography records",
}

SERVICE_ALIASES = {
    "kidsstop": ("kids stop", "kidsstop", "children's stop"),
    "leadingreading": ("leading reading", "leadingreading"),
    "clc": ("community led services", "community-led services", "clc"),
    "dih": ("digital innovation hub", "innovation hub", "dih"),
    "teencouncil": ("teen council", "teencouncil"),
    "youthhub": ("youth hub", "youthhub"),
    "adultliteracyprogram": ("adult literacy program", "adult literacy", "adultliteracyprogram"),
    "publicwashroom": ("public washroom", "washroom", "restroom", "public bathroom", "public toilet"),
}
SERVICE_NAMES = {
    "kidsstop": "Kids Stop",
    "leadingreading": "Leading Reading",
    "clc": "Community-led services",
    "dih": "Digital Innovation Hub",
    "teencouncil": "Teen Council",
    "youthhub": "Youth Hub",
    "adultliteracyprogram": "Adult Literacy Program",
    "publicwashroom": "Public washroom",
}
METRIC_CONFIG = {
    "circulation": ("HAS_CIRCULATION_RECORD", "CirculationAnnualByBranch", ("Circulation", "TotalCirculation", "Value"), "circulation"),
    "visits": ("HAS_VISITS_RECORD", "VisitsAnnualByBranch", ("Visits", "TotalVisits", "Value"), "visits"),
    "workstations": ("HAS_WORKSTATION_RECORD", "WorkstationUsageAnnualByBranch", ("Sessions", "WorkstationSessions", "WorkstationUsage", "Value"), "sessions"),
    "registrations": ("HAS_REGISTRATION_RECORD", "CardRegistrationsAnnualByBranch", ("Registrations", "CardRegistrations", "NewRegistrations", "Value"), "registrations"),
}


class GraphUnavailable(RuntimeError):
    """Raised when the committed Relate store cannot be opened."""


def _quote(identifier: str) -> str:
    if not identifier or any(ord(ch) < 32 for ch in identifier):
        raise ValueError("Invalid Relate identifier")
    return "`" + identifier.replace("`", "``") + "`"


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def _humanize_label(value: str) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(value or ""))
    text = re.sub(r"[_-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip().title()


def _rows(cursor) -> list[dict[str, Any]]:
    return cursor.fetchall()


def open_graph(read_only: bool = True):
    if not RELATE_FILE.is_file():
        raise GraphUnavailable(f"The Relate store {RELATE_FILE.name} is missing.")
    try:
        import relate
        return relate.connect(database=str(RELATE_FILE), read_only=read_only)
    except Exception as exc:
        raise GraphUnavailable(f"The Relate store could not be opened ({type(exc).__name__}).") from exc


def _schema(connection) -> tuple[dict[str, dict[str, str]], list[str]]:
    properties: dict[str, dict[str, str]] = defaultdict(dict)
    for row in _rows(connection.execute(
        "CALL db.schema.nodeTypeProperties() YIELD nodeLabels, propertyName "
        "RETURN nodeLabels, propertyName LIMIT 2000"
    )):
        labels = row.get("nodeLabels") or []
        if isinstance(labels, str):
            labels = [labels]
        key = str(row.get("propertyName") or "")
        if not key:
            continue
        for label in labels:
            properties[str(label)][_norm(key)] = key
    types = sorted({str(row.get("relationshipType")) for row in _rows(
        connection.execute("CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType")
    ) if row.get("relationshipType")})
    return dict(properties), types


def _branch_label(schema: dict[str, dict[str, str]]) -> tuple[str, dict[str, str]]:
    # Prefer the branch directory label. Annual observation labels can also
    # contain BranchCode and BranchName, so generic schema discovery is unsafe.
    preferred = schema.get(BRANCH_LABEL_FALLBACK)
    if preferred and "branchcode" in preferred and "physicalbranch" in preferred and ("branchname" in preferred or "name" in preferred):
        return BRANCH_LABEL_FALLBACK, preferred
    for label, props in schema.items():
        if "branchcode" in props and "physicalbranch" in props and ("branchname" in props or "name" in props):
            return label, props
    raise GraphUnavailable("The Relate store does not contain a physical branch directory with a PhysicalBranch field.")


def _physical_branch_clause(alias: str, branch_props: dict[str, str]) -> str:
    """Return the strict source flag predicate required for branch graph views."""
    physical_property = branch_props.get("physicalbranch")
    if not physical_property:
        raise GraphUnavailable("The branch directory is missing PhysicalBranch; only physical branches can be inspected safely.")
    return f"toString({alias}.{_quote(physical_property)}) = '1'"


def _safe_properties(properties: Any) -> dict[str, Any]:
    if not isinstance(properties, dict):
        return {}
    hidden = {"_libraryto_source_key", "_libraryto_source_file"}
    return {str(k): v for k, v in properties.items() if _norm(k) not in hidden and not str(k).startswith("_") and v not in (None, "")}


def _node_summary(labels: list[str], props: dict[str, Any]) -> str:
    values = {_norm(k): v for k, v in props.items()}
    label = " ".join(labels)
    if "LibraryService" in labels:
        return str(values.get("servicename") or values.get("name") or "Service")
    if "LibraryFacility" in labels:
        return str(values.get("facilityname") or values.get("name") or "Facility")
    if "LibraryNeighbourhood" in labels:
        name = values.get("name") or "Neighbourhood"
        number = values.get("neighbourhoodno")
        return f"{name} (No. {number})" if number else str(name)
    if "LibraryWard" in labels:
        name = values.get("name") or "Ward"
        number = values.get("wardno")
        return f"{name} (Ward {number})" if number else str(name)
    if any("circulation" in _norm(v) for v in labels):
        metric_value = next((values.get(key) for key in ("circulation", "totalcirculation", "value") if values.get(key) is not None), "value not supplied")
        return f"Circulation · {values.get('year', 'year not supplied')} · {metric_value}"
    if any("visits" in _norm(v) for v in labels):
        metric_value = next((values.get(key) for key in ("visits", "totalvisits", "value") if values.get(key) is not None), "value not supplied")
        return f"Visits · {values.get('year', 'year not supplied')} · {metric_value}"
    if any("workstation" in _norm(v) for v in labels):
        metric_value = next((values.get(key) for key in ("sessions", "workstationsessions", "workstationusage", "value") if values.get(key) is not None), "value not supplied")
        return f"Workstation sessions · {values.get('year', 'year not supplied')} · {metric_value}"
    if any("registration" in _norm(v) for v in labels):
        metric_value = next((values.get(key) for key in ("registrations", "cardregistrations", "newregistrations", "value") if values.get(key) is not None), "value not supplied")
        return f"Registrations · {values.get('year', 'year not supplied')} · {metric_value}"
    title = next((values.get(k) for k in ("title", "eventtitle", "eventname", "programname", "name") if values.get(k)), None)
    if title:
        when = values.get("startdatelocal") or values.get("startdate") or values.get("startdatetime") or ""
        return f"{title} · {when}" if when else str(title)
    return str(values.get("name") or values.get("branchname") or label or "Connected record")


def _peer_branches_in_shared_areas(connection, branch_label: str, branch_props: dict[str, str], branch_code: str, schema: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    """Find other branches connected to the selected branch through its ward or neighbourhood."""
    code_property = branch_props.get("branchcode")
    if not code_property:
        return []
    physical_anchor = _physical_branch_clause("anchor", branch_props)
    physical_peer = _physical_branch_clause("peer", branch_props)
    contexts = (
        ("neighbourhood", "IN_NEIGHBOURHOOD", NEIGHBOURHOOD_LABEL),
        ("ward", "IN_WARD", WARD_LABEL),
    )
    peers: dict[str, dict[str, Any]] = {}
    service_available = SERVICE_LABEL in schema
    for context_type, relationship, area_label in contexts:
        if area_label not in schema:
            continue
        service_match = f"OPTIONAL MATCH (peer)-[:{_quote('OFFERS_SERVICE')}]->(service:{_quote(SERVICE_LABEL)})" if service_available else ""
        service_return = "collect(properties(service)) AS service_properties" if service_available else "[] AS service_properties"
        query = (
            f"MATCH (anchor:{_quote(branch_label)})-[:{_quote(relationship)}]->(area:{_quote(area_label)})"
            f"<-[:{_quote(relationship)}]-(peer:{_quote(branch_label)}) "
            f"WHERE {physical_anchor} AND {physical_peer} "
            f"AND toLower(toString(anchor.{_quote(code_property)})) = $branch_code "
            f"AND toLower(toString(peer.{_quote(code_property)})) <> $branch_code "
            f"{service_match} "
            f"RETURN properties(area) AS area_properties, properties(peer) AS peer_properties, {service_return}"
        )
        try:
            rows = _rows(connection.execute(query, {"branch_code": branch_code.casefold()}))
        except Exception:
            # Older stores may not yet have the explicit peer-path relationships.
            continue
        for row in rows:
            branch_data = row.get("peer_properties") or {}
            peer_code = _branch_value(branch_data, ("BranchCode", "Code"))
            peer_name = _branch_value(branch_data, ("BranchName", "Name")) or peer_code
            if not peer_code:
                continue
            area_data = row.get("area_properties") or {}
            area_name = _branch_value(area_data, ("name", "NeighbourhoodName", "WardName"))
            area_number = _branch_value(area_data, ("neighbourhood_no", "ward_no"))
            if context_type == "ward":
                context_name = f"{area_name} (Ward {area_number})" if area_name and area_number else area_name or (f"Ward {area_number}" if area_number else "Ward not named")
            else:
                context_name = f"{area_name} (No. {area_number})" if area_name and area_number else area_name or (f"Neighbourhood {area_number}" if area_number else "Neighbourhood not named")
            key = peer_code.casefold()
            peer = peers.setdefault(key, {"branch_code": peer_code, "branch_name": peer_name, "contexts": [], "services": []})
            context = {"context_type": context_type, "context_name": context_name}
            if context not in peer["contexts"]:
                peer["contexts"].append(context)
            service_names = set(peer["services"])
            for props in row.get("service_properties") or []:
                if not isinstance(props, dict):
                    continue
                name = _branch_value(props, ("service_name", "facility_name", "name"))
                if name:
                    service_names.add(name)
            peer["services"] = sorted(service_names, key=str.casefold)
    return sorted(peers.values(), key=lambda item: item["branch_name"].casefold())


def _graph_insights(
    connection,
    branch_label: str,
    branch_props: dict[str, str],
    schema: dict[str, dict[str, str]],
    physical_branch_count: int,
) -> dict[str, Any]:
    """Calculate graph-specific topology insights for physical branch nodes only."""
    physical_b = _physical_branch_clause("b", branch_props)
    code_property = branch_props.get("branchcode")
    name_property = branch_props.get("branchname") or branch_props.get("name")

    physical_rows = _rows(connection.execute(
        f"MATCH (b:{_quote(branch_label)}) WHERE {physical_b} RETURN count(b) AS count"
    ))
    physical_graph_nodes = int((physical_rows[0].get("count") or 0) if physical_rows else 0)

    connected_rows = _rows(connection.execute(
        f"MATCH (b:{_quote(branch_label)})-[r]->() WHERE {physical_b} "
        "RETURN count(DISTINCT b) AS branches, count(r) AS relationships"
    ))
    connected = connected_rows[0] if connected_rows else {}
    connected_branches = int(connected.get("branches") or 0)
    physical_relationships = int(connected.get("relationships") or 0)

    top_branches = []
    if code_property and name_property:
        rows = _rows(connection.execute(
            f"MATCH (b:{_quote(branch_label)})-[r]->() WHERE {physical_b} "
            f"RETURN b.{_quote(code_property)} AS code, b.{_quote(name_property)} AS name, "
            "count(r) AS connections ORDER BY connections DESC LIMIT 8"
        ))
        top_branches = [
            {"code": str(row.get("code") or ""), "name": str(row.get("name") or row.get("code") or "Unknown branch"),
             "connections": int(row.get("connections") or 0)}
            for row in rows if row.get("code") is not None
        ]

    coverage = []
    for relationship_type in sorted(BRANCH_EDGE_TYPES):
        if relationship_type not in {
            "IN_NEIGHBOURHOOD", "IN_WARD", "OFFERS_SERVICE", "HAS_FACILITY",
            "HAS_CIRCULATION_RECORD", "HAS_VISITS_RECORD", "HAS_WORKSTATION_RECORD",
            "HAS_REGISTRATION_RECORD", "HOSTS_EVENT",
        }:
            continue
        try:
            rows = _rows(connection.execute(
                f"MATCH (b:{_quote(branch_label)})-[:{_quote(relationship_type)}]->() "
                f"WHERE {physical_b} RETURN count(DISTINCT b) AS count"
            ))
            branch_coverage = int((rows[0].get("count") or 0) if rows else 0)
        except Exception:
            continue
        coverage.append({
            "type": relationship_type,
            "label": RELATIONSHIP_LABELS.get(relationship_type, relationship_type.replace("_", " ").title()),
            "branches": branch_coverage,
            "percent": round(branch_coverage / physical_graph_nodes * 100, 1) if physical_graph_nodes else 0.0,
        })
    coverage.sort(key=lambda item: (-item["branches"], item["label"].casefold()))

    area_hubs: dict[str, list[dict[str, Any]]] = {"neighbourhoods": [], "wards": []}
    for key, area_label, relationship_type, number_aliases in (
        ("neighbourhoods", NEIGHBOURHOOD_LABEL, "IN_NEIGHBOURHOOD", ("neighbourhood_no", "nbhdno")),
        ("wards", WARD_LABEL, "IN_WARD", ("ward_no", "wardno")),
    ):
        if area_label not in schema:
            continue
        try:
            rows = _rows(connection.execute(
                f"MATCH (b:{_quote(branch_label)})-[:{_quote(relationship_type)}]->(a:{_quote(area_label)}) "
                f"WHERE {physical_b} RETURN properties(a) AS properties, count(DISTINCT b) AS branches "
                "ORDER BY branches DESC LIMIT 8"
            ))
        except Exception:
            continue
        for row in rows:
            properties = row.get("properties") or {}
            name = _branch_value(properties, ("name", "NeighbourhoodName", "WardName"))
            number_value = _branch_value(properties, number_aliases)
            if key == "wards":
                title = f"{name} (Ward {number_value})" if name and number_value else name or (f"Ward {number_value}" if number_value else "Unlabelled ward")
            else:
                title = f"{name} (No. {number_value})" if name and number_value else name or (f"Neighbourhood {number_value}" if number_value else "Unlabelled neighbourhood")
            area_hubs[key].append({"name": title, "branches": int(row.get("branches") or 0)})

    return {
        "physical_branches_in_directory": physical_branch_count,
        "physical_branch_nodes": physical_graph_nodes,
        "connected_physical_branches": connected_branches,
        "unconnected_physical_branches": max(0, physical_graph_nodes - connected_branches),
        "physical_branch_relationships": physical_relationships,
        "average_relationships_per_physical_branch": round(physical_relationships / physical_graph_nodes, 2) if physical_graph_nodes else 0,
        "top_connected_branches": top_branches,
        "relationship_coverage": coverage,
        "area_hubs": area_hubs,
    }


def explorer_snapshot(branch_codes: list[str] | None = None) -> dict[str, Any]:
    """Return graph structure, physical-branch-only topology insights and selected branch paths."""
    connection = open_graph(read_only=True)
    try:
        schema, relationship_types = _schema(connection)
        branch_label, branch_props = _branch_label(schema)
        physical_clause = _physical_branch_clause("n", branch_props)
        node_counts = []
        for label in sorted(schema):
            where = f" WHERE {physical_clause}" if label == branch_label else ""
            result = _rows(connection.execute(f"MATCH (n:{_quote(label)}){where} RETURN count(n) AS count"))
            row = result[0] if result else {}
            node_counts.append({
                "label": label,
                "display_label": _humanize_label(label),
                "count": int((row or {}).get("count") or 0),
                "properties": sorted(
                    (key for key in schema.get(label, {}).values()
                     if key and not str(key).startswith("_")),
                    key=str.casefold,
                ),
            })

        relationship_counts = []
        for rel_type in relationship_types:
            if rel_type in BRANCH_EDGE_TYPES:
                query = (
                    f"MATCH (b:{_quote(branch_label)})-[r:{_quote(rel_type)}]->() "
                    f"WHERE {_physical_branch_clause('b', branch_props)} RETURN count(r) AS count"
                )
            else:
                query = f"MATCH ()-[r:{_quote(rel_type)}]->() RETURN count(r) AS count"
            result = _rows(connection.execute(query))
            row = result[0] if result else {}
            relationship_counts.append({
                "type": rel_type,
                "label": RELATIONSHIP_LABELS.get(rel_type, rel_type.replace("_", " ").title()),
                "count": int((row or {}).get("count") or 0),
            })

        eligible = {b["code"].casefold(): b for b in branch_records()}
        selected = []
        physical_b = _physical_branch_clause("b", branch_props)
        physical_peer = _physical_branch_clause("peer", branch_props)
        for code in (branch_codes or [])[:5]:
            branch = eligible.get(str(code).casefold())
            if not branch:
                continue
            branch_query = (
                f"MATCH (b:{_quote(branch_label)}) "
                f"WHERE {physical_b} AND toLower(toString(b.{_quote(branch_props['branchcode'])})) = $branch_code "
                "RETURN properties(b) AS properties LIMIT 1"
            )
            branch_rows = _rows(connection.execute(branch_query, {"branch_code": branch["code"].casefold()}))
            branch_properties = _safe_properties(branch_rows[0].get("properties") if branch_rows else {})
            query = (
                f"MATCH (b:{_quote(branch_label)})-[r]->(n) "
                f"WHERE {physical_b} AND toLower(toString(b.{_quote(branch_props['branchcode'])})) = $branch_code "
                "RETURN type(r) AS relationship_type, labels(n) AS labels, "
                "properties(n) AS properties, properties(r) AS relationship_properties "
                "LIMIT 5000"
            )
            edges = []
            for row in _rows(connection.execute(query, {"branch_code": branch["code"].casefold()})):
                labels = [str(v) for v in row.get("labels") or []]
                props = _safe_properties(row.get("properties"))
                relation = str(row.get("relationship_type") or "RELATED_TO")
                edges.append({
                    "relationship_type": relation,
                    "relationship_label": RELATIONSHIP_LABELS.get(relation, relation.replace("_", " ").title()),
                    "target_labels": labels,
                    "target_title": _node_summary(labels, props),
                    "properties": props,
                    "relationship_properties": _safe_properties(row.get("relationship_properties")),
                })
            peer_branches = _peer_branches_in_shared_areas(
                connection, branch_label, branch_props, branch["code"], schema
            )
            selected.append({
                "branch_code": branch["code"],
                "branch_name": branch["name"],
                "labels": [branch_label],
                "properties": branch_properties,
                "connections": edges,
                "peer_branches": peer_branches,
            })

        insights = _graph_insights(connection, branch_label, branch_props, schema, len(eligible))
        return {
            "available": True,
            "mode": "single-file",
            "node_count": sum(item["count"] for item in node_counts),
            "relationship_count": sum(item["count"] for item in relationship_counts),
            "node_counts": node_counts,
            "relationship_counts": relationship_counts,
            "branches": [{"code": b["code"], "name": b["name"]} for b in branch_records()],
            "insights": insights,
            "selected": selected,
        }
    finally:
        connection.close()


def inspect_graph_nodes(label: str, search: str = "", limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """Browse a bounded, read-only page of graph nodes; branch directory rows are physical-only."""
    connection = open_graph(read_only=True)
    try:
        schema, _relationship_types = _schema(connection)
        if label not in schema:
            raise ValueError("Choose a node label returned by the graph schema.")
        branch_label, branch_props = _branch_label(schema)

        properties = [
            key for key in schema[label].values()
            if key and not str(key).startswith("_")
            and _norm(key) not in {"librarytosourcekey", "librarytosourcefile"}
        ]
        term = str(search or "").strip()[:120]
        predicates = [f"toLower(toString(n.{_quote(key)})) CONTAINS $search" for key in properties]
        where_parts = []
        parameters = {}
        if label == branch_label:
            where_parts.append(_physical_branch_clause("n", branch_props))
        if term and predicates:
            where_parts.append("(" + " OR ".join(predicates) + ")")
            parameters["search"] = term.casefold()
        where = " WHERE " + " AND ".join(where_parts) if where_parts else ""

        count_rows = _rows(connection.execute(
            f"MATCH (n:{_quote(label)}){where} RETURN count(n) AS count", parameters
        ))
        total = int((count_rows[0].get("count") or 0) if count_rows else 0)
        safe_limit = max(1, min(int(limit), 100))
        safe_offset = max(0, min(int(offset), 50000))
        rows = _rows(connection.execute(
            f"MATCH (n:{_quote(label)}){where} "
            f"RETURN labels(n) AS labels, properties(n) AS properties "
            f"SKIP {safe_offset} LIMIT {safe_limit}", parameters
        ))
        records = []
        for row in rows:
            raw = row.get("properties") or {}
            props = _safe_properties(raw)
            labels = [str(value) for value in row.get("labels") or [label]]
            records.append({"summary": _node_summary(labels, props), "labels": labels, "properties": props})
        return {
            "available": True, "label": label, "display_label": _humanize_label(label),
            "physical_branch_filter": "PhysicalBranch = 1" if label == branch_label else None,
            "search": term, "total": total, "offset": safe_offset, "limit": safe_limit,
            "has_more": safe_offset + len(records) < total, "property_names": properties, "records": records,
        }
    finally:
        connection.close()

def activity_intensity_payload(branch_codes: list[str] | None = None) -> dict[str, Any]:
    """Calculate activity per 1,000 sq ft using only existing annual CSV snapshots."""
    from app.services.analytics import METRICS, overview

    data = overview()
    selected = {str(code).casefold() for code in (branch_codes or []) if str(code).strip()}
    branches = [b for b in data["branches"] if not selected or b["code"].casefold() in selected]
    branch_by_code = {b["code"]: b for b in branches}
    output: dict[str, Any] = {}
    for metric, label in METRICS.items():
        yearly = []
        for year_row in data.get("annual_values", {}).get(metric, []):
            per_branch = []
            total_activity = 0.0
            total_area = 0.0
            included = 0
            for code, branch in branch_by_code.items():
                value = year_row.get("values", {}).get(code)
                area = branch.get("square_footage")
                if value is None or area is None or float(area) <= 0:
                    continue
                rate = float(value) / float(area) * 1000.0
                per_branch.append({"code": code, "name": branch["name"], "activity": float(value), "square_footage": float(area), "per_1000_sq_ft": round(rate, 3)})
                total_activity += float(value)
                total_area += float(area)
                included += 1
            per_branch.sort(key=lambda item: item["per_1000_sq_ft"], reverse=True)
            yearly.append({
                "year": str(year_row["year"]),
                "network_per_1000_sq_ft": round(total_activity / total_area * 1000.0, 3) if total_area else None,
                "branches_with_values": included,
                "branch_values": per_branch,
            })
        output[metric] = {"label": label, "unit": "reported annual units per 1,000 sq ft", "years": yearly}
    return {
        "scope": "selected branches" if selected else "physical branch network",
        "denominator": "branch square footage from the supplied branch directory",
        "metrics": output,
    }


def _service_from_question(question: str) -> str | None:
    q = _norm(question)
    found = []
    for key, aliases in SERVICE_ALIASES.items():
        if any(_norm(alias) in q for alias in aliases):
            found.append(key)
    return found[0] if len(found) == 1 else None


def _area_intent(question: str) -> str | None:
    q = question.casefold()
    if re.search(r"\bward\b", q):
        return "ward"
    if re.search(r"\bneighbou?rhood\b|\bsame area\b", q):
        return "neighbourhood"
    return None


def _branch_value(props: dict[str, Any], aliases: tuple[str, ...]) -> str:
    values = {_norm(k): v for k, v in props.items()}
    return str(next((values.get(_norm(key)) for key in aliases if values.get(_norm(key)) not in (None, "")), "")).strip()


def _area_records(connection, area_type: str) -> list[dict[str, Any]]:
    label = WARD_LABEL if area_type == "ward" else NEIGHBOURHOOD_LABEL
    rows = _rows(connection.execute(f"MATCH (a:{_quote(label)}) RETURN properties(a) AS properties LIMIT 1000"))
    return [row.get("properties") or {} for row in rows if isinstance(row.get("properties"), dict)]


def _resolve_area(question: str, area_type: str, records: list[dict[str, Any]]) -> tuple[str, str] | None:
    q = question.casefold()
    q_compact = _norm(question)
    if area_type == "ward":
        match = re.search(r"\bward\s+(?:no\.?\s*)?(\d+)\b", q)
        if match:
            return "ward_no", match.group(1)
        aliases = ("name", "ward_name")
    else:
        aliases = ("name", "neighbourhood_name")
    for record in records:
        name = _branch_value(record, aliases)
        if name and (name.casefold() in q or _norm(name) in q_compact):
            key = "name" if "name" in {_norm(k) for k in record} else aliases[-1]
            return key, name
    return None


def _metric_intent(question: str) -> tuple[str, str] | None:
    q = question.casefold()
    for metric, (rel_type, label, aliases, _) in METRIC_CONFIG.items():
        words = {
            "circulation": ("circulation", "checkouts", "borrowing"),
            "visits": ("visits", "visitation"),
            "workstations": ("workstation sessions", "workstation usage", "computer sessions", "sessions"),
            "registrations": ("registrations", "card registrations"),
        }[metric]
        if any(re.search(rf"\b{re.escape(word)}\b", q) for word in words):
            return metric, rel_type
    return None


def answer_connected_question(connection, schema: dict[str, dict[str, str]], question: str, branch: dict[str, Any] | None) -> dict[str, Any] | None:
    """Answer relationship-dependent questions by traversing real Relate edges.

    Returns None when the question is outside connected-context scope so the
    existing field/metric Q&A remains the fallback.
    """
    if not any(name in schema for name in (NEIGHBOURHOOD_LABEL, WARD_LABEL, SERVICE_LABEL, FACILITY_LABEL)):
        return None
    branch_label, branch_props = _branch_label(schema)
    q = question.casefold()
    service_key = _service_from_question(question)
    area_type = _area_intent(question)
    metric_intent = _metric_intent(question)
    asks_network_metric_ranking = bool(
        metric_intent and branch is None and re.search(
            r"\b(highest|lowest|most|least|top|rank|ranking)\b", q
        )
    )
    mentions_cross_branch = bool(re.search(
        r"\b(other branches|branches|branch locations|library locations|same ward|same neighbourhood|same neighborhood|which branches|how many (?:branches|libraries|locations))\b", q
    )) or asks_network_metric_ranking
    service_question = service_key is not None or (
        bool(re.search(r"\b(services|service offerings)\b", q)) and bool(branch or area_type)
    )
    asks_area_peer_question = bool(re.search(
        r"\b(other|same|compare|among|which|list|show|find|how many)\b.{0,45}\b(branches|libraries|locations)\b|\b(branches|libraries|locations)\b.{0,45}\b(ward|neighbou?rhood)\b",
        q,
    ))
    # Asking for the selected branch's own ward/neighbourhood is a directory
    # field question, not a peer-traversal question. Leave it to the existing
    # branch-directory answer path unless the user asks about other locations,
    # connected services or annual measures in that area.
    if area_type and branch and not (asks_area_peer_question or service_question or metric_intent):
        return None
    if not (area_type or service_question or mentions_cross_branch):
        return None
    # The existing metric intent handlers already provide full time-series and
    # ranking behaviour. Route metrics through graph edges only when the user
    # explicitly asks for an area/cross-branch comparison.
    if metric_intent and not area_type and not mentions_cross_branch:
        return None

    # Resolve a named ward/neighbourhood, or anchor to the branch selected in
    # Branch Insights / named in Overview Q&A.
    area_value = None
    area_property = None
    area_records = _area_records(connection, area_type) if area_type else []
    if area_type:
        resolved = _resolve_area(question, area_type, area_records)
        if resolved:
            area_property, area_value = resolved
        elif not branch:
            return None

    match_parts = [f"MATCH (peer:{_quote(branch_label)})"]
    predicates: list[str] = []
    parameters: dict[str, Any] = {}
    service_peer_scope = bool(branch and service_question and mentions_cross_branch and not area_type)
    shared_service_area_scope = bool(branch and service_question and mentions_cross_branch and area_type and not service_key)
    service_relation = "HAS_FACILITY" if service_key == "publicwashroom" else "OFFERS_SERVICE"
    service_label = FACILITY_LABEL if service_key == "publicwashroom" else SERVICE_LABEL
    service_property = "facility_key" if service_key == "publicwashroom" else "service_key"
    if service_peer_scope:
        # Traverse from the selected branch to a shared service/facility node,
        # then back to the other branches connected to that same node.
        match_parts = [
            f"MATCH (anchor:{_quote(branch_label)})-[:{service_relation}]->(service:{_quote(service_label)})"
            f"<-[:{service_relation}]-(peer:{_quote(branch_label)})"
        ]
        predicates.append(f"toLower(toString(anchor.{_quote(branch_props['branchcode'])})) = $anchor_code")
        predicates.append(f"toLower(toString(peer.{_quote(branch_props['branchcode'])})) <> $anchor_code")
        parameters["anchor_code"] = branch["code"].casefold()
    elif area_type:
        area_label = WARD_LABEL if area_type == "ward" else NEIGHBOURHOOD_LABEL
        relation = "IN_WARD" if area_type == "ward" else "IN_NEIGHBOURHOOD"
        if area_value is not None and branch:
            match_parts.append(
                f"MATCH (anchor:{_quote(branch_label)})-[:{relation}]->(area:{_quote(area_label)})"
                f"<-[:{relation}]-(peer)"
            )
            predicates.append(f"toLower(toString(anchor.{_quote(branch_props['branchcode'])})) = $anchor_code")
            parameters["anchor_code"] = branch["code"].casefold()
            predicates.append(f"toLower(toString(peer.{_quote(branch_props['branchcode'])})) <> $anchor_code")
            if shared_service_area_scope:
                match_parts.append(
                    f"MATCH (anchor)-[:{service_relation}]->(service:{_quote(service_label)})"
                    f"<-[:{service_relation}]-(peer)"
                )
        elif area_value is not None:
            match_parts.append(f"MATCH (peer)-[:{relation}]->(area:{_quote(area_label)})")
        elif branch:
            match_parts.append(
                f"MATCH (anchor:{_quote(branch_label)})-[:{relation}]->(area:{_quote(area_label)})"
                f"<-[:{relation}]-(peer)"
            )
            predicates.append(f"toLower(toString(anchor.{_quote(branch_props['branchcode'])})) = $anchor_code")
            parameters["anchor_code"] = branch["code"].casefold()
            predicates.append(f"toLower(toString(peer.{_quote(branch_props['branchcode'])})) <> $anchor_code")
            if shared_service_area_scope:
                match_parts.append(
                    f"MATCH (anchor)-[:{service_relation}]->(service:{_quote(service_label)})"
                    f"<-[:{service_relation}]-(peer)"
                )
        if area_value is not None:
            actual_area_key = "ward_no" if area_type == "ward" and area_property == "ward_no" else "name"
            predicates.append(f"toLower(toString(area.{_quote(actual_area_key)})) = $area_value")
            parameters["area_value"] = str(area_value).casefold()
    elif branch and mentions_cross_branch:
        # A branch-scoped question can still compare its selected branch with
        # the rest of the network. The selected branch is the anchor and is
        # excluded from the peer result set.
        predicates.append(f"toLower(toString(peer.{_quote(branch_props['branchcode'])})) <> $anchor_code")
        parameters["anchor_code"] = branch["code"].casefold()
    elif branch:
        predicates.append(f"toLower(toString(peer.{_quote(branch_props['branchcode'])})) = $anchor_code")
        parameters["anchor_code"] = branch["code"].casefold()

    if service_question and not service_peer_scope and not shared_service_area_scope:
        match_parts.append(f"MATCH (peer)-[:{service_relation}]->(service:{_quote(service_label)})")
    if service_question and service_key:
        predicates.append(f"toLower(toString(service.{service_property})) = $service_key")
        parameters["service_key"] = service_key

    metric_name = None
    if metric_intent:
        metric_name, rel_type = metric_intent
        label = METRIC_CONFIG[metric_name][1]
        metric_properties = schema.get(label, {})
        value_aliases = {_norm(k) for k in METRIC_CONFIG[metric_name][2]}
        value_key = next((v for k, v in metric_properties.items() if k in value_aliases), None)
        year_key = next((v for k, v in metric_properties.items() if k in {"year", "fiscalyear", "calendaryear"}), None)
        if not value_key or not year_key:
            return None
        match_parts.append(f"MATCH (peer)-[:{rel_type}]->(metric:{_quote(label)})")
        year_match = re.search(r"\b((?:19|20)\d{2})\b", question)
        if year_match:
            predicates.append(f"toString(metric.{_quote(year_key)}) = $year")
            parameters["year"] = year_match.group(1)

    if not area_type and not branch and not service_key and not mentions_cross_branch:
        return None
    where = " WHERE " + " AND ".join(predicates) if predicates else ""
    query = (
        " ".join(match_parts) + where +
        " RETURN properties(peer) AS branch_properties, "
        + ("properties(area) AS area_properties, " if area_type else "")
        + ("properties(metric) AS metric_properties, " if metric_name else "[] AS metric_properties, ")
        + ("properties(service) AS service_properties" if service_question else "[] AS service_properties")
        + " LIMIT 5000"
    )
    try:
        rows = _rows(connection.execute(query, parameters))
    except Exception:
        # Do not break regular Q&A if an older store has not been rebuilt yet.
        return None

    if service_question and branch and not area_type and not mentions_cross_branch:
        names = sorted({
            str((row.get("service_properties") or {}).get("service_name") or (row.get("service_properties") or {}).get("facility_name") or "")
            for row in rows if isinstance(row.get("service_properties"), dict)
        } - {""})
        answer = f"{branch['name']} has these connected services: {', '.join(names)}." if names else f"No connected service records were found for {branch['name']}."
        return _connected_answer(answer, "Reported services", [{"label": "Service", "value": name} for name in names], rows, branch, False)

    if metric_name:
        metric_rows = []
        for row in rows:
            bp = row.get("branch_properties") or {}
            mp = row.get("metric_properties") or {}
            code = _branch_value(bp, ("BranchCode",))
            name = _branch_value(bp, ("BranchName", "Name")) or code
            year = _branch_value(mp, ("Year", "FiscalYear", "CalendarYear"))
            raw = _branch_value(mp, METRIC_CONFIG[metric_name][2])
            try:
                value = float(str(raw).replace(",", ""))
            except (TypeError, ValueError):
                continue
            metric_rows.append({"code": code, "name": name, "year": year, "value": value})
        if not metric_rows:
            return None
        asked_year = re.search(r"\b((?:19|20)\d{2})\b", question)
        latest_requested = bool(re.search(r"\b(latest|most recent|last reported|current year)\b", q))
        low = bool(re.search(r"\b(lowest|least|fewest|smallest)\b", q))
        ranking = bool(re.search(r"\b(highest|lowest|most|least|top|rank|ranking)\b", q))
        if asked_year:
            chosen_year = asked_year.group(1)
            metric_rows = [r for r in metric_rows if r["year"] == chosen_year]
        elif ranking and not latest_requested:
            # A ranking without a year compares every available branch-year
            # observation, rather than silently restricting the answer to 2024.
            chosen_year = "all available reporting years"
        else:
            chosen_year = max((r["year"] for r in metric_rows if r["year"].isdigit()), key=int, default="")
            metric_rows = [r for r in metric_rows if not chosen_year or r["year"] == chosen_year]
        metric_rows.sort(key=lambda r: r["value"], reverse=not low if ranking else False)
        selected = metric_rows[:10 if ranking else 20]
        label = METRIC_CONFIG[metric_name][3]
        if area_type:
            scope = f"the requested {area_type}"
        elif branch and mentions_cross_branch:
            scope = f"other physical branches (excluding {branch['name']})"
        elif branch:
            scope = f"{branch['name']}'s connected context"
        else:
            scope = "the physical branch network"
        if ranking and chosen_year == "all available reporting years":
            direction = "lowest" if low else "highest"
            yearly_leaders = []
            for reporting_year in sorted({r["year"] for r in metric_rows if r["year"].isdigit()}, key=int):
                year_rows = [r for r in metric_rows if r["year"] == reporting_year]
                year_rows.sort(key=lambda item: item["value"], reverse=not low)
                if year_rows:
                    yearly_leaders.append(year_rows[0])
            answer = (
                f"Across all available reporting years, the {direction} annual {label} in {scope} was "
                + (f"{selected[0]['name']} ({selected[0]['value']:,.0f}) in {selected[0]['year']}" if selected else "not reported")
                + ". Ranked branch-year records: "
                + "; ".join(f"{r['name']} ({r['value']:,.0f}, {r['year']})" for r in selected) + "."
            )
            if yearly_leaders:
                answer += " Annual leader by year: " + "; ".join(
                    f"{row['year']}: {row['name']} ({row['value']:,.0f})" for row in yearly_leaders
                ) + "."
            details = [{"label": f"{r['name']} · {r['year']}", "value": f"{r['value']:,.0f}"} for r in selected]
            details.extend({"label": f"{row['year']} annual leader", "value": f"{row['name']} · {row['value']:,.0f}"} for row in yearly_leaders)
        else:
            answer = (
                f"{len(metric_rows)} branch records in {scope} reported {label} "
                f"for {chosen_year or 'the available year'}: "
                + "; ".join(f"{r['name']} ({r['value']:,.0f})" for r in selected) + "."
            )
            details = [{"label": r["name"], "value": f"{r['value']:,.0f}"} for r in selected]
        return _connected_answer(answer, f"Connected {label.title()}", details, rows, branch, not bool(branch))

    if service_question:
        service_name = SERVICE_NAMES.get(service_key, "reported services")
        service_branches = sorted({
            _branch_value(row.get("branch_properties") or {}, ("BranchName", "Name"))
            for row in rows
            if _branch_value(row.get("branch_properties") or {}, ("BranchName", "Name"))
        }, key=str.casefold)
        if branch and not area_type and not mentions_cross_branch:
            service_names = sorted({
                str((row.get("service_properties") or {}).get("service_name") or (row.get("service_properties") or {}).get("facility_name") or "")
                for row in rows if isinstance(row.get("service_properties"), dict)
            } - {""})
            return _connected_answer(
                f"{branch['name']} has these connected services: {', '.join(service_names) or 'none listed'}.",
                "Reported services", [{"label": "Service", "value": n} for n in service_names], rows, branch, False
            )
        scope = f"in the requested {area_type}" if area_type else "across physical branches"
        if service_peer_scope:
            scope = f"sharing a connected service or facility with {branch['name']}"
        elif branch:
            scope = f"in the {branch['name']} {area_type or 'branch'} context"
        answer = f"Branches with {service_name} {scope}: " + (", ".join(service_branches) if service_branches else "none found") + "."
        return _connected_answer(answer, service_name, [{"label": "Branch", "value": n} for n in service_branches], rows, branch, not bool(branch))

    peers = sorted({
        _branch_value(row.get("branch_properties") or {}, ("BranchName", "Name"))
        for row in rows
        if _branch_value(row.get("branch_properties") or {}, ("BranchName", "Name"))
    }, key=str.casefold)
    context = "ward" if area_type == "ward" else "neighbourhood"
    answer = (
        f"Other physical branches connected to {branch['name']} through its {context}: "
        if branch else f"Physical branches in the requested {context}: "
    ) + (", ".join(peers) if peers else "none found") + "."
    return _connected_answer(answer, f"Branches in {context}", [{"label": "Branch", "value": name} for name in peers], rows, branch, not bool(branch))

def _connected_answer(answer: str, category: str, details: list[dict[str, str]], rows: list[dict[str, Any]], branch: dict[str, Any] | None, network_scope: bool) -> dict[str, Any]:
    return {
        "status": "ok",
        "answer": answer,
        "highlights": [{"title": branch["name"] if branch else category, "category": category, "details": details[:30]}],
        "evidence": [],
        "direct_intent": True,
        # Branch-specific Q&A can traverse to peer branches in the selected
        # branch's own ward/neighbourhood. This is still a selected-branch query.
        "scope_verified": True,
        "network_scope": network_scope,
    }
