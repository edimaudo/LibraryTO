# LibraryTO

LibraryTO is a civic intelligence app designed to transform [Toronto Public Library (TPL) open data](https://tpl.ca/about-the-library/open-data/) into actionable operational insights.

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


## How it uses Relate

- **Mode:** Single-file database. LibraryTO uses a persistent Relate graph store at `data/tpl_library_graph.rl`, accessed in-process through the `relate-db` Python package. The application opens the graph in read-only mode.

- **Why this mode:** The central challenge LibraryTO addresses is that information about Toronto Public Library branches is spread across separate datasets. Looking at circulation, visits, events, geography and services independently provides only a partial picture of a branch and its role in the community.

  Relate allows LibraryTO to model the connections between these datasets directly. Instead of building separate joins for every feature or question, the application can traverse relationships from a branch to its activity records, neighbourhood, ward, events and services, and then follow those connections to other branches. This is particularly valuable for questions that require multiple steps. For example, identifying all branches in a particular ward that offer a Digital Innovation Hub involves connecting a ward to its branches and then those branches to their reported services.

  This relationship-first approach supports the Library Network Explorer, Branch Explorer, branch comparisons and relationship-based Q&A using a shared graph model. It also makes it easier to extend the application as additional datasets and relationships are introduced.

  A single-file store suits the application's architecture because it provides persistent graph data without requiring a separately operated database server. The application can query the same stored graph locally, with read-only access protecting the underlying data. The graph is generated from the supplied CSV snapshots using `scripts/build_relate_graph.py`.

- **What the graph models:** The graph represents Toronto Public Library's physical branches and their connections to operational, geographic and community information across seven CSV datasets:
  - **Physical branches:** Branch directory records, using `PhysicalBranch = 1` to identify physical library locations.
  - **Annual activity:** Circulation, visits, workstation usage and card registration records associated with individual branches.
  - **Programs and events:** Event records associated with the branches hosting them.
  - **Geography:** Neighbourhoods, municipal wards and available neighbourhood geography records.
  - **Services and facilities:** Reported branch services and facilities, represented as connected entities so the application can explore their distribution across the library network.

  These connections are represented through typed relationships, including `HAS_CIRCULATION_RECORD`, `HAS_VISITS_RECORD`, `HAS_WORKSTATION_RECORD`, `HAS_REGISTRATION_RECORD`, `HOSTS_EVENT`, `IN_NEIGHBOURHOOD`, `IN_WARD`, `OFFERS_SERVICE`, `HAS_FACILITY` and `HAS_GEOGRAPHY_RECORD`.

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

