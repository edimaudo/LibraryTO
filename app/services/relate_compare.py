"""Read annual branch metrics from the embedded Relate graph for comparisons.

The current graph import stores each CSV record as a labelled node. This
adapter therefore joins the annual metric nodes to the physical-branch list
using BranchCode; it does not pretend that relationships exist where none were
created. User input is parameterized, and schema-derived identifiers are quoted.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from app.config import RELATE_FILE
from app.services.analytics import METRICS
from app.services.data_store import branch_records, is_physical_branch, field


def _identifier(value: str) -> str:
    if not value or any(ord(ch) < 32 for ch in value):
        raise ValueError("Invalid graph identifier")
    return "`" + value.replace("`", "``") + "`"


def _normalize(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def compare_from_relate(codes: tuple[str, ...]) -> dict[str, Any] | None:
    if not RELATE_FILE.is_file():
        return None
    try:
        import relate
        connection = relate.connect(database=str(RELATE_FILE), read_only=True)
    except Exception:
        return None
    try:
        schema = connection.execute(
            "CALL db.schema.nodeTypeProperties() YIELD nodeLabels, propertyName "
            "RETURN nodeLabels, propertyName LIMIT 500"
        ).fetchall()
        properties: dict[str, set[str]] = defaultdict(set)
        for row in schema:
            labels = row.get("nodeLabels") or []
            if isinstance(labels, str):
                labels = [labels]
            for label in labels:
                properties[str(label)].add(str(row.get("propertyName") or ""))

        branch_lookup = {branch["code"].casefold(): branch for branch in branch_records()}
        selected = [branch_lookup[code.casefold()] for code in codes if code.casefold() in branch_lookup]
        selected_codes = {branch["code"].casefold() for branch in selected}
        metric_values: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
        value_aliases = {
            "circulation": ("circulation", "totalcirculation"),
            "visits": ("visits", "totalvisits"),
            "workstations": ("sessions", "workstationsessions", "workstationusage"),
            "registrations": ("registrations", "cardregistrations", "newregistrations"),
        }
        for label, names in properties.items():
            normalized = {_normalize(name): name for name in names if name}
            branch_key = next((normalized[key] for key in ("branchcode", "tplbranchcode") if key in normalized), None)
            year_key = next((normalized[key] for key in ("year", "fiscalyear", "calendaryear") if key in normalized), None)
            if not branch_key or not year_key:
                continue
            matching_metric = next((metric for metric, aliases in value_aliases.items() if any(alias in normalized for alias in aliases)), None)
            if not matching_metric:
                continue
            value_key = next(normalized[alias] for alias in value_aliases[matching_metric] if alias in normalized)
            query = (
                f"MATCH (n:{_identifier(label)}) "
                f"WHERE toLower(toString(n.{_identifier(branch_key)})) = $branch_code "
                f"RETURN properties(n) AS properties LIMIT 5000"
            )
            for requested in selected_codes:
                rows = connection.execute(query, {"branch_code": requested}).fetchall()
                for row in rows:
                    props = row.get("properties") or {}
                    if not isinstance(props, dict) or not is_physical_branch(props):
                        continue
                    branch_code = str(field(props, branch_key)).strip()
                    if branch_code.casefold() not in selected_codes:
                        continue
                    year_match = re.search(r"(?:19|20)\d{2}", str(field(props, year_key)))
                    try:
                        value = float(field(props, value_key))
                    except (TypeError, ValueError):
                        continue
                    if year_match:
                        canonical = branch_lookup[branch_code.casefold()]["code"]
                        metric_values[matching_metric][year_match.group(0)][canonical] = value
        # Do not return a misleading empty comparison when the graph contains
        # branch details but not its annual observations.
        if not any(metric_values.values()):
            return None
        metrics = {}
        for metric in METRICS:
            years = sorted(metric_values[metric], key=lambda item: int(item))
            metrics[metric] = [
                {"year": year, "values": {branch["code"]: metric_values[metric][year].get(branch["code"]) for branch in selected}}
                for year in years
            ]
        return {"branches": selected, "metrics": metrics, "metric_labels": METRICS, "data_source": "Relate graph"}
    finally:
        connection.close()
