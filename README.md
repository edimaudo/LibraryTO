# LibraryTO

**LibraryTO turns Toronto Public Library's existing branch, activity and program records into an explorable municipal library intelligence graph.**

## Use case

LibraryTO helps library leaders, municipal planners, researchers and the public understand how Toronto Public Library's physical branches are distributed, what services they report, how annual activity changes, and how locations compare with one another.

The project works with the CSV snapshots already included in this repository. It does not call external data providers, scrape additional information or depend on another database service.

The relationships that matter are the connections between a physical branch and its annual activity, programs, neighbourhood, ward, services and facilities. These connections support questions such as:

- Which branches in a particular ward offer a Digital Innovation Hub?
- Which other branches share a selected branch's neighbourhood?
- How does annual circulation compare across branches in the same ward?
- Which annual records and services are connected to this branch?

## How it uses Relate

- **Mode:** Single-file Relate store.
- **Persistent store:** `data/tpl_library_graph.rl`.
- **Why this mode:** Relate runs embedded in the Python application, so there is no separate graph server to install or operate. The single-file store is committed with the repository and can be inspected by judges after cloning. The running application opens it read-only. A rebuild script is supplied for maintainers to regenerate the graph from the repository's CSV snapshots.
- **What the graph models:** CSV-derived branch directory records, annual circulation, visits, workstation-usage and card-registration observations, program/event records, and neighbourhood geography records. Additional relationship nodes for neighbourhoods, wards, services and facilities are derived from the branch directory in the supplied snapshots.
- **Relationships:**
  - `HAS_CIRCULATION_RECORD`, `HAS_VISITS_RECORD`, `HAS_WORKSTATION_RECORD` and `HAS_REGISTRATION_RECORD` connect a branch to its corresponding annual records using the source `BranchCode`.
  - `HOSTS_EVENT` connects a branch to an event-feed row when the row contains a matching `BranchCode` or an unambiguous branch location/name.
  - `IN_NEIGHBOURHOOD` and `IN_WARD` connect a branch to neighbourhood and ward nodes derived from `NBHDNo`, `NBHDName`, `WardNo` and `WardName` in the branch directory.
  - `OFFERS_SERVICE` connects a branch to service nodes derived from the existing service flags, including Kids Stop, Leading Reading, Community-led services, Digital Innovation Hub, Teen Council, Youth Hub and Adult Literacy Program.
  - `HAS_FACILITY` connects a branch to a public-washroom facility node when the source flag is true. Numeric parking counts remain branch properties rather than being converted to a yes/no flag.
  - `HAS_GEOGRAPHY_RECORD` links a derived neighbourhood to a supplied neighbourhood geometry record when an unambiguous name/number key exists in that CSV.

The graph build is reproducible from the committed CSV snapshots: it creates a staging single-file store and uses `MERGE` for typed relationships. The script validates the new graph before replacing the committed store. The original node-only import notebook is retained as a record of the first import; `scripts/build_relate_graph.py` is the complete graph build used by this submission. No additional data source is used.

### Graph-powered application features

- **Overview:** network-wide questions, branch rankings across the full available reporting period, per-metric Top 10/Bottom 10 cumulative rankings, one year-specific annual activity-versus-branch-size chart inside each metric subtab, the Relate Explorer and activity per 1,000 square feet.
- **Branch Insights:** branch-scoped questions that traverse to the selected branch's ward/neighbourhood and related peer branches, the Relate Explorer for the selected branch, and annual activity intensity by year.
- **Branch Comparisons:** comparison of selected branches, exploration of each selected branch's connected records, and normalized activity comparisons.

The Relate Explorer is available from Overview, Branch Insights and Branch Comparisons. It exposes node labels and counts, relationship types and counts, the selected branch node and its source properties, and up to 5,000 directly connected records for the selected branch. Each connected record can be expanded to inspect its underlying properties and relationship type. It is read-only and uses the same committed graph that powers Q&A.

## Setup and run

### Prerequisites

