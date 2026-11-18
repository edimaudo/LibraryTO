"""Read-only, schema-aware retrieval from the user-supplied Relate .rl store.

No user-authored Cypher is executed. Search statements are built from labels
and property names discovered in the existing graph, and all search values are
passed as parameters.
"""
from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
import importlib
import re
from typing import Any

from app.config import RELATE_FILE

STOP_WORDS = {
    "a", "about", "and", "are", "at", "be", "been", "branch", "branches",
    "by", "can", "do", "does", "for", "from", "how", "i", "in", "is",
    "it", "me", "of", "on", "or", "please", "the", "their", "this",
    "to", "tpl", "was", "what", "when", "where", "which", "who", "why",
    "with", "would", "you", "your", "show", "find", "list", "tell", "give",
}
def _quote_identifier(value: Any) -> str | None:
    """Quote a discovered graph identifier; never accept it from the request."""
    text = str(value or "")
    if not text or any(ord(character) < 32 for character in text):
        return None
    return "`" + text.replace("`", "``") + "`"


class RelateUnavailable(RuntimeError):
    """The supplied Relate file or Python client cannot be opened."""


def _load_module():
    try:
        return importlib.import_module("relate")
    except ImportError as exc:
        raise RelateUnavailable("The relate-db package is not installed in this environment.") from exc


def _open_connection():
    if not RELATE_FILE.is_file():
        raise RelateUnavailable(f"The graph file {RELATE_FILE.name} has not been added to data/ yet.")
    relate = _load_module()
    try:
        return relate.connect(database=str(RELATE_FILE), read_only=True)
    except Exception as exc:  # Relate exposes typed errors; keep provider internals server-side.
        raise RelateUnavailable(f"The graph file could not be opened read-only ({type(exc).__name__}).") from exc


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, bytes):
        return value.hex()
    if hasattr(value, "to_dict"):
        try:
            return _json_safe(value.to_dict())
        except Exception:
            return str(value)
    return str(value)


