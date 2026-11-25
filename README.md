# LibraryTO

LibraryTO is a civic intelligence app designed to transform [Toronto Public Library (TPL)](https://tpl.ca/about-the-library/open-data/) open data into actionable operational insights.

## Key Features
- Overview
- Branch Insights
- Branch Comparisons
- Programs & Events

## Use Case
LibraryTO helps denizens and community partners understand how Toronto Public Library branches relate to the places they serve and the services they provide. The source data from [Toronto Public Library (TPL) open data](https://tpl.ca/about-the-library/open-data/). 

The key relationships are between a branch and its annual circulation, visit, workstation-use and card-registration records; the events hosted by a branch; the neighbourhood and ward in which it is located; and the services and facilities it provides. These connections support branch-level exploration, comparisons between branches, service-reach analysis and relationship-based Q&A. 

## Tech Stack
- Python
- FastAPI
- Jinja2
- CSS
- Relate
- Vercel

### How it uses Relate
- **Mode:** Single file. LibraryTO uses a persistent Relate database at `data/tpl_library_graph.rl` and opens it in-process through the `relate-db` Python package (`import relate`).
- **Why this mode:** A single persistent file gives the application one graph store to query. The web application opens graph connections in read-only mode, so its inspection and analytics requests do not modify the submitted store.
- **What the graph models:**
  - **Branch records** from Branch General Information, with `PhysicalBranch = 1` identifying the physical-branch directory used for branch-level rankings and peer analysis.
  - **Annual activity records** for circulation, visits, workstation usage and card registrations.
  - **Events**, **neighbourhoods**, **wards**, **reported services**, **facilities** and **geography records**.
  - **Relationships** including `HAS_CIRCULATION_RECORD`, `HAS_VISITS_RECORD`, `HAS_WORKSTATION_RECORD`, `HAS_REGISTRATION_RECORD`, `HOSTS_EVENT`, `IN_NEIGHBOURHOOD`, `IN_WARD`, `OFFERS_SERVICE`, `HAS_FACILITY` and `HAS_GEOGRAPHY_RECORD`.

The graph is used by connected-context Q&A, Branch Insights and Branch Comparisons. It supports finding branches in the same neighbourhood or ward, comparing reported services across selected branches, and exploring how widely a reported service is distributed. These are measures of recorded coverage and connectivity, not measures of service quality, demand or community outcomes.

Judges can inspect the live graph through **Overview → Library Network Explorer**:

1. Confirm the **Relate connected** runtime status and the persistent store filename.
2. Use **Graph Structure** to inspect the node labels, node counts, relationship types and relationship counts queried from the store.
3. Use **Browse Nodes** to search graph records and inspect their stored source properties.
4. Ask a relationship-based question in Q&A, such as `Which branches in Ward 1 offer a Digital Innovation Hub?`.
5. Explore connected peers and service context in **Branch Insights → Branch Explorer** and **Branch Comparisons → Branch Explorer**.

For direct inspection, the same store can be opened with the Relate CLI from the repository root:

```bash
relate info --database data/tpl_library_graph.rl
relate query --database data/tpl_library_graph.rl --read-only
```

At the `cypher>` prompt, `.info` displays store information. These read-only queries inspect physical-branch records and traverse their stored relationships:

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

## Setup and run

**Prerequisites:** Python 3.12, the project source and CSV files, and the persistent Relate store. Run these commands from the repository root.

Create and activate a virtual environment, then install the project dependencies and Relate client:

```bash
python3.12 -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pip install relate-db
```

If the persistent graph store has not yet been created, or the graph needs to be rebuilt after changing its model or source data, run the repository's one-time graph builder:

```bash
python scripts/build_relate_graph.py
```

Then start the application:

```bash
uvicorn main:app --reload
```

Open `http://127.0.0.1:8000`. For a first result, open **Overview → Library Network Explorer** and confirm that it reports **Relate connected**. Then try the Q&A question `Which branches in Ward 1 offer a Digital Innovation Hub?`, or open **Branch Insights**, select a branch using **Find a branch**, and inspect its **Branch Explorer** relationships.

To run the project's validation checks:

```bash
python scripts/validate_relate_graph.py
python scripts/validate_accessibility.py
python -m pytest -q
```

## Where the data lives

The persistent Relate graph store is:

```text
data/tpl_library_graph.rl
```

The graph is built from the seven CSV snapshots in `data/`:

```text
data/tpl-branch-general-information.csv
data/tpl-circulation-annual-by-branch.csv
data/tpl-visits-annual-by-branch.csv
data/tpl-workstation-usage-annual-by-branch.csv
data/tpl-card-registrations-annual-by-branch.csv
data/tpl-events-feed.csv
data/tpl-Neighbourhoods.csv
```

The application queries `data/tpl_library_graph.rl` directly; it does not substitute a JSON export or an in-memory mock graph. Keep the `.rl` file alongside the source data when reproducing the project. The annual CSV snapshots end in 2024 for circulation, visits and card registrations, and in 2023 for workstation sessions; the application does not infer or fabricate later observations.
