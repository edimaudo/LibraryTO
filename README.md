# LibraryTO

LibraryTO is a web application to understand the Toronto Public Library Network.

## Technology

- Python 3.12 and FastAPI
- Jinja2 templates
- Vanilla JavaScript and CSS
- Plotly.js for interactive, responsive charts
- Leaflet for branch maps
- Relate embedded graph database through `relate-db`
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

## Local development

Use Python 3.12.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
uvicorn main:app --reload
```

Open `http://127.0.0.1:8000`.


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
- **Branch characteristics:** address, postal code, library type, year opened, service tier, square footage, workstation count, website, telephone and reported services are shown when supplied. Square footage is not treated as full service capacity.

### Overview analytics

The Overview includes these descriptive analyses, using eligible physical branches only:

- Four annual network trend charts: circulation, visitation, workstation usage and card registrations. Each chart has one metric title.
- Network-versus-service-tier trends compare network totals with DL, NL and RR annual totals. The tier breakdown also reports the number of branches with a value for each metric-year. A simple count of branches by tier is not presented as an analytical view.
- Eight metric-specific Top 10 and Bottom 10 charts, one pair for each annual metric. These are descriptive rankings for the selected reporting year, not overall branch ratings.
- Metric distributions for the selected year, shown as box plots by service tier. The plots expose medians, quartiles and outliers; they do not imply that an outlier is inherently positive or negative.
- Four annual metric-versus-square-footage scatter plots. X is square footage, Y is the selected annual metric, and colour indicates DL, NL or RR. Marker area is scaled to reported workstation count where available as a supplementary size variable; missing workstation counts use the minimum marker size.
- A four-metric correlation matrix. Each metric pair uses only observations with the same BranchCode and Year, and the hover value reports the matched branch-year sample size. Correlation is descriptive and does not establish causation.
- A visitation-versus-square-footage quadrant plot for the selected year. Median visitation and median square footage define the four relative groups. The labels describe visitation relative to branch area only; they are not holistic branch performance evaluations. The branch lists link to Branch Insights.
- A Toronto branch metric map. The selected metric and reporting year colour branch points by the observed value. Marker size reflects square footage. This is a point-based metric map, not an interpolated geographic heat surface. Branch records without valid coordinates are not plotted.

Metric values remain missing when no observation exists. They are not converted to zero for ranking, distribution, correlation, mapping or quadrant analysis.

### Service offering analysis

Reported branch service flags are normalized into branch service lists. Branch Insights displays a selected branch's reported services. Branch Comparisons presents a side-by-side matrix showing whether each selected service is reported for each selected branch. A service not recorded in the source is labelled as not listed; this does not prove that the branch does not offer it. The actual set of service fields must be checked against the supplied branch-information CSV.

### Event discovery analysis

The Programs & Events section summarizes the matching event-feed records by program type, audience, language and branch. Categorical selections for audience, language, program type and branch are filters. Interest remains a free-text relevance preference. Date, start time, end time and registration availability further constrain the result set. Counts and recommendations describe the feed snapshot only; they are not measures of attendance, popularity, demand or program effectiveness.

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
- The browser stores successful GET responses in session storage. Responses remain fresh for five minutes; for the following 25 minutes, a cached result is shown immediately while a refresh runs in the background. Cache keys include the application asset version and a revision derived from the source files' modification times and sizes, so a new application build or changed deployment snapshot invalidates old browser entries. Read-only JSON responses also include short-lived HTTP cache headers.
- Plotly and Leaflet JavaScript are loaded when charts and maps approach the viewport rather than blocking the initial page render. The app sends one combined `/overview` request for the overview metrics and branch directory.
- The data files are immutable deployment snapshots. To refresh data, replace the files in `data/` and redeploy. No runtime writes are required or treated as persistent storage.
- Vercel functions may start more than one process or instance; process caches are local to each instance and are not a shared database cache.

## User experience and accessibility

- Responsive layouts support desktop, tablet and mobile widths. Branch selection and comparison selection do not depend on desktop keyboard shortcuts.
- Overview, branch history, forecasts and comparison charts use interactive Plotly charts with hover values, zoom/pan and image export. Metric comparison tables are expandable and are shown once per metric. The Overview has no generic CSV export; downloads are available only where the dataset or applied filters are clear.
- Branch pins open detail popups with the library name, type, year opened, location, workstation count, area, reported services, telephone and website where those values are supplied. The branch table focuses the corresponding map marker rather than navigating to Branch Insights.
- Branch Insights uses a native branch dropdown and keyboard-operable tabs. Branch Comparisons supports up to five selected branches and uses tabs for annual metrics, branch information, services and locations. Each metric has one expandable annual data table.
- Light and dark modes use the same control dimensions. Text and interface scaling supports Small (0.75×), Medium (1.0×) and Large (1.25×), with minimum target sizes retained.
- The interface uses semantic landmarks, labels, visible keyboard focus, status announcements for dynamic results, reduced-motion support and dark-mode contrast adjustments.

The interface is designed against WCAG 2.2 AA practices, but no conformance claim is made without a manual audit using keyboard-only navigation, screen readers, browser zoom/reflow, contrast measurement and representative mobile devices. Plotly and Leaflet output should also be included in that audit.




