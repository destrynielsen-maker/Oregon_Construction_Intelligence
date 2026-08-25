# Oregon Construction Intelligence

Sales-oriented public building-permit intelligence for Oregon.

## Current production collectors

- **Portland** — official City of Portland Bureau of Development Services `BDS_Permit` FeatureServer. Production collection uses layer **5 Residential Construction Permit** and layer **2 Commercial Construction Permit**, requesting the newest issued records as JSON.
- **Eugene** — official City of Eugene Planning & Development **Issued Building Permits** report. Production collection requests the public Excel export for a rolling 45-day window and maps issued date, permit number, work type, address, owner, contractor, dwellings, use, valuation and project description.
- **Bend** — official City of Bend nightly open-data permit services. Production collection filters the **Permits and Contractors Table** to issued `BLDG` applications marked `New Construction`, then enriches them from **Permit Applications Poly** with units, building category and census structure. This source provides strong builder/GC, owner, valuation, square-footage, use and address coverage.
- **Hillsboro** — official OpenHillsboro Accela Citizen Access building records plus the City of Hillsboro inspection system. Production collection uses one rolling **21-day** Accela window, keeps only Residential/Commercial Structural Permit records whose authoritative subtype begins `New`, and requires independent City inspection-system validation before a record can qualify as issued new construction. Hillsboro's public systems do not expose a reliable exact issue timestamp, so qualifying Hillsboro records use the date issuance was first observed by this collector and preserve that date on later runs.
- **Gresham** — official City of Gresham Tyler EnerGov public permit search. Production collection isolates the permit module, pages newest-first, locally enforces a rolling **45-day** issue-date cutoff, ignores future-dated bad records, and only accepts `New Construction` workclass records whose permit type is Residential, Multi-Family, or Commercial New Construction.
- Collectors validate their expected source/schema and retain permit history between runs.
- Deferred submittals (`DFS`), revisions (`REV`) and identified accessory structures do **not** qualify as standalone new-construction leads.

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
