# Oregon Construction Intelligence

Sales-oriented public building-permit intelligence for Oregon.

## Current production collector

- **Portland** — official City of Portland Bureau of Development Services `BDS_Permit` FeatureServer.
- Production collection uses layer **5 Residential Construction Permit** and layer **2 Commercial Construction Permit**, requesting the newest issued records as JSON.
- The collector validates the ArcGIS schema, rejects foreign permit-link hosts, and preserves permit history between runs.
- Deferred submittals (`DFS`) and revisions (`REV`) are retained in history but do **not** qualify as standalone new-construction leads.
- PortlandMaps HTML issued-permit reports remain in the rep source directory for manual browsing/export, but are not the production ingestion dependency.

## Outputs

- `public/index.html` — sortable/filterable lead dashboard
- `public/data/permits.json` — qualifying new-construction permits
- `public/data/sources.json` — collector health/freshness
- `public/data/builders.json` — 90-day contractor rollups when contractor data is available
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
