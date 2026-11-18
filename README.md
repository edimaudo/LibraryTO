# LibraryTO

LibraryTO is a responsive web application for exploring Toronto Public Library branch information, annual activity, reported services, connected branch information and upcoming programs. It is designed for residents and other non-technical users. It does not rank branches or label branches as overperforming or underperforming.

## Technology

- Python 3.12 and FastAPI
- Jinja2 templates
- Vanilla JavaScript and CSS
- Plotly.js for interactive, responsive charts
- Leaflet for branch maps
- Relate embedded graph database through `relate-db`
- CSV deployment snapshots and one Relate `.rl` database in `data/`
- Vercel Python Functions
- Statsmodels ARIMA for branch-level forecasts

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

There is one FastAPI application in the root `main.py`. The `app/` directory contains supporting services only. All six CSV files and the Relate database are stored directly in the single `data/` directory.

## Local development

Use Python 3.12.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
uvicorn main:app --reload
```

Open `http://127.0.0.1:8000`.

Add the seven data assets using the exact filenames above, then run:

```bash
python scripts/validate_data.py
python -m pytest -q
```

## Source files and data rules

The required files are:

1. `tpl_library_graph.rl`
2. `tpl-branch-general-information.csv`
3. `tpl-circulation-annual-by-branch.csv`
4. `tpl-visits-annual-by-branch.csv`
5. `tpl-workstation-usage-annual-by-branch.csv`
6. `tpl-card-registrations-annual-by-branch.csv`
7. `tpl-events-feed.csv`

CSV field matching is case-insensitive and normalizes spaces, underscores and punctuation. The actual CSV schemas must be validated against the files supplied for deployment.

### Physical branch inclusion

The branch information file is the authoritative branch list. LibraryTO includes physical branches only. Any row with `PhysicalBranch = 0` (including equivalent false values such as `false` or `no`) is excluded. Metric observations with `PhysicalBranch = 0` are also excluded. Metric rows must additionally match a branch code in the eligible physical-branch directory. Event-feed records explicitly marked non-physical are excluded, and events carrying a branch code must match an eligible physical branch.

The expected eligible branch count is 100. The validator checks this count after physical-branch filtering. This is a validation expectation, not a hard-coded truncation: the application does not arbitrarily discard branches to force the total to 100.

The same eligible branch set is used for overview totals, annual trends, branch histories, forecasts, branch comparisons, map pins, exports, branch search, branch-linked programs and Relate graph retrieval. Graph records explicitly marked `PhysicalBranch = 0` are excluded, as are graph records carrying a branch code outside the eligible physical-branch directory. A non-physical location cannot leak into these views by appearing in a metric file or connected graph record.

### Metric definitions and calculations

- **Circulation:** annual circulation values as reported in the source dataset.
- **Visits:** annual visit counts as reported. They are not interpreted as unique people.
- **Workstation sessions:** annual workstation-use session values as reported.
- **Card registrations:** annual registration values as reported. They are not treated as active-card counts.
- **Network totals:** each metric is summed over eligible physical branches for that metric's latest available reporting year. The app does not add multiple years together into one total.
- **Duplicate records:** duplicate branch/metric/year rows are consolidated before network aggregation. The last row encountered for a duplicate key is used; review the source data if duplicate records have conflicting values.
- **Missing observations:** blank branch-year values remain missing. The app does not substitute zero for a missing observation.
- **Comparisons:** compare selected branches over the reporting years supplied in the dataset. Missing years remain blank; no rankings or performance scores are calculated.
- **Service tiers:** DL = District Library; NL = Neighbourhood Library; RR = Research & Reference Library.
- **Branch characteristics:** address, postal code, service tier, square footage, workstation count and reported services are shown as supplied. Square footage is not treated as full service capacity.

### Forecasts

Branch forecasts use an ARIMA model fitted to each metric's annual history. A small set of ARIMA orders is evaluated using AIC; the lowest-AIC model that fits successfully is used. The app displays estimates for 2025 and 2026 only, and does not extend the forecast beyond 2026. At least six consecutive annual observations are required. If years are missing within the historical sequence or the model cannot be fitted, the forecast is not displayed rather than filling gaps with invented values.

Forecasts are estimates, not guaranteed outcomes. They are presented with plain-language year/value labels rather than model diagnostics. Results should be reviewed against actual data once those years are available.

### Programs and events

The event finder uses only metadata in `tpl-events-feed.csv`: interest terms, audience, language, program type, branch, date, start time, end time and registration status. Results are sorted by matching preferences and then event start time. An event is treated as open for registration only when the source feed explicitly provides an open/available status. The app does not infer attendance, popularity, demand, satisfaction or program effectiveness.

