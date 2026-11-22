# LibraryTO data directory

This directory contains the seven supplied CSV snapshots and the persistent Relate graph used by LibraryTO. No external data source is required by the application or graph builder.

## Source files

| Asset | Filename |
|---|---|
| Persistent Relate store | `tpl_library_graph.rl` |
| Branch directory | `tpl-branch-general-information.csv` |
| Annual circulation | `tpl-circulation-annual-by-branch.csv` |
| Annual visits | `tpl-visits-annual-by-branch.csv` |
| Annual workstation usage | `tpl-workstation-usage-annual-by-branch.csv` |
| Annual card registrations | `tpl-card-registrations-annual-by-branch.csv` |
| Programs and events | `tpl-events-feed.csv` |
| Neighbourhood geography | `tpl-Neighbourhoods.csv` |

Keep these filenames unchanged. Application data loading and graph-building scripts expect them directly under `data/`.

## Relate graph

`tpl_library_graph.rl` is a persistent single-file Relate store. The application opens it in read-only mode. It contains CSV-derived nodes and typed relationships connecting eligible physical branches to annual observations, events, neighbourhoods, wards, services and facilities.

The original `Load_relate_db.ipynb` records the initial CSV-to-node import. The current connected graph is rebuilt from the same seven CSV snapshots by running, from the repository root:

```bash
python scripts/build_relate_graph.py
python scripts/validate_relate_graph.py
```

The builder creates and validates a staging `.rl` file before replacing the persistent store. Stop the application before rebuilding so the single-file store is not open by another process.

CSV snapshots are read locally and cached by the application. There are no live API calls or external data refreshes. Rebuild the graph after changing any source snapshot, then commit the regenerated `tpl_library_graph.rl` with the matching CSV changes.


## Graph relationships

The node-only import notebook documents the original CSV load. The judging graph is rebuilt from those same CSV files by `../scripts/build_relate_graph.py`. This creates typed relationships from the existing `BranchCode`, ward, neighbourhood, service, facility and event fields. No external data source is used.
