# LibraryTO data directory

Place the six CSV source snapshots and the Relate graph file directly in this directory. There are no `source/` or `derived/` subdirectories.

## Exact filenames

| Asset | Filename |
|---|---|
| Relate graph | `tpl_library_graph.rl` |
| Branch directory | `tpl-branch-general-information.csv` |
| Annual circulation | `tpl-circulation-annual-by-branch.csv` |
| Annual visits | `tpl-visits-annual-by-branch.csv` |
| Annual workstation usage | `tpl-workstation-usage-annual-by-branch.csv` |
| Annual card registrations | `tpl-card-registrations-annual-by-branch.csv` |
| Programs and events feed | `tpl-events-feed.csv` |

The names above are the application contract. Do not rename the files or place them in nested directories.

## Runtime behavior

- CSVs are read from the project directory and cached in memory for the lifetime of each application process.
- The Relate store is opened directly from `tpl_library_graph.rl` using `relate-db` in read-only mode.
- LibraryTO does not create, seed, rewrite or checkpoint the graph file.
- Add or replace source files and redeploy to publish a new snapshot. Vercel's function filesystem is not treated as persistent storage.

Run `python scripts/validate_data.py` after adding the files. The validator checks exact filenames, expected CSV fields, reporting years and whether the Relate graph file is present.
