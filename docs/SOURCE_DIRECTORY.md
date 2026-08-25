# Oregon permit/prospecting source directory

This list separates **issued building permits** from **earlier planning/development signals** so reps can work a project before and after permit issuance.

| Market | Source | Rep use |
|---|---|---|
| Statewide participating jurisdictions | https://buildingpermits.oregon.gov/ | Oregon ePermitting public permit search; no account is required to search existing records. Best statewide reconciliation source where the city/county participates. |
| Portland | https://www.portlandmaps.com/arcgis/rest/services/Public/BDS_Permit/FeatureServer | Official Bureau of Development Services machine-readable permit service. Production automation uses Residential Construction layer 5 and Commercial Construction layer 2. |
| Portland | https://www.portlandmaps.com/reports/index.cfm?action=rs-issued | Residential issued building-permit report for rep browsing/export. |
| Portland | https://www.portlandmaps.com/reports/index.cfm?action=co-issued | Commercial issued building-permit report for rep browsing/export. |
| Portland | https://www.portlandmaps.com/reports/index.cfm?action=rs-intake | Residential permit applications received; earlier sales signal than issuance. |
| Portland | https://www.portlandmaps.com/reports/index.cfm?action=co-intake | Commercial permit applications received; earlier sales signal than issuance. |
| Eugene | https://pdd.eugene-or.gov/buildingpermits/permitreports | Official Building Activity Reports. Production automation uses the public Issued Building Permits Excel export; reps can also run submitted-permit and dwelling-unit reports here. |
| Eugene | https://pdd.eugene-or.gov/buildingpermits/permitsearch | Permit Record Search by permit, person/business, project, address, contractor, map/tax lot. Use for project and contractor detail. |
| Bend | https://services5.arcgis.com/JisFYcK2mIVg9ueP/arcgis/rest/services/Permits_and_Contractors_Table/FeatureServer/0 | Official nightly City of Bend permit/contractor table. Production automation filters issued building permits to new construction and captures GC, owner, valuation, square feet, use and address. |
| Bend | https://services5.arcgis.com/JisFYcK2mIVg9ueP/ArcGIS/rest/services/Permit_Applications_Poly/FeatureServer/0 | Official Bend permit application spatial/open-data layer. Production uses it to enrich Bend leads with units, building category and census structure. |
| Bend | https://bendoregon.gov/services/permits-licenses/developers-and-contractors/ | Online Permit Center, permit lookup, open data and development tools for rep research. |
| Salem | https://permits.cityofsalem.net/ | Public PAC portal for browser-based permit, license and land-use searches. It currently blocks GitHub Actions automation, so it remains a manual/reference source. |
| Hillsboro | https://aca-prod.accela.com/HILLSBORO/Cap/CapHome.aspx?TabName=Building&module=Building | Official OpenHillsboro Accela Citizen Access building search. Production automation uses a rolling 21-day window, narrows to Residential/Commercial Structural Permit records, and requires an authoritative subtype beginning `New`. Older arbitrary date ranges were not reliable enough for backfill, so this is treated as a forward-looking monitor. |
| Hillsboro | https://inspections.hillsboro-oregon.gov/ | Official City inspection scheduler. A permit must be issued before inspection scheduling is available, so production automation uses this as an independent issuance validator before a Hillsboro candidate can enter the qualifying feeds. The public systems do not expose a reliable exact issue timestamp; the system stores the first date issuance is observed and preserves that date. |
| Hillsboro | https://www.hillsboro-oregon.gov/services/permitting-center | City permitting-center landing page for OpenHillsboro, building, planning, fire, right-of-way and major-project research. |
| Gresham | https://greshamor-energovweb.tylerhost.net/apps/SelfService/ | Official City of Gresham Tyler EnerGov Self Service portal. Production automation uses the anonymous permit-only module, pages by newest issue date, locally enforces a rolling 45-day cutoff because the public server does not reliably apply its IssueDate range criteria, rejects future-dated bad records, and accepts only authoritative Residential/Multi-Family/Commercial `New Construction` permit records. Project and description fields frequently expose subdivision and builder names for rep prospecting. |
| Beaverton | https://prod.buildinginbeaverton.org/lookup-record | Official City of Beaverton BEPS / Rhythm CIVICS public record lookup. Production automation anonymously queries the public building-application API using native `HouseOrAdu` and `NewCon` work types ordered by authoritative `issuedDateTime`, applies a rolling 45-day cutoff, and keeps only primary C/MF/R building records. New houses must also carry the authoritative `SFRdetNew` occupancy so ADUs are excluded. Public results include exact issue date, project/address, declared valuation, square footage and primary contractor identity when reported. |

## Rep workflow

1. Start with application/intake or planning sources to identify projects before construction begins.
2. Confirm movement with issued building permits.
3. Capture project name, address, permit number, builder/GC, owner/developer, units, valuation, issue date and source link.
4. Aggregate related permits into one builder/development opportunity instead of treating each deferred submittal, revision or trade permit as a separate lead.
