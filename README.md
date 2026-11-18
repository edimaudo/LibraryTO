# LibraryTO

LibraryTO is an open-data intelligence application for the Toronto Public Library network. It brings together branch information, annual activity, service characteristics, connected graph evidence, and programs and events.

## Technology

- Python 3.12
- FastAPI
- Jinja2 templates
- Vanilla JavaScript and CSS
- Relate embedded graph database through `relate-db`
- CSV source snapshots and one Relate `.rl` graph in `data/`
- Vercel Python Functions

## Project structure

```text
LibraryTO/
├── app/
│   ├── services/
│   │   ├── analytics.py
│   │   ├── data_store.py
│   │   └── relate.py
│   └── config.py
├── data/
│   ├── tpl_library_graph.rl
│   ├── tpl-branch-general-information.csv
│   ├── tpl-circulation-annual-by-branch.csv
│   ├── tpl-visits-annual-by-branch.csv
│   ├── tpl-workstation-usage-annual-by-branch.csv
│   ├── tpl-card-registrations-annual-by-branch.csv
│   └── tpl-events-feed.csv
├── scripts/validate_data.py
├── static/css/app.css
├── static/js/app.js
├── templates/
├── tests/
├── main.py
├── requirements.txt
├── requirements-dev.txt
└── vercel.json
```

The seven data assets above belong directly in `data/`. There are no `source/` or `derived/` directories. The `.rl` graph and the six CSVs are separate source assets; the application does not generate either.

## Local development

Use Python 3.12.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
uvicorn main:app --reload
```

Open `http://127.0.0.1:8000`.

The application starts even if source files are not present, but the sections depending on missing data will show a clear empty state. Add your data files and run:

```bash
python scripts/validate_data.py
python -m pytest -q
```

## Relate integration

`requirements.txt` installs `relate-db`; Python imports it as `relate`. The application opens `data/tpl_library_graph.rl` directly in read-only mode. No API URL, API key, database ID, remote service or Relate server is required.

The adapter introspects labels, relationship types and node properties from the supplied graph. Branch graph Q&A uses parameterized Cypher built from that discovered schema. User-entered text is passed as a parameter; the application does not run arbitrary Cypher supplied by a user. The current Q&A implementation ranks matching graph nodes and displays their properties and connected evidence. It is deterministic graph retrieval, not LLM-generated prose.

The graph is opened read-only. LibraryTO does not create, seed, write, mutate or checkpoint `tpl_library_graph.rl`. The graph's actual labels and properties are discovered at runtime rather than assumed from a proposed schema.

## Data handling

The application expects these exact filenames:

1. `tpl_library_graph.rl`
2. `tpl-branch-general-information.csv`
3. `tpl-circulation-annual-by-branch.csv`
4. `tpl-visits-annual-by-branch.csv`
5. `tpl-workstation-usage-annual-by-branch.csv`
6. `tpl-card-registrations-annual-by-branch.csv`
7. `tpl-events-feed.csv`

CSV field matching is case-insensitive and normalizes spaces, underscores and punctuation. The validator checks required fields, but the actual CSV schemas still need to be checked against the files you provide. The event finder requires future-dated events in the feed; an old snapshot will correctly return no upcoming events.

CSV records are parsed once and cached in memory per running application process. On Vercel, the source files are bundled with the function. Replace the files and redeploy to refresh the deployment snapshot. The app does not depend on runtime writes for persistence.

## Application sections

### Overview

Network-wide latest-year totals for circulation, visits, workstation sessions and card registrations; annual trends; branch counts by service tier; source coverage; and an interactive branch map with an accessible branch-link alternative.

### Branch Insights

Branch directory and branch profile; reported characteristics and services; annual metric histories; a transparent baseline forecast when at least six annual observations exist; events associated with the branch; and graph-backed Q&A with returned evidence.

### Branch Comparisons

Side-by-side comparison of up to six selected branches across the available metric years, service tiers, square footage and workstation counts. Reporting-year filters, shareable selection URLs and CSV export are included. No branch rankings or performance scores are generated.

### Programs & Events

Upcoming-event discovery with audience, interest, language, type, branch/location, date, time and registration filters. Recommendations explain which metadata matched. Full or closed events can remain visible as alternatives; an event is only treated as registration-open when the feed explicitly indicates that status.

### Data & Methodology

Exact source filenames, row counts, reporting coverage, graph status, definitions and analysis limitations.

## Analytical safeguards

- A network total is calculated from each metric's latest available reporting year. The application does not add multiple years together into one misleading total.
- Visits are counts as reported by the source and are not called unique people.
- Metrics with different reporting years or branch coverage are not presented as directly equivalent.
- Blank branch-year observations remain blank in comparisons.
- Forecasts are point estimates from an interpretable linear-trend baseline and are displayed with an expanding-window backtest against a last-observation baseline. Six annual observations are required. This is not a causal model and does not imply a calibrated prediction interval.
- Square footage is descriptive and is not treated as full service capacity. Staffing, operating hours, maintenance and other capacity factors are not assumed.
- Event metadata does not establish attendance, demand, satisfaction or program effectiveness.
- Branches are not ranked or classified as overperforming or underperforming.
- Population data, neighbourhood polygons and neighbourhood service-coverage analysis are not used.

## Accessibility and interface

The interface uses Inter, responsive navigation, semantic page landmarks, keyboard-visible focus, reduced-motion support, accessible chart data tables, and a map link alternative. Light and dark themes are available. The global interface scale is Small (0.75×), Medium (1.0×) and Large (1.25×); controls retain a minimum interaction height. These design provisions do not constitute a formal WCAG 2.2 AA audit. Manual keyboard, screen-reader, contrast and zoom testing remains necessary.

## Vercel deployment

1. Commit the project and the seven data assets to the repository.
2. Import the repository into Vercel.
3. Use the Python 3.12 runtime.
4. Keep `main.py`, `vercel.json`, `requirements.txt`, `app/`, `templates/`, `static/` and `data/` at the project root as shown above.
5. Deploy. Vercel builds the root `main.py` with `@vercel/python` and rewrites incoming application paths to that entry point. The `app/` directory contains service modules and configuration only; it does not contain a second FastAPI application.

`vercel.json` explicitly includes `app/`, `templates/`, `static/` and `data/` in the Python function bundle. This is required because the app loads templates, static assets, CSV snapshots and the Relate graph at runtime.

The Relate graph and CSVs are included as deployment files. The application opens the graph read-only. Do not rely on writing updates to the Vercel function filesystem.

## Known verification boundary

The project workspace used to build this code did not contain the user's six CSV files or `tpl_library_graph.rl`. Tests therefore use representative CSV fixtures and a mocked Relate client. The actual field coverage, graph schema, graph query performance, forecast accuracy and event feed freshness must be validated after the real source assets are added.
