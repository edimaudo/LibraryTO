"""Rebuild LibraryTO's persistent Relate graph from its committed CSV snapshots.

The script imports the same seven CSV files as data/Load_relate_db.ipynb, then
adds typed relationships derived only from those records. It builds a staging
single-file store, validates it, and replaces data/tpl_library_graph.rl only
when the new graph can be reopened and contains the expected relationship types.
Run while the application is stopped so the file is not locked by a reader.
"""
from __future__ import annotations

import csv
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DEST = DATA / "tpl_library_graph.rl"
SOURCES = [
    ("tpl-events-feed.csv", "EventsFeed"),
    ("tpl-Neighbourhoods.csv", "Neighbourhoods"),
    ("tpl-circulation-annual-by-branch.csv", "CirculationAnnualByBranch"),
    ("tpl-branch-general-information.csv", "BranchGeneralInformation"),
    ("tpl-workstation-usage-annual-by-branch.csv", "WorkstationUsageAnnualByBranch"),
    ("tpl-visits-annual-by-branch.csv", "VisitsAnnualByBranch"),
    ("tpl-card-registrations-annual-by-branch.csv", "CardRegistrationsAnnualByBranch"),
]
METRICS = [
    ("tpl-circulation-annual-by-branch.csv", "CirculationAnnualByBranch", "HAS_CIRCULATION_RECORD"),
    ("tpl-visits-annual-by-branch.csv", "VisitsAnnualByBranch", "HAS_VISITS_RECORD"),
    ("tpl-workstation-usage-annual-by-branch.csv", "WorkstationUsageAnnualByBranch", "HAS_WORKSTATION_RECORD"),
    ("tpl-card-registrations-annual-by-branch.csv", "CardRegistrationsAnnualByBranch", "HAS_REGISTRATION_RECORD"),
]
SERVICES = {
    "KidsStop": "Kids Stop", "LeadingReading": "Leading Reading", "CLC": "Community-led services",
    "DIH": "Digital Innovation Hub", "TeenCouncil": "Teen Council", "YouthHub": "Youth Hub",
    "AdultLiteracyProgram": "Adult Literacy Program",
}


def norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def quote(value: str) -> str:
    if not value or any(ord(ch) < 32 for ch in value):
        raise ValueError("Unsafe Cypher identifier")
    return "`" + value.replace("`", "``") + "`"


def truthy(value: Any) -> bool:
    return str(value or "").strip().casefold() in {"1", "1.0", "true", "yes", "y", "t", "available", "offered"}


def read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"Required CSV snapshot is missing: {path.name}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"CSV snapshot has no header: {path.name}")
        rows = []
        for index, row in enumerate(reader, start=1):
            record = {str(k).strip(): (v if v not in ("") else None) for k, v in row.items() if k is not None}
            record["_libraryto_source_key"] = f"{path.stem}:{index}"
            record["_libraryto_source_file"] = path.name
            rows.append(record)
        return rows


def get_value(row: dict[str, Any], *keys: str) -> Any:
    values = {norm(k): v for k, v in row.items()}
    for key in keys:
        value = values.get(norm(key))
        if value not in (None, ""):
            return value
    return None


def label_properties(connection, label: str) -> set[str]:
    rows = connection.execute(
        "CALL db.schema.nodeTypeProperties() YIELD nodeLabels, propertyName RETURN nodeLabels, propertyName LIMIT 2000"
    ).fetchall()
    output = set()
    for row in rows:
        labels = row.get("nodeLabels") or []
        if isinstance(labels, str):
            labels = [labels]
        if label in labels and row.get("propertyName"):
            output.add(str(row["propertyName"]))
    return output


