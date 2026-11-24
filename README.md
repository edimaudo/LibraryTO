# LibraryTO

**Explore Toronto Public Library branches, annual activity, services, programs and connected neighbourhood context.**

LibraryTO uses the seven CSV snapshots already in `data/`. It does not query external data sources. Physical-branch records are used for branch analysis; records explicitly marked `PhysicalBranch = 0` are excluded.

## Relate graph

- **Mode:** Persistent single-file Relate database.
- **Store:** `data/tpl_library_graph.rl`.
- **Why:** A committed, local graph file is straightforward to run and inspect; the application opens it read-only.
- **Nodes:** Branches, annual circulation, visits, workstation sessions and card registrations, events, neighbourhood geography, wards, services and facilities.
- **Relationships:** `HAS_CIRCULATION_RECORD`, `HAS_VISITS_RECORD`, `HAS_WORKSTATION_RECORD`, `HAS_REGISTRATION_RECORD`, `HOSTS_EVENT`, `IN_NEIGHBOURHOOD`, `IN_WARD`, `OFFERS_SERVICE`, `HAS_FACILITY` and `HAS_GEOGRAPHY_RECORD`.

The application uses these edges for connected-context Q&A and the Branch Explorer in Branch Insights and Branch Comparisons. Branch Insights uses the branch selected in Find a branch to identify peers in the same ward or neighbourhood, rank the closest local connections by shared graph relationships, and compare the reach of reported services across the peer group. Branch Comparisons shows pairwise shared neighbourhoods, wards and services, plus a service-coverage matrix. These are descriptive relationship measures, not service-quality or community-need scores. All insights are derived from the existing CSV snapshots and their Relate graph connections.

The **Graph Explorer** is a subtab within Overview and is the judge-facing graph inspection interface. It is read-only and uses the same committed single-file Relate store that powers Q&A. Its Graph Insights view summarizes relationship coverage across physical branches, ranks physical branch nodes by direct graph connections, and identifies neighbourhood and ward nodes connected to the largest numbers of physical branches. Graph Structure exposes node labels, node counts, relationship types and edge counts. Browse Nodes allows judges to search stored properties and expand records; the Branch General Information node type is strictly filtered to `PhysicalBranch = 1`. Branch Connections allows inspection of direct relationships and connected node properties for a selected physical branch. Branch-level graph counts, relationships and peer queries exclude records not marked `PhysicalBranch = 1`. `/relate/explorer` exposes graph structure, topology insights and selected physical-branch connections; `/relate/inspect` provides bounded, searchable node browsing, returning up to 100 nodes per request with support for additional result pages. This makes the persisted graph inspectable through the application rather than relying on an external database client.

Overview Q&A supports ordinal branch-history questions such as `What was the 5th branch to open?`. These are ranked using `PresentSiteYear`, which records the year of the current site, not necessarily when the library service first opened. Branches with the same recorded year are ordered alphabetically by branch name; the answer discloses this tie-handling rule.

## Application sections

- **Overview:** The **Branch Overview** tab groups annual metric rankings and the branch-area comparison under one **Reporting Year** selector. It defaults to **All Years**, which filters both the Top 10/Bottom 10 rankings and the annual activity-versus-area chart. The **Location** tab also defaults to **All Years**; map colours reflect cumulative reported activity across the available years.
- **Branch Insights:** **Branch Information** includes hours, public parking, neighbourhood, ward and reported services. **Activity & Forecast** combines the historical series and its forecast in one graph per measure. **Branch Explorer** uses the branch selected through **Find a branch** to identify same-area peer branches and compare reported service coverage.
- **Branch Comparisons:** **Branch Explorer** is a separate subtab. It shows pairwise shared neighbourhoods, wards and services, plus a reported-service matrix across the selected branches.

## Setup and run

Requires Python 3.12.

```bash
python3.12 -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
python -m pip install -r requirements-dev.txt
```

The source overlay does not replace the repository's CSV files or binary graph store. The previous graph import contained CSV-derived nodes but no explicit edges. **Run this one-time graph build after applying the overlay** to create the relationship model and replace `data/tpl_library_graph.rl` with the validated store:

```bash
python scripts/build_relate_graph.py
```

The builder reads only the seven committed CSV snapshots, creates a staging database, validates the expected relationship types and counts, and replaces the graph file only after validation succeeds. It also preserves a backup of the previous graph in the system temporary directory. Stop the application before running it.

Start the application:

```bash
uvicorn main:app --reload
```

Open `http://127.0.0.1:8000`. Try asking `Which branches in Ward 1 offer a Digital Innovation Hub?` or `What was the 5th branch to open?` (the latter is ranked by current-site year, not original service founding date). In Branch Insights, select a branch and open **Branch Explorer** to inspect local peers and reported service reach. Open the **Graph Explorer** subtab within **Overview** to inspect graph coverage insights, node labels, relationship counts, node properties and physical-branch connections stored in Relate.

## Validation

```bash
python scripts/validate_relate_graph.py
python scripts/validate_accessibility.py
python -m pytest -q
```

The source-level accessibility checks pass in this update. They do not replace manual browser testing with keyboard-only navigation, screen readers, zoom/reflow and mobile viewports; see `ACCESSIBILITY_VALIDATION.md`.

The annual CSV snapshots end in 2024 for circulation, visits and card registrations, and 2023 for workstation sessions. No 2025 or 2026 observations are inferred or fabricated.
