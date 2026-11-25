# LibraryTO

**Explore Toronto Public Library branches, annual activity, services, programs and connected neighbourhood context.**

LibraryTO uses the seven CSV snapshots already in `data/`. It does not query external data sources. Physical-branch records are used for branch analysis; records explicitly marked `PhysicalBranch = 0` are excluded.

## Relate graph

- **Mode:** Persistent single-file Relate database, opened in-process through the official Python client (`relate-db`, imported as `relate`).
- **Store:** `data/tpl_library_graph.rl`.
- **Why:** A committed, local graph file is straightforward to run and inspect; the application opens it read-only.
- **Runtime proof:** The Library Network Explorer queries the store through the embedded Relate engine. A successful response displays **Relate connected** and the store filename; the message is rendered only after the store opens and its graph queries succeed.
- **Nodes:** Branches, annual circulation, visits, workstation sessions and card registrations, events, neighbourhood geography, wards, services and facilities.
- **Relationships:** `HAS_CIRCULATION_RECORD`, `HAS_VISITS_RECORD`, `HAS_WORKSTATION_RECORD`, `HAS_REGISTRATION_RECORD`, `HOSTS_EVENT`, `IN_NEIGHBOURHOOD`, `IN_WARD`, `OFFERS_SERVICE`, `HAS_FACILITY` and `HAS_GEOGRAPHY_RECORD`.

The application uses these edges for connected-context Q&A and the Branch Explorer in Branch Insights and Branch Comparisons. Branch Insights uses the branch selected in Find a branch to identify peers in the same ward or neighbourhood, rank the closest local connections by shared graph relationships, and compare the reach of reported services across the peer group. Branch Comparisons shows pairwise shared neighbourhoods, wards and services, plus a service-coverage matrix. These are descriptive relationship measures, not service-quality or community-need scores. All insights are derived from the existing CSV snapshots and their Relate graph connections.

The **Library Network Explorer** is a subtab within Overview and is the judge-facing graph inspection interface. It uses the same committed single-file Relate store that powers Q&A. Graph Insights ranks the ten physical branches with the most direct relationships, the ten neighbourhoods and wards connected to the most physical branches, and the ten services with the widest physical-branch reach. Graph Structure exposes node labels, record counts, relationship types and edge counts. Browse Nodes is a record-level audit tool: judges can search a node type, inspect the stored source properties, and verify that relationships are backed by actual CSV-derived records. Branch General Information results are strictly filtered to `PhysicalBranch = 1`. All branch-level graph counts, rankings and peer queries exclude records not marked `PhysicalBranch = 1`. `/relate/explorer` exposes graph structure and topology insights; `/relate/inspect` provides bounded, searchable node browsing, returning up to 100 nodes per request with support for additional result pages. The graph connection details remain available to the backend for connected-context Q&A but are not presented as a separate Overview panel.

Overview Q&A supports ordinal branch-history questions such as `What was the 5th branch to open?`. These are ranked using `PresentSiteYear`, which records the year of the current site, not necessarily when the library service first opened. Branches with the same recorded year are ordered alphabetically by branch name; the answer discloses this tie-handling rule.

## Judge walkthrough and criteria alignment

Use this sequence to confirm that the submitted application is running against Relate:

1. Start LibraryTO and open **Overview → Library Network Explorer**. Confirm the **Relate connected** line names `tpl_library_graph.rl`.
2. Open **Graph Structure** to inspect the node labels, node counts, relationship types and relationship counts returned from the live store.
3. Open **Browse Nodes**, select **Branch General Information**, and inspect individual source properties. Search for a branch name and expand its record.
4. Ask `Which branches in Ward 1 offer a Digital Innovation Hub?` in Q&A. The answer should be grounded in the stored `IN_WARD` and `OFFERS_SERVICE` relationships.
5. Open **Branch Insights → Branch Explorer** for a selected branch, then **Branch Comparisons → Branch Explorer** to inspect the connected peer and service context across branches.
6. For direct store inspection, use the Relate CLI commands in **Inspect the Relate store directly** below.

The project maps to the judging criteria as follows:

- **Creativity:** Applies a property graph to a public-library network, joining branch records to service, geographic, event and annual-activity context rather than treating each CSV as an isolated report.
- **Relate and connected context:** Uses an on-disk `.rl` store and actual graph traversals for neighbourhood/ward peers, reported-service reach, branch comparisons and relationship-based Q&A. The explorer lets judges inspect the graph schema and stored node properties.
- **Functionality and completeness:** Includes annual branch rankings, branch-area analysis, mapping, branch-level insights, peer comparisons and natural-language questions over connected records.
- **Usefulness:** Supports library administrators, municipal analysts and community partners reviewing where reported services are present and how branches connect to neighbourhoods and wards. The measures are descriptive coverage, not proof of service quality, unmet demand or social outcomes.
- **Documentation and reproducibility:** Documents the data inputs, graph model, one-time graph build, local startup, judge walkthrough and direct inspection of the same persistent store.

