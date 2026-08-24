# Oregon Construction Intelligence

Sales-oriented public building-permit intelligence for Oregon.

## Current production collector

- **Portland** — official PortlandMaps Residential and Commercial Issued Building Permit reports.
- The collector polls the last 180 days, follows report pagination, preserves permit history, and rejects foreign permit-link hosts.
- Deferred submittals (`DFS`) and revisions (`REV`) are retained in history but do **not** qualify as standalone new-construction leads.

## Outputs

- `public/index.html` — sortable/filterable lead dashboard
- `public/data/permits.json` — qualifying new-construction permits
- `public/data/sources.json` — collector health/freshness
- `public/data/builders.json` — 90-day contractor rollups
- RSS: all new construction, multifamily, single family, commercial, and top opportunities

## Local run

```bash
pip install -r requirements.txt
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m oregon_permits.main
```

## Automation

GitHub Actions runs every six hours and on changes merged to `main`, commits generated permit history/data, then deploys `public/` to GitHub Pages.

See `docs/SOURCE_DIRECTORY.md` for rep-facing Oregon permit and development sources.