def _fetchall(connection, statement: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    cursor = connection.execute(statement, params or {})
    return cursor.fetchall()


def graph_schema() -> dict[str, Any]:
    connection = _open_connection()
    try:
        labels_rows = _fetchall(connection, "CALL db.labels() YIELD label RETURN label")
        relationship_rows = _fetchall(
            connection,
            "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType",
        )
        property_rows = _fetchall(
            connection,
            "CALL db.schema.nodeTypeProperties() YIELD nodeLabels, propertyName "
            "RETURN nodeLabels, propertyName LIMIT 500",
        )
        node_properties: dict[str, set[str]] = {}
        for row in property_rows:
            labels = row.get("nodeLabels") or []
            if isinstance(labels, str):
                labels = [labels]
            for label in labels:
                if isinstance(label, str):
                    node_properties.setdefault(label, set()).add(str(row.get("propertyName") or ""))
        labels = sorted({str(row.get("label")) for row in labels_rows if row.get("label")})
        relationships = sorted({str(row.get("relationshipType")) for row in relationship_rows if row.get("relationshipType")})
        return {
            "available": True,
            "file": RELATE_FILE.name,
            "labels": labels,
            "relationship_types": relationships,
            "node_properties": {key: sorted(value) for key, value in sorted(node_properties.items())},
        }
    except Exception as exc:
        raise RelateUnavailable(f"The graph schema could not be read ({type(exc).__name__}).") from exc
    finally:
        connection.close()


def graph_status() -> dict[str, Any]:
    status = {
        "filename": RELATE_FILE.name,
        "file_present": RELATE_FILE.is_file(),
        "client_available": False,
        "ready": False,
        "message": "",
    }
    if not status["file_present"]:
        status["message"] = f"Add {RELATE_FILE.name} to the data/ directory to enable graph-backed retrieval."
        return status
    try:
        _load_module()
        status["client_available"] = True
        schema = graph_schema()
        status["ready"] = True
        status["labels"] = schema["labels"]
        status["relationship_types"] = schema["relationship_types"]
        status["message"] = "Graph file opened successfully in read-only mode."
    except RelateUnavailable as exc:
        status["message"] = str(exc)
    return status


def _terms(question: str, branch_code: str | None = None) -> list[str]:
    text = f"{question} {branch_code or ''}".casefold()
    tokens = [token for token in re.findall(r"[\w'-]+", text) if len(token) >= 2 and token not in STOP_WORDS]
    return list(dict.fromkeys(tokens))[:8]


def ask(question: str, branch_code: str | None = None) -> dict[str, Any]:
    """Keyword-rank matching graph nodes and expose connected evidence.

    This is deterministic graph retrieval, not LLM-generated prose. It provides
    evidence from the actual graph without allowing arbitrary Cypher execution.
    """
    terms = _terms(question, branch_code)
    if not terms:
        return {
            "status": "no_search_terms",
            "answer": "Add a branch name, service, metric, event or another specific term to search the graph.",
            "evidence": [],
        }

    connection = _open_connection()
    try:
        labels = [
            str(row.get("label"))
            for row in _fetchall(connection, "CALL db.labels() YIELD label RETURN label")
            if row.get("label") and _quote_identifier(row.get("label"))
        ]
        schema_rows = _fetchall(
            connection,
            "CALL db.schema.nodeTypeProperties() YIELD nodeLabels, propertyName "
            "RETURN nodeLabels, propertyName LIMIT 500",
        )
        properties_by_label: dict[str, set[str]] = {label: set() for label in labels}
        for row in schema_rows:
            group = row.get("nodeLabels") or []
            if isinstance(group, str):
                group = [group]
            prop = str(row.get("propertyName") or "")
            if not _quote_identifier(prop):
                continue
            for label in group:
                if label in properties_by_label:
                    properties_by_label[label].add(prop)

        # If the schema procedure returns no properties, use an actual sample
        # node to discover keys. Identifiers are validated before interpolation.
        for label in labels:
            if not properties_by_label[label]:
                sample = _fetchall(
                    connection,
                    f"MATCH (n:{_quote_identifier(label)}) RETURN properties(n) AS properties LIMIT 1",
                )
                if sample and isinstance(sample[0].get("properties"), dict):
                    properties_by_label[label].update(
                        key for key in sample[0]["properties"] if isinstance(key, str) and _quote_identifier(key)
                    )

        evidence_by_node: dict[str, dict[str, Any]] = {}
        for label in labels[:30]:
            properties = sorted(properties_by_label.get(label, set()))[:30]
            if not properties:
                continue
            predicates = []
            parameters: dict[str, str] = {}
            for prop in properties:
                quoted_prop = _quote_identifier(prop)
                if not quoted_prop:
                    continue
                for term_index, term in enumerate(terms):
                    param_name = f"t{term_index}"
                    parameters[param_name] = term
                    predicates.append(f"toLower(toString(n.{quoted_prop})) CONTAINS ${param_name}")
            if not predicates:
                continue
            statement = (
                f"MATCH (n:{_quote_identifier(label)}) WHERE {' OR '.join(predicates)} "
                "OPTIONAL MATCH (n)-[r]-(m) "
                "RETURN labels(n) AS labels, properties(n) AS properties, "
                "type(r) AS relationship_type, labels(m) AS related_labels, "
                "properties(m) AS related_properties LIMIT 30"
            )
            try:
                for row in _fetchall(connection, statement, parameters):
                    props = _json_safe(row.get("properties") or {})
                    if not isinstance(props, dict):
                        continue
                    matched = 0
                    searchable = " ".join(str(value) for value in props.values()).casefold()
                    for term in terms:
                        if term in searchable:
                            matched += 1
                    if not matched:
                        continue
                    node_labels = _json_safe(row.get("labels") or [label])
                    node_key = repr((node_labels, sorted(props.items())))
                    item = evidence_by_node.setdefault(node_key, {
                        "labels": node_labels,
                        "properties": props,
                        "connections": [],
                        "match_count": matched,
                    })
                    item["match_count"] = max(item["match_count"], matched)
                    relationship_type = row.get("relationship_type")
                    if relationship_type:
                        connection_evidence = {
                            "relationship_type": str(relationship_type),
                            "related_labels": _json_safe(row.get("related_labels") or []),
                            "related_properties": _json_safe(row.get("related_properties") or {}),
                        }
                        connection_key = repr(connection_evidence)
                        if all(repr(existing) != connection_key for existing in item["connections"]):
                            item["connections"].append(connection_evidence)
            except Exception:
                # One unsupported property/query shape should not prevent the
                # remaining discovered labels from being searched.
                continue

        deduplicated = sorted(
            evidence_by_node.values(),
            key=lambda item: item["match_count"],
            reverse=True,
        )[:20]

        if not deduplicated:
            answer = "The graph did not return a node matching those terms. Try a branch name, branch code, service name, metric or event keyword."
            status = "no_matches"
        else:
            node_types = sorted({label for item in deduplicated for label in item["labels"]})
            edge_count = sum(len(item.get("connections", [])) for item in deduplicated)
            answer = (
                f"Relate returned {len(deduplicated)} matching graph record(s) across "
                f"{', '.join(node_types)}. {edge_count} returned record(s) include a connected relationship. "
                "The evidence below shows the matching node properties and any connected node returned by the graph query."
            )
            status = "ok"
        return {
            "status": status,
            "answer": answer,
            "search_terms": terms,
            "evidence": deduplicated,
            "source": RELATE_FILE.name,
            "retrieval_method": "Schema-aware, parameterized Cypher retrieval",
            "notice": "This version retrieves and ranks graph evidence. It does not use a generative language model to infer facts or write arbitrary Cypher.",
        }
    except RelateUnavailable:
        raise
    except Exception as exc:
        raise RelateUnavailable(f"The graph query could not be completed ({type(exc).__name__}).") from exc
    finally:
        connection.close()
