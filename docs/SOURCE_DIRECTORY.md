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
| Hillsboro | https://www.hillsboro-oregon.gov/services/permitting-center | OpenHillsboro permit portal for building, planning, fire, right-of-way and major projects. |

## Rep workflow

1. Start with application/intake or planning sources to identify projects before construction begins.
2. Confirm movement with issued building permits.
3. Capture project name, address, permit number, builder/GC, owner/developer, units, valuation, issue date and source link.
4. Aggregate related permits into one builder/development opportunity instead of treating each deferred submittal, revision or trade permit as a separate lead.