def _run_many(connection, statement: str, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    connection.executemany(statement, rows)
    connection.commit()
    return len(rows)


def _match_and_link(connection, branch_key: str, target_label: str, target_key: str, relationship: str, parameters: dict[str, Any]) -> None:
    statement = (
        f"MATCH (b:{quote('BranchGeneralInformation')}), (n:{quote(target_label)}) "
        "WHERE b._libraryto_source_key = $branch_key AND n._libraryto_source_key = $target_key "
        f"MERGE (b)-[:{quote(relationship)}]->(n)"
    )
    connection.execute(statement, {"branch_key": branch_key, "target_key": target_key, **parameters})


def build_relationships(connection, datasets: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    branches = datasets["tpl-branch-general-information.csv"]
    physical: dict[str, dict[str, Any]] = {}
    for branch in branches:
        if not truthy(get_value(branch, "PhysicalBranch") if get_value(branch, "PhysicalBranch") is not None else 1):
            continue
        code = str(get_value(branch, "BranchCode", "Branch Code") or "").strip()
        if code:
            physical[code.casefold()] = branch

    counts: dict[str, int] = {}
    # Branch -> annual observations. Source-row keys make duplicate rows
    # individually inspectable and prevent accidental many-to-many joins.
    for filename, label, rel_type in METRICS:
        batch = []
        for record in datasets[filename]:
            code = str(get_value(record, "BranchCode", "Branch Code") or "").strip().casefold()
            branch = physical.get(code)
            if branch and truthy(get_value(record, "PhysicalBranch") if get_value(record, "PhysicalBranch") is not None else 1):
                batch.append({"branch_key": branch["_libraryto_source_key"], "target_key": record["_libraryto_source_key"]})
        statement = (
            f"MATCH (b:{quote('BranchGeneralInformation')}), (m:{quote(label)}) "
            "WHERE b._libraryto_source_key = $branch_key AND m._libraryto_source_key = $target_key "
            f"MERGE (b)-[:{quote(rel_type)}]->(m)"
        )
        counts[rel_type] = _run_many(connection, statement, batch)

    # Branch -> event records, using an exact source BranchCode first and the
    # supplied location/name only when a branch code is absent.
    branch_names: dict[str, list[dict[str, Any]]] = {}
    for item in physical.values():
        name = str(get_value(item, "BranchName", "Branch Name", "Name") or "").strip().casefold()
        if name:
            branch_names.setdefault(name, []).append(item)
    event_rows = []
    for event in datasets["tpl-events-feed.csv"]:
        code = str(get_value(event, "BranchCode", "Branch Code", "TPLBranchCode") or "").strip().casefold()
        branch = physical.get(code)
        if not branch and not code:
            location = str(get_value(event, "LocationName", "BranchName", "Location", "Venue") or "").strip().casefold()
            matches = branch_names.get(location, [])
            branch = matches[0] if len(matches) == 1 else None
        if branch and truthy(get_value(event, "PhysicalBranch") if get_value(event, "PhysicalBranch") is not None else 1):
            event_rows.append({"branch_key": branch["_libraryto_source_key"], "target_key": event["_libraryto_source_key"]})
    counts["HOSTS_EVENT"] = _run_many(connection,
        f"MATCH (b:{quote('BranchGeneralInformation')}), (e:{quote('EventsFeed')}) "
        "WHERE b._libraryto_source_key = $branch_key AND e._libraryto_source_key = $target_key "
        f"MERGE (b)-[:{quote('HOSTS_EVENT')}]->(e)", event_rows)

    # Branch -> neighbourhood and ward nodes derived from the branch directory.
    area_links: dict[str, int] = {"IN_NEIGHBOURHOOD": 0, "IN_WARD": 0}
    for branch in physical.values():
        branch_key = branch["_libraryto_source_key"]
        nbhd_name = str(get_value(branch, "NBHDName", "NeighbourhoodName", "Neighbourhood") or "").strip()
        nbhd_no = str(get_value(branch, "NBHDNo", "NeighbourhoodNo", "NeighbourhoodNumber") or "").strip()
        if nbhd_name or nbhd_no:
            area_key = nbhd_no or norm(nbhd_name)
            connection.execute(
                f"MERGE (a:{quote('LibraryNeighbourhood')} {{area_key: $area_key}}) "
                "ON CREATE SET a.name = $name, a.neighbourhood_no = $number",
                {"area_key": area_key, "name": nbhd_name or f"Neighbourhood {nbhd_no}", "number": nbhd_no or None},
            )
            connection.execute(
                f"MATCH (b:{quote('BranchGeneralInformation')}), (a:{quote('LibraryNeighbourhood')}) "
                "WHERE b._libraryto_source_key = $branch_key AND a.area_key = $area_key "
                f"MERGE (b)-[:{quote('IN_NEIGHBOURHOOD')}]->(a)",
                {"branch_key": branch_key, "area_key": area_key},
            )
            area_links["IN_NEIGHBOURHOOD"] += 1

        ward_name = str(get_value(branch, "WardName", "Ward Name") or "").strip()
        ward_no = str(get_value(branch, "WardNo", "Ward No", "WardNumber") or "").strip()
        if ward_name or ward_no:
            area_key = ward_no or norm(ward_name)
            connection.execute(
                f"MERGE (a:{quote('LibraryWard')} {{area_key: $area_key}}) "
                "ON CREATE SET a.name = $name, a.ward_no = $number",
                {"area_key": area_key, "name": ward_name or f"Ward {ward_no}", "number": ward_no or None},
            )
            connection.execute(
                f"MATCH (b:{quote('BranchGeneralInformation')}), (a:{quote('LibraryWard')}) "
                "WHERE b._libraryto_source_key = $branch_key AND a.area_key = $area_key "
                f"MERGE (b)-[:{quote('IN_WARD')}]->(a)",
                {"branch_key": branch_key, "area_key": area_key},
            )
            area_links["IN_WARD"] += 1

        for field, display in SERVICES.items():
            if not truthy(get_value(branch, field)):
                continue
            service_key = norm(field)
            connection.execute(
                f"MERGE (s:{quote('LibraryService')} {{service_key: $service_key}}) "
                "ON CREATE SET s.service_name = $service_name",
                {"service_key": service_key, "service_name": display},
            )
            connection.execute(
                f"MATCH (b:{quote('BranchGeneralInformation')}), (s:{quote('LibraryService')}) "
                "WHERE b._libraryto_source_key = $branch_key AND s.service_key = $service_key "
                f"MERGE (b)-[:{quote('OFFERS_SERVICE')}]->(s)",
                {"branch_key": branch_key, "service_key": service_key},
            )
            area_links["OFFERS_SERVICE"] = area_links.get("OFFERS_SERVICE", 0) + 1

        # A public washroom is a facility flag; parking remains a numeric
        # directory attribute and is not converted into a yes/no relationship.
        if truthy(get_value(branch, "PublicWashroom")):
            connection.execute(
                f"MERGE (f:{quote('LibraryFacility')} {{facility_key: 'publicwashroom'}}) "
                "ON CREATE SET f.facility_name = 'Public washroom'"
            )
            connection.execute(
                f"MATCH (b:{quote('BranchGeneralInformation')}), (f:{quote('LibraryFacility')}) "
                "WHERE b._libraryto_source_key = $branch_key AND f.facility_key = 'publicwashroom' "
                f"MERGE (b)-[:{quote('HAS_FACILITY')}]->(f)", {"branch_key": branch_key})
            area_links["HAS_FACILITY"] = area_links.get("HAS_FACILITY", 0) + 1

    counts.update(area_links)

    # Link derived neighbourhood nodes to the imported neighbourhood geography
    # records when the existing CSV exposes a recognizable name or number key.
    geography_props = label_properties(connection, "Neighbourhoods")
    name_key = next((key for key in geography_props if norm(key) in {"nbhdname", "neighbourhoodname", "neighbourhood", "neighborhood", "areaname", "areanameng", "areanamelong"}), None)
    number_key = next((key for key in geography_props if norm(key) in {"nbhdno", "neighbourhoodno", "neighbourhoodnumber", "areanumber", "areano", "areacode", "arealongcode", "areashortcode"}), None)
    geography_predicates = []
    if name_key:
        geography_predicates.append(
            f"toLower(toString(a.{quote('name')})) = toLower(toString(g.{quote(name_key)}))"
        )
    if number_key:
        geography_predicates.append(
            f"toLower(toString(a.{quote('neighbourhood_no')})) = toLower(toString(g.{quote(number_key)}))"
        )
    if geography_predicates:
        connection.execute(
            f"MATCH (a:{quote('LibraryNeighbourhood')}), (g:{quote('Neighbourhoods')}) "
            f"WHERE {' OR '.join(geography_predicates)} "
            f"MERGE (a)-[:{quote('HAS_GEOGRAPHY_RECORD')}]->(g)"
        )
        rows = connection.execute(
            f"MATCH ()-[r:{quote('HAS_GEOGRAPHY_RECORD')}]->() RETURN count(r) AS count"
        ).fetchall()
        counts["HAS_GEOGRAPHY_RECORD"] = int((rows[0].get("count") or 0) if rows else 0)
    else:
        counts["HAS_GEOGRAPHY_RECORD"] = 0
    connection.commit()
    return counts


def import_and_build(path: Path) -> dict[str, int]:
    import relate

    datasets = {filename: read_csv(DATA / filename) for filename, _ in SOURCES}
    connection = relate.connect(database=str(path), read_only=False)
    try:
        total_nodes = 0
        for filename, label in SOURCES:
            rows = datasets[filename]
            total_nodes += _run_many(connection,
                f"CREATE (n:{quote(label)} $props)", [{"props": row} for row in rows])
            print(f"Imported {len(rows):,} {label} nodes")
        relationship_counts = build_relationships(connection, datasets)
        connection.commit()
        print(f"Imported {total_nodes:,} nodes and created relationship types: {relationship_counts}")
        return relationship_counts
    finally:
        connection.close()


def validate_store(path: Path) -> dict[str, int]:
    import relate
    connection = relate.connect(database=str(path), read_only=True)
    try:
        relationships = [str(row.get("relationshipType")) for row in connection.execute(
            "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType"
        ).fetchall() if row.get("relationshipType")]
        expected = {"HAS_CIRCULATION_RECORD", "HAS_VISITS_RECORD", "HAS_WORKSTATION_RECORD", "HAS_REGISTRATION_RECORD", "IN_NEIGHBOURHOOD", "IN_WARD", "OFFERS_SERVICE"}
        missing = expected.difference(relationships)
        if missing:
            raise RuntimeError(f"Graph validation failed; missing relationship types: {sorted(missing)}")
        counts = {}
        for rel_type in relationships:
            rows = connection.execute(f"MATCH ()-[r:{quote(rel_type)}]->() RETURN count(r) AS count").fetchall()
            counts[rel_type] = int((rows[0].get("count") or 0) if rows else 0)
        for rel_type in expected:
            if counts.get(rel_type, 0) <= 0:
                raise RuntimeError(f"Graph validation failed; {rel_type} has no relationships.")
        return counts
    finally:
        connection.close()


def main() -> int:
    if not DATA.is_dir():
        raise SystemExit("Run this script from a complete LibraryTO checkout.")
    for filename, _ in SOURCES:
        if not (DATA / filename).is_file():
            raise SystemExit(f"Missing required data/{filename}; no graph changes were made.")
    with tempfile.TemporaryDirectory(prefix="libraryto-relate-", dir=DATA) as temp:
        staging = Path(temp) / "tpl_library_graph.rebuild.rl"
        counts = import_and_build(staging)
        verified = validate_store(staging)
        backup = Path(tempfile.gettempdir()) / "tpl_library_graph.pre-relationships.bak"
        if DEST.exists():
            shutil.copy2(DEST, backup)
        os.replace(staging, DEST)
        print(f"\nValidated graph relationships: {verified}")
        print(f"Replaced {DEST.relative_to(ROOT)}")
        if backup.exists():
            print(f"Original store backed up outside the repository at {backup}.")
        print("Graph build completed. Restart the application before testing Q&A or the Relate Explorer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
