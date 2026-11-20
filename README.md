# LibraryTO — updated source overlay

This ZIP contains the updated application source files for the existing `edimaudo/LibraryTO` project. It is intended to be extracted over a fresh checkout of the repository's current `main` branch.

**This is an update overlay, not a self-contained data archive.** The existing `data/` directory is deliberately not included. Keep the repository's supplied CSV snapshots, `tpl_library_graph.rl`, templates, deployment configuration, and other unchanged project files. The update adds `app/services/relate_compare.py` and replaces the listed source files.

## Apply the update

1. Check out the existing `edimaudo/LibraryTO` repository.
2. Extract this ZIP into the repository root and allow the updated files to overwrite files with the same paths.
3. Keep the original `data/` directory in place.
4. Install the project's requirements and run the tests before deploying.

No Git branch is created by this package. No commit is pushed, and no Vercel deployment is triggered.

## Runtime and architecture

- Python 3.12, FastAPI and Jinja2
- Vanilla JavaScript and CSS; no Node build step
- Plotly for interactive charts
- Leaflet for physical branch maps
- `relate-db` for the embedded, read-only Relate graph
- Statsmodels ARIMA for one-step annual branch forecasts
- Vercel Python Functions for deployment

The existing graph is a Relate database. It is not Neo4j. The current graph import stores CSV rows as labelled nodes and does not create relationships. The updated comparison adapter reads annual metric nodes from Relate and joins them to the physical branch directory by `BranchCode`. If the graph file, client, or required annual metric nodes are unavailable, the comparison endpoint uses the filtered CSV snapshots instead of presenting an empty or fabricated graph result.

## Data rules and calculations

### Physical branches

The branch directory is the authoritative list. Any branch row explicitly marked `PhysicalBranch = 0` (including false-equivalent values) is excluded. Metric observations are accepted only when their `BranchCode` belongs to that physical-branch directory; a `PhysicalBranch = 0` field on a metric row is also excluded. Events with an explicit non-physical flag or an unmatched branch code are excluded. These rules apply to overview totals, branch histories, annual averages, rankings, correlations, comparisons, forecasts, map pins, branch search, branch-linked events and CSV endpoints.

The app does not truncate the directory to force a count. It uses every eligible physical branch present in the supplied branch snapshot.

### Overview

- Annual circulation, visitation, workstation usage and card registration network totals use each measure's latest available reporting year.
- Service-tier trends show District Library (DL), Neighbourhood Library (NL) and Research and Reference Library (RR), without an extra network series.
- Correlations use all matched branch-year pairs for each metric pair. The value `r` ranges from -1 to +1 and describes the direction and strength of a linear relationship; it does not establish causation.
- Top and bottom 10 rankings use each branch's average of its available annual values across all reporting years. Missing observations remain missing rather than being converted to zero.
- Annual-average metric-versus-floor-area charts use all available years for each branch and are coloured by the three service tiers.
- The visitation-versus-floor-area quadrant uses average annual visitation and reported floor area. Median splits define four relative groups. These groups describe the relationship between visitation and size, not overall branch quality or service capacity.
- The map displays physical branch pins. Selecting a metric and reporting year colours the pins by the reported value; pin size reflects reported floor area. Selecting a pin displays available branch attributes and reported services.

### Branch insights and forecasts

Branch Insights uses a searchable branch field and tabbed panels for branch information, activity, forecasts, questions and programs. Forecasts use an ARIMA model and produce one annual estimate after the latest available reporting year. At least six consecutive annual observations are required. If the history has gaps or a model cannot be fitted, the app displays a plain-language unavailable state rather than filling gaps or exposing model diagnostics.

The Relate question flow returns a concise answer and result summaries first. Supporting graph evidence remains collapsed by default.

### Programs and events

Audience, language, program type, branch, date, start time, end time and registration status are structured filters; interest is free text. Event timestamps are normalized to `YYYY-MM-DD HH:MM` when a time is supplied. An event is considered upcoming only if its start timestamp can be parsed and is today or later in the Toronto timezone. Invalid and past event timestamps are not presented as upcoming programs.

Event recommendations describe only the supplied event-feed metadata. They do not infer attendance, popularity, demand or program effectiveness.

## Performance, deployment and accessibility

- CSV files and derived calculations are cached in-process. Only the datasets needed by the selected view are loaded on initial requests.
- Successful GET responses are cached in the browser for five minutes; stale cached data may be shown while a refresh runs for up to thirty minutes.
- Plotly and Leaflet are loaded on demand. Charts inside inactive tabs are drawn when their tab becomes visible.
- The interface uses responsive layouts, keyboard-operable tabs, visible focus, semantic labels, reduced-motion support and 44-pixel minimum control targets. Light/dark mode and text scaling controls share dimensions.
- This is an accessibility-focused implementation, not a claim of audited WCAG conformance. Complete WCAG 2.2 AA validation still requires manual keyboard, screen-reader, contrast, zoom/reflow and mobile testing with real browser rendering.

## Verification

Run from the repository root:

```bash
python3.12 -m pip install -r requirements-dev.txt
python scripts/validate_data.py
python -m pytest -q
```


## Relate-backed event retrieval and current result limits

Programs & Events now reads event-like nodes from the embedded Relate graph when its discovered schema contains event title and start-date/time fields. The graph query remains read-only and uses discovered, quoted schema identifiers. Event filters are evaluated against supplied branch, audience, language, program type, date, time and registration fields. Only future-dated records with a parseable start time are eligible. The interface displays at most 10 matching programs; the displayed count refers to the rows shown, not the total number of records in the underlying graph. If the graph file, Relate package or event node schema is unavailable, the normalized CSV event feed remains the fallback.

Branch comparisons supplement incomplete Relate annual metrics with the matching physical-branch CSV observations. This is particularly important when one graph import is missing the visitation or workstation node label. Values already present in Relate take precedence; CSV fills missing branch-year values.

The Overview includes an unscoped Relate question form. Branch Insights sends the selected branch code with the question, and the API keeps only graph records that explicitly identify that branch by branch code or branch/location name. It does not present unrelated graph matches as branch-specific answers.


The interface uses a horizontal civic-information masthead and restrained, rule-based sectioning rather than a side-rail dashboard or repeated bordered cards. Overview analysis and branch Q&A are separate from the metric and location views. Event filter options are taken from Relate when the graph event schema is available, with CSV fallback.
