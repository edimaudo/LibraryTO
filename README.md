# LibraryTO

**Explore Toronto Public Library branches, annual activity, services, programs and connected neighbourhood context.**

LibraryTO uses the seven CSV snapshots already in `data/`. It does not query external data sources. Physical-branch records are used for branch analysis; records explicitly marked `PhysicalBranch = 0` are excluded.

## Relate graph

- **Mode:** Persistent single-file Relate database.
- **Store:** `data/tpl_library_graph.rl`.
- **Why:** A committed, local graph file is straightforward to run and inspect; the application opens it read-only.
- **Nodes:** Branches, annual circulation, visits, workstation sessions and card registrations, events, neighbourhood geography, wards, services and facilities.
- **Relationships:** `HAS_CIRCULATION_RECORD`, `HAS_VISITS_RECORD`, `HAS_WORKSTATION_RECORD`, `HAS_REGISTRATION_RECORD`, `HOSTS_EVENT`, `IN_NEIGHBOURHOOD`, `IN_WARD`, `OFFERS_SERVICE`, `HAS_FACILITY` and `HAS_GEOGRAPHY_RECORD`.

The application uses these edges for connected-context Q&A and the Branch Explorer in Branch Insights and Branch Comparisons. Branch Insights places Branch Explorer after Activity & Forecast and uses the branch selected in Find a branch. It identifies other branches connected through the same ward or neighbourhood, compares their reported services, and highlights services reported by local peers but not listed for the selected branch. Branch Comparisons provides a dedicated Branch Explorer subtab with pairwise shared neighbourhoods, wards and services, plus a service-coverage matrix for the selected branches. Annual observation records and program/event records are excluded from these explorer views. Branch properties and reported services remain in Branch Information. Overview and Programs & Events do not contain a graph explorer. All graph relationships and peer insights are derived from the existing CSV snapshots and their Relate graph connections.

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

Open `http://127.0.0.1:8000`. Try asking: `Which branches in Ward 1 offer a Digital Innovation Hub?` In Branch Insights, select a branch and open **Branch Explorer** after Activity & Forecast to inspect local peer branches and reported service coverage. In Branch Comparisons, select two or more branches and open the **Branch Explorer** subtab to compare shared areas, pairwise service overlap and service distribution.

## Validation

```bash
python scripts/validate_relate_graph.py
python scripts/validate_accessibility.py
python -m pytest -q
```

The source-level accessibility checks pass in this update. They do not replace manual browser testing with keyboard-only navigation, screen readers, zoom/reflow and mobile viewports; see `ACCESSIBILITY_VALIDATION.md`.

The annual CSV snapshots end in 2024 for circulation, visits and card registrations, and 2023 for workstation sessions. No 2025 or 2026 observations are inferred or fabricated.
