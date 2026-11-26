# Oregon Construction Intelligence

Sales-oriented public building-permit intelligence for Oregon.

## Current production collectors

- **Portland** — official City of Portland Bureau of Development Services `BDS_Permit` FeatureServer. Production collection uses layer **5 Residential Construction Permit** and layer **2 Commercial Construction Permit**, requesting the newest issued records as JSON.
- **Eugene** — official City of Eugene Planning & Development **Issued Building Permits** report. Production collection requests the public Excel export for a rolling 45-day window and maps issued date, permit number, work type, address, owner, contractor, dwellings, use, valuation and project description.
- **Bend** — official City of Bend nightly open-data permit services. Production collection filters the **Permits and Contractors Table** to issued `BLDG` applications marked `New Construction`, then enriches them from **Permit Applications Poly** with units, building category and census structure. This source provides strong builder/GC, owner, valuation, square-footage, use and address coverage.
- **Hillsboro** — official OpenHillsboro Accela Citizen Access building records plus the City of Hillsboro inspection system. Production collection uses one rolling **21-day** Accela window, keeps only Residential/Commercial Structural Permit records whose authoritative subtype begins `New`, and requires independent City inspection-system validation before a record can qualify as issued new construction. Hillsboro's public systems do not expose a reliable exact issue timestamp, so qualifying Hillsboro records use the date issuance was first observed by this collector and preserve that date on later runs.
- **Gresham** — official City of Gresham Tyler EnerGov public permit search. Production collection isolates the permit module, pages newest-first, locally enforces a rolling **45-day** issue-date cutoff, ignores future-dated bad records, and only accepts `New Construction` workclass records whose permit type is Residential, Multi-Family, or Commercial New Construction.
- **Beaverton** — official City of Beaverton BEPS / Rhythm CIVICS public building applications. Production automation uses anonymous CIVICS access, queries the native `HouseOrAdu` and `NewCon` work-type streams sorted by authoritative `issuedDateTime`, locally enforces a rolling **45-day** cutoff, and accepts only primary Residential, Multifamily, or Commercial building records. New-house records additionally require the authoritative `SFRdetNew` occupancy so standalone ADUs are not promoted. Public records provide valuation, square footage, project/address detail and, when present, the primary contractor.
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

## Eastern Oregon opt-in dry run

A Hermiston pilot is not registered in default collection and does not change the Pages workflow. In a disposable copy of the repository, install `requirements.txt` and run:

```bash
OREGON_ENABLE_HERMISTON_PILOT=1 PYTHONPATH=src python -m oregon_permits.main
```

The pilot discovers the two newest linked official monthly issued-structural reports and retains only new primary single-family dwelling entries. It intentionally excludes trade, accessory, multifamily and commercial permits and does not treat unqualified CCB listings as contractor/builder roles. It uses the existing permit-key history, source status, and stale-cache handling. An opt-in run writes generated outputs locally; do not commit them as part of this pilot. See the [source directory](docs/SOURCE_DIRECTORY.md) for nearby manual sources and restrictions.

### Hermiston publication quarantine preview

`OREGON_QUARANTINE_HERMISTON_OUTPUT=1` withholds only City of Hermiston permit
rows from the public dashboard, builder summaries and all RSS feeds. It does
not delete or de-qualify historical rows. A status note records the number
withheld. Unset or `0` leaves output identical to the current pilot.

`OREGON_ENABLE_HERMISTON_PILOT=0` is separate and stops further collection only.
For a containment rollback after any separately approved deployment, enable the
quarantine and stop collection if desired, then verify that generated and served
outputs exclude Hermiston while durable history remains intact. Clearing
quarantine allows cached qualifying rows back into output and requires a separate
release decision. Neither flag is set by the production workflow in this preview.