## Application sections

- **Overview:** The **Branch Overview** tab groups annual metric rankings and the branch-area comparison under one **Reporting Year** selector. It defaults to **All Years**, which filters both the Top 10/Bottom 10 rankings and the annual activity-versus-area chart. The Top 10/Bottom 10 horizontal axis is labelled with the selected metric. The activity-versus-area chart aggregates each branch's reported values across the selected years; with All Years selected, it displays one cumulative point per branch and is titled, for circulation, **Annual Circulation And Branch Area - All**. The **Location** tab also defaults to **All Years**; map colours reflect cumulative reported activity across the available years.
- **Branch Insights:** **Branch Information** includes hours, public parking, neighbourhood, ward and reported services. **Activity & Forecast** combines the historical series and its forecast in one graph per measure. **Branch Explorer** uses the branch selected through **Find a branch** to identify same-area peer branches and compare reported service coverage.
- **Branch Comparisons:** **Branch Explorer** is a separate subtab. It shows pairwise shared neighbourhoods, wards and services, plus a reported-service matrix across the selected branches.

## Setup and run

Requires Python 3.12.

```bash
python3.12 -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
python -m pip install -r requirements-dev.txt
```

The source overlay does not replace the repository's CSV files or binary graph store. Install the Relate Python client explicitly if it is not already included in the project's dependency files:

```bash
python -m pip install relate-db
```

The previous graph import contained CSV-derived nodes but no explicit edges. **Run this one-time graph build after applying the overlay** to create the relationship model and replace `data/tpl_library_graph.rl` with the validated store:

```bash
python scripts/build_relate_graph.py
```

The builder reads only the seven committed CSV snapshots, creates a staging database, validates the expected relationship types and counts, and replaces the graph file only after validation succeeds. It also preserves a backup of the previous graph in the system temporary directory. Stop the application before running it.

Start the application:

```bash
uvicorn main:app --reload
```

Open `http://127.0.0.1:8000`. Try asking `Which branches in Ward 1 offer a Digital Innovation Hub?` or `What was the 5th branch to open?` (the latter is ranked by current-site year, not original service founding date). In Branch Insights, select a branch and open **Branch Explorer** to inspect local peers and reported service reach. Open the **Library Network Explorer** subtab within **Overview** to inspect the top connected physical branches, neighbourhood and ward hubs, service reach, node labels, relationship types and stored node properties.

### Inspect the Relate store directly

Judges can inspect the same persistent file used by the application, not a JSON export or a mock graph. From the repository root, run:

Install the [Relate CLI](https://github.com/relatedb/relate#install), then run:

```bash
relate info --database data/tpl_library_graph.rl
relate query --database data/tpl_library_graph.rl --read-only
```

At the `cypher>` prompt, run `.info` to see the store's node and relationship counts, then try these read-only queries:

```cypher
MATCH (b:BranchGeneralInformation)
WHERE toString(b.PhysicalBranch) = '1'
RETURN b.BranchCode, b.BranchName, b.PresentSiteYear
ORDER BY b.BranchName
LIMIT 25;

MATCH (b:BranchGeneralInformation)-[r]->(connected)
WHERE toString(b.PhysicalBranch) = '1'
RETURN b.BranchName, type(r) AS relationship, labels(connected) AS connected_node_type
LIMIT 50;
```

The first query inspects physical-branch source records. The second traverses actual stored edges from those branches. In the running app, **Library Network Explorer** exposes node and relationship counts, relationship types and searchable stored node properties. `GET /status` also returns the application's Relate status payload. The CLI commands open the same `.rl` file used by the app; `--read-only` prevents inspection from modifying it.

## Validation

```bash
python scripts/validate_relate_graph.py
python scripts/validate_accessibility.py
python -m pytest -q
```

The source-level accessibility checks pass in this update. They do not replace manual browser testing with keyboard-only navigation, screen readers, zoom/reflow and mobile viewports; see `ACCESSIBILITY_VALIDATION.md`.

The annual CSV snapshots end in 2024 for circulation, visits and card registrations, and 2023 for workstation sessions. No 2025 or 2026 observations are inferred or fabricated.