- Python 3.12 (Python 3.9+ is required by the Relate Python package; use the project's supported Python 3.12 runtime for the application).
- Git and a local checkout of this public repository.

### Install

From the repository root:

```bash
python3.12 -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

### Rebuild the graph with explicit relationships

The repository's `data/Load_relate_db.ipynb` documents the original CSV-to-node import. The connected graph used by the current application is built by the following script (also demonstrated in `data/Build_relate_relationships.ipynb`):

```bash
python scripts/build_relate_graph.py
python scripts/validate_relate_graph.py
```

The builder reads only the seven CSV files already in `data/`, creates a staging `.rl` file, validates its nodes and relationship types, then replaces `data/tpl_library_graph.rl`. It saves the prior graph as `tpl_library_graph.pre-relationships.bak` in the operating system's temporary directory. Stop the application before rebuilding so the single-file store is not open elsewhere.

### Start the application

```bash
uvicorn main:app --reload
```

Open `http://127.0.0.1:8000`.

### First result to try

1. Open **Overview** and ask: `What branch had the highest annual circulation?` A yearless ranking compares all available branch-year records, identifies the highest single-year observation and shows the leading branch for each reporting year. Add a year to restrict the result, for example: `What branch had the highest annual circulation in 2024?`
2. Ask: `Which branches in Ward 1 offer a Digital Innovation Hub?` to exercise a ward-to-branch-to-service traversal.
3. Open **Branch Insights**, select a branch and ask: `Which other branches share this neighbourhood?` or `Which other branches offer the same services as this branch?`
4. Open **Branch Comparisons**, select two or more branches and use **Relate Explorer** to inspect each branch's node properties, connected annual observations, ward, neighbourhood, services and events. Expand a connected record to inspect its stored values.
5. In the **Branch analysis** metric tabs, compare Top 10/Bottom 10 cumulative rankings with the selected year's annual activity-versus-branch-size scatter plot. Use the activity-intensity panel to compare annual activity per 1,000 square feet.

## Where the data lives

All source snapshots and the persistent Relate store are in the repository's `data/` directory:

| File | Contents |
|---|---|
| `data/tpl_library_graph.rl` | Persistent single-file Relate graph used by the application |
| `data/tpl-branch-general-information.csv` | Branch directory, physical-branch flags, addresses, service flags, floor area, neighbourhood, ward and present-site year |
| `data/tpl-circulation-annual-by-branch.csv` | Annual circulation by branch |
| `data/tpl-visits-annual-by-branch.csv` | Annual visits by branch |
| `data/tpl-workstation-usage-annual-by-branch.csv` | Annual workstation sessions by branch |
| `data/tpl-card-registrations-annual-by-branch.csv` | Annual card registrations by branch |
| `data/tpl-events-feed.csv` | Programs and events feed |
| `data/tpl-Neighbourhoods.csv` | Neighbourhood geography records |
| `data/Load_relate_db.ipynb` | Original CSV-to-Relate node import notebook |

The application excludes records explicitly marked `PhysicalBranch = 0` from physical-branch analysis and only associates annual metric records with eligible physical branch codes. The `PresentSiteYear` field refers to the current site, not necessarily the original founding date of the library service.

## Activity intensity

LibraryTO calculates annual activity per 1,000 square feet using the existing annual measure and branch floor-area fields:

\[
\text{Activity per 1,000 sq ft} = \frac{\text{Annual activity}}{\text{Branch square footage}} \times 1,000
\]

The network-level rate uses total annual activity divided by the combined floor area of branches with a reported value for that year. Branch-level rates are available in Overview, Branch Insights and Branch Comparisons. The Overview Branch analysis tabs also show one year-specific activity-versus-branch-size scatter plot for the selected metric. This is a size-normalized activity measure; it is not a measure of operational efficiency or service quality.

## Verification

```bash
python scripts/validate_data.py
python scripts/validate_relate_graph.py
python -m pytest -q
```

The status endpoint reports dataset and graph readiness:

```bash
curl http://127.0.0.1:8000/status
```

The Relate Explorer data endpoint is available at `/relate/explorer`; activity intensity is available at `/activity-intensity`. Both endpoints use the application's local files and do not contact third-party data sources.

## Known data coverage

The supplied annual CSV snapshots currently end in 2024 for circulation, visits and card registrations, and 2023 for workstation sessions. There are no 2025 or 2026 annual observations in the supplied records, so LibraryTO does not claim to have measured activity or forecast accuracy for those missing years. A yearless highest/lowest annual metric question compares the full historical branch-year set rather than assuming that the latest available year is the answer. The forecast view remains a one-step estimate based on the historical observations that are actually available; additional backtesting for unavailable future periods is not part of this submission.

## Deployment

The FastAPI application is configured for Vercel Python Functions. The Relate file and source CSV snapshots are included through the existing `data/**` deployment configuration. The runtime opens the `.rl` file read-only; graph rebuilds are a local maintenance operation, followed by committing the regenerated store with the source update.