The event feed must contain current, future-dated events for the program finder to return upcoming programs. An older snapshot can correctly result in no upcoming events.

### Relate graph

`requirements.txt` installs `relate-db`; Python imports it as `relate`. The app opens `data/tpl_library_graph.rl` directly in read-only mode. No API URL, API key, database ID, remote service or Relate server is required.

The adapter inspects labels, relationship types and node properties in the supplied graph. User-entered questions are used to search discovered graph properties; values are passed as query parameters and arbitrary user-written Cypher is not executed. The interface shows a concise answer first. Supporting graph details are available on demand rather than exposing raw properties as the default answer.

The graph is not created, seeded, written, mutated or checkpointed by LibraryTO. Its actual schema is discovered at runtime rather than assumed from a proposed model.

## Caching and deployment data lifecycle

- Each CSV is read once and cached in memory per application process.
- Normalized branch records, observations, events, status information, overview calculations, branch histories, forecasts, event options, comparisons and event results are cached in-process.
- The browser caches successful GET responses for five minutes. Read-only JSON responses also include short-lived HTTP cache headers.
- The data files are immutable deployment snapshots. To refresh data, replace the files in `data/` and redeploy. No runtime writes are required or treated as persistent storage.
- Vercel functions may start more than one process or instance; process caches are local to each instance and are not a shared database cache.

## User experience and accessibility

- Responsive layouts support desktop, tablet and mobile widths. Branch selection and comparison selection do not depend on desktop keyboard shortcuts.
- Overview, branch history, forecasts and comparison charts use interactive Plotly charts with hover values, zoom/pan and image export. Each chart also has an optional data table.
- Branch pins open detail popups. A collapsed table provides an alternative to the map.
- Branch Insights uses keyboard-operable tabs and a searchable branch picker.
- Light and dark modes use the same control dimensions. Text and interface scaling supports Small (0.75×), Medium (1.0×) and Large (1.25×), with minimum target sizes retained.
- The interface uses semantic landmarks, labels, visible keyboard focus, status announcements for dynamic results, reduced-motion support and dark-mode contrast adjustments.

The interface is designed against WCAG 2.2 AA practices, but no conformance claim is made without a manual audit using keyboard-only navigation, screen readers, browser zoom/reflow, contrast measurement and representative mobile devices. Plotly and Leaflet output should also be included in that audit.

## Application URLs

The web app uses descriptive resource-based paths. No route contains an `/api` prefix.

- Pages: `/`, `/branch-insights`, `/comparisons`, `/programs-events`
- Overview data: `/overview`
- Branch directory and profiles: `/branches`, `/branches/{code}`, `/branches/{code}/forecasts`
- Branch comparison data: `/comparisons/data`
- Event filter options and recommendations: `/events/options`, `/events/recommendations`
- Search and branch questions: `/search`, `/ask`
- Application status: `/status`, `/health`
- CSV downloads: `/exports/observations.csv`, `/exports/branches.csv`, `/exports/comparisons.csv`, `/exports/events.csv`

HTML pages are served as HTML. Data routes return JSON where needed. CSV export routes return downloadable files.

## Vercel deployment

The project retains the deployment configuration supplied for LibraryTO in `vercel.json`:

```json
{
  "version": 2,
  "builds": [
    {
      "src": "main.py",
      "use": "@vercel/python",
      "config": {
        "maxDuration": 300,
        "memory": 1024,
        "includeFiles": "data/**"
      }
    }
  ],
  "rewrites": [
    {
      "source": "/(.*)",
      "destination": "main.py"
    },
    {
      "source": "/(.*)",
      "destination": "main.py"
    }
  ]
}
```

Keep `main.py`, `vercel.json`, `requirements.txt`, `app/`, `templates/`, `static/` and `data/` at the project root. The two rewrite entries are retained exactly as specified. The `includeFiles` setting bundles the graph and CSV source snapshots with the Python function. The Relate file is opened read-only; do not rely on writes to the Vercel function filesystem.

## Scope exclusions

LibraryTO does not use population datasets, neighbourhood polygons or neighbourhood service-coverage analysis. It does not evaluate branch performance, rank branches, infer unique visitors, or claim program effectiveness from event metadata.

## Verification boundary

The current source archive does not contain your six CSV files or `tpl_library_graph.rl`. Automated tests therefore use controlled CSV fixtures and a mocked Relate client. The actual source column mappings, the 100-branch count, graph schema and Q&A retrieval, event-feed freshness, forecast suitability and browser-level accessibility must be verified after the real data assets are added.
