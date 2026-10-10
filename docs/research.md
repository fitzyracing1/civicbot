# US city APIs that robots and software agents can call: landscape research

*Compiled Oct 10, 2026 (ET). All counts have a cited source. When a number is my own estimate or count, it says so. Raw pulls are in this folder: `wzdx.json`, `dg_orgs.json`, `socrata_domains_2025.txt`, `socrata_local_guess.txt`.*

## TL;DR

| Layer | What an agent can do | Rough US coverage | Source / date |
|---|---|---|---|
| **311 / Open311 (write)** | File a service request (pothole, graffiti, streetlight), check its status | **Under 10 city-run endpoints** are live and documented with POST, plus **about 300–340 SeeClickFix (CivicPlus) client governments** that expose Open311 through one vendor endpoint | wiki.open311.org list (stale), live probes Oct 10, 2026, SeeClickFix docs, LeadIQ/E4C (third-party) |
| **Open data portals (read)** | Query datasets (permits issued, 311 history, inspections, crashes) | **About 150 distinct US local governments on Socrata** (my dedupe of 193 domains). **ArcGIS Hub reports at least 10,000 public Hub sites** worldwide (the API caps the count at 10,000). **data.gov federates only 27 cities and 9 counties** | Socrata domain scrape Feb 2025, Hub Search API Oct 10, 2026, data.gov v4 API Oct 10, 2026 |
| **Transit (read, real time)** | Schedules, vehicle positions, arrivals | **About 1,177 of 2,867 NTD agencies (41%)** have GTFS in Transitland. GTFS·X finds **55% of 2,238 FY2024 NTD agencies** have a findable feed. busmaps lists **1,592 US feeds, 400 providers, 340 with realtime** | transit.land, gtfsx.com (Aug 5, 2026), busmaps.com |
| **Work zones / road closures (read)** | Know where lanes are closed | **42 active feeds from 41 issuers** in the USDOT WZDx registry. These are almost all state DOTs. Only **3 are local** (City of Austin, Maricopa County AZ, St. Charles County MO), plus the MTC Bay Area region | data.transportation.gov/resource/69qe-yiui (pulled Oct 10, 2026) |
| **Parking (write, via vendor)** | Start or pay for a parking session | ParkMobile: **"over 700 cities across North America"**. The API is a partner API, not a city API | ParkMobile press release, Nov 18, 2025 |
| **Permits (write, via vendor)** | Apply for or look up permits and inspections | Accela Civic Platform / Construct API: **"900+ agencies"** (third-party figure) | supergood.ai / yardstick (third-party) |
| **Denominator** | n/a | **19,491 municipal governments** (2022) and **19,489** (2025), plus 16,214 townships and 3,031 counties | US Census Bureau, Census of Governments |

**Bottom line:** fewer than about 1–2% of US municipalities run their own callable API that can *do* something. Reach comes from **vendors**: SeeClickFix/CivicPlus for 311, Accela/Tyler for permits, ParkMobile and others for parking, and Socrata or Esri for data. An SDK that integrates one vendor unlocks hundreds of towns at once.

---

## 1. Open311 GeoReport v2 (311 service requests)

**The spec** (https://wiki.open311.org/GeoReport_v2/): `GET /services`, `GET /requests`, and `POST /requests` (needs an API key, plus `service_code` and a location). It is the only cross-city standard for *writing* to a city.

**Official server list** (https://wiki.open311.org/GeoReport_v2/Servers): it lists **11 US jurisdictions in production**: Baltimore, Bloomington IN, Boston, Brookline MA, Chicago, Columbus IN, Gilbert AZ, Grand Rapids MI, Peoria IL, San Francisco, and Washington DC. Philadelphia is listed as "in development." The list is **badly stale**; see the live check below.

**Live status.** These come from my own `curl` probes on Oct 10, 2026, cross-checked with http://status.open311.org/:

| Jurisdiction | Read (GET services/requests) | Write (POST) | Notes |
|---|---|---|---|
| **Chicago, IL** | Up per status.open311.org (124 service types). It timed out from my box. | **Yes, with an API key** (https://311api.cityofchicago.org/open311/v2/, docs https://github.com/Chicago/open311-api-docs) | Most mature |
| **Boston, MA** | Up (https://311.boston.gov/open311/v2/services.json) | **Yes, with an API key**. Creation "may require additional approval" (https://311.boston.gov/open311/docs) | Spot Mobile platform |
| **Bloomington, IN** | Up. It is the most active US endpoint on status.open311.org: 55 requests in 48h, 64 types | **Yes** (uReport, https://bloomington.in.gov/crm/open311/v2/) | Small city (~80k) with a real write API |
| **Austin, TX** | Up (https://311.austintexas.gov/open311/v2). `services.json` returned an empty list today | **Documented with an API key** (https://311.austintexas.gov/open311/docs) | Not on the wiki list |
| **Brookline, MA** | Up (22 types) | Likely yes (Spot platform, key) | Small town |
| San Francisco, CA | The endpoint still answers with live data | **Officially discontinued.** DataSF says "San Francisco 311 no longer supports the Open311 API" (https://sfdigitalservices.gitbook.io/dataset-explainers/311-cases) | Treat it as read-only/unsupported |
| Washington, DC | Down (522 / error on status.open311.org) | No | DC moved 311 to SeeClickFix integration (https://octo.dc.gov/release/district-integrates-311-service-request-system-seeclickfix-0) |
| New York City | n/a | **No.** The NYC311 Public API is read-only content. GeoReport v2 is retired (https://api-portal.nyc.gov/, https://portal.311.nyc.gov/article/?kanumber=KA-01336) | |
| Baltimore, Columbus IN, Gilbert, Grand Rapids, Peoria | Error, 401, 404, or no response | No (effectively) | Dead or locked |

**Count (city-run):** about **5 US jurisdictions have a live, documented write-capable Open311 API**: Chicago, Boston, Bloomington, Austin, and Brookline. About 6 more from the official list are dead or read-only. *(My count from live probes; methods are in the table above.)*

**Vendor-hosted Open311, which is the real multiplier:**
- **SeeClickFix (CivicPlus)** gives *every client organization* its own GeoReport v2 endpoint, `https://seeclickfix.com/open311/v2/:organization_id`. It also has an aggregate endpoint that finds the right jurisdiction by lat/long. SeeClickFix says the Open311 API allows "the ability to report issues without needing to establish a SeeClickFix user account" (https://dev.seeclickfix.com/v2/recommendations/, https://seeclickfix.com/open311/v2/docs). I confirmed that New Haven (org 29) answers live. **Client count:** "more than 340 local governments" (LeadIQ, third-party, ~2025) and "300 cities" (Engineering for Change, older). CivicPlus's own SeeClickFix page gives no client count, only "1 million+ resident requests resolved annually" (https://www.civicplus.com/seeclickfix-311-crm/).
- **Spot Mobile / Connected Bits** hosts Boston, Austin, Brookline, SF, and Grand Rapids (from URL patterns; my inference). A single integration pattern covers all of them.
- **Accela PublicStuff, Salesforce/Verint/Granicus 311 CRMs:** I found no public cross-tenant API. Treat them as closed unless each city publishes one.

**Bottom line for item 1:** roughly **5 city-run write APIs plus about 300–340 governments via SeeClickFix**. Everything else is read-only 311 history on open data portals (NYC, SF, LA, Seattle, and others) or nothing.

## 2. Open data portals (mostly read-only)

- **Socrata / Tyler Data & Insights:** Simon Willison's git scraper of the Socrata Discovery API had **357 domains** with public assets as of Feb 13, 2025 (https://github.com/simonw/scrape-open-data; method: https://github.com/simonw/scrape-open-data/issues/1, which counted 513 domains in 2022). After I removed demo/test/internal, federal, state, and non-US domains, **193 US local-government domains** remain. Deduping multiple domains per government (Austin alone has about 6) gives **roughly 150 distinct US cities and counties**. *(My estimate; the list is in `socrata_local_guess.txt`.)* At the 2018 acquisition, Socrata had about 1,300 government customers (https://www.govtech.com/biz/Tyler-Technologies-Acquires-Socrata.html). That figure includes internal/enterprise customers who are not public portals. Every Socrata dataset has a SODA REST/SoQL endpoint, which makes this the most agent-friendly layer.
- **ArcGIS Hub (Esri):** the Hub Search API (`https://hub.arcgis.com/api/search/v1/collections/site/items`) reported `numberMatched` = **10,000** for public Hub sites, which looks like the cap. Queries for "city" matched 5,517, "county" 5,639, "town" 909, and "open data" 5,870. These are global, overlap, and include non-government sites (queried Oct 10, 2026). Esri said **4,000+ organizations** had enabled open data on Hub in Jan 2019 (https://www.esri.com/about/newsroom/announcements/esri-helps-government-agencies-meet-new-open-data-law-requirements-using-arcgis-hub). Hub is very likely the **largest local-government footprint**, including many small towns and counties publishing GIS layers. Every layer is an ArcGIS REST FeatureServer, which can be queried as JSON or GeoJSON.
- **CKAN:** used by Boston (data.boston.gov), WPRDC/Pittsburgh, and Lisbon. In the US it covers dozens of governments at most; I found no authoritative count.
- **OpenDataSoft (now Huwise):** few US cities. Its *Open Data Inception* census listed about **500 US portals** as of 2015 (https://www.huwise.com/en/blog/how-we-put-together-a-list-of-1600-open-data-portals-around-the-world-to-help-open-data-community/). That figure is dated.
- **data.gov** (v4 Catalog API, `https://api.gsa.gov/technology/datagov/v4/organizations`, pulled Oct 10, 2026): **123 organizations total**, of which **27 are City Government and 9 County Government**. Examples: Austin (2,855 datasets), NYC (2,710), DC (1,803), Chicago (1,130). data.gov badly undercounts local open data.
- The US City Open Data Census (Sunlight/OKFN) is defunct. I did not use it.

## 3. Transit (GTFS / GTFS-Realtime)

- **Transitland NTD crosswalk** (https://www.transit.land/data/id-crosswalks/us-ntd, 2024 NTD year): **2,867** NTD agencies, of which **1,177 (41%)** have GTFS in Transitland and 1,690 are missing.
- **GTFS·X Feed Health** (https://www.gtfsx.com/feed-health/, refreshed Aug 5, 2026): of **2,238** FY2024 NTD agencies, **45% have no findable GTFS**. That means about 55% do. The gap is 10% for full reporters and 65% for rural 5311 agencies. Only 77 US feeds publish GTFS-Flex.
- **busmaps.com** (https://busmaps.com/en/usa/feedlist): **1,592 US feeds** (1,259 active), **400 providers**, **340 with realtime**.
- **Mobility Database** (https://mobilitydatabase.org): 6,000+ feeds worldwide. One export shows 6,487 feeds (4,523 GTFS plus 1,964 GTFS-RT) across 94 countries, with no US-only figure published.
- Transit is read-only for agents, except fare payment through agency apps, which have no public APIs.

## 4. Other actionable APIs (write vs read)

| Domain | API | Writable? | Coverage |
|---|---|---|---|
| Parking | ParkMobile partner API (find, start, and extend sessions) | **Yes**, but partner access only | "over 700 cities across North America" (ParkMobile, Nov 18, 2025: https://news.cision.com/parkmobile/r/parkmobile-to-expand-parking-network-to-8-000-new-locations-across-the-u-s-,c4269090). Also PayByPhone, Passport, SpotHero (not researched) |
| Permits/licensing | Accela Construct API (https://developer.accela.com) | **Yes** (apply, schedule inspections, pay) with agency-granted credentials | "900+ agencies" (third-party: https://supergood.ai/api-report-card/accela). Tyler EnerGov/Civic Access has no public API that I found |
| Work zones | WZDx feeds (https://www.transportation.gov/av/data/wzdx) | Read-only | **42 active feeds / 41 issuers.** Locals: City of Austin, Maricopa County, St. Charles County, MTC (registry pulled Oct 10, 2026) |
| 311 | Open311 / SeeClickFix | **Yes** | See section 1 |
| Payments, utilities | Usually behind vendor portals (Paymentus, Invoice Cloud, Tyler) | No public API | n/a |
| Open data | Socrata SODA / ArcGIS REST / CKAN | Read-only | See section 2 |

## 5. Ten standout US cities

1. **Chicago:** Open311 **POST** (https://311api.cityofchicago.org/open311/v2/), Socrata portal (https://data.cityofchicago.org), CTA Bus/Train Tracker APIs (https://www.transitchicago.com/developers/).
2. **Boston:** Open311 **POST** (https://311.boston.gov/open311/docs), CKAN portal (https://data.boston.gov), MBTA V3 API with real-time data (https://api-v3.mbta.com).
3. **New York City:** NYC Open Data (Socrata, https://data.cityofnewyork.us, 2,700+ datasets), NYC311 Public API (read-only, https://api-portal.nyc.gov), MTA GTFS-RT (https://api.mta.info). No public 311 write API.
4. **Austin:** Open311 (https://311.austintexas.gov/open311), Socrata (https://data.austintexas.gov), the only *city* WZDx feed in the registry, and CapMetro GTFS-RT.
5. **San Francisco:** DataSF (Socrata, https://data.sfgov.org) and the 511 SF Bay API for transit and traffic (https://511.org/open-data). Open311 is officially unsupported even though the endpoint still serves data.
6. **Washington, DC:** Open Data DC (ArcGIS Hub, https://opendata.dc.gov), WMATA API (https://developer.wmata.com), and 311 via SeeClickFix.
7. **Los Angeles:** Socrata (https://data.lacity.org), LA Metro APIs (https://developer.metro.net), and the Controller's data portal.
8. **Seattle:** Socrata (https://data.seattle.gov), OneBusAway Puget Sound API (https://pugetsound.onebusaway.org), and the WSDOT traveler API and WZDx.
9. **Bloomington, IN:** a small city with a full read/write Open311 endpoint (uReport, https://bloomington.in.gov/crm/open311/v2/), the busiest on status.open311.org, plus a Socrata portal (https://data.bloomington.in.gov). It is an ideal SDK test target.
10. **Philadelphia:** OpenDataPhilly plus the Carto SQL API (https://phl.carto.com), SEPTA real-time APIs, and Philly311 Open311 listed as "in development." *Honorable mentions:* Pittsburgh/WPRDC (CKAN), Kansas City (Socrata), New Haven (SeeClickFix org 29).

## 6. Coverage vs the ~19,500 municipalities

- **Denominator:** the Census of Governments counts **19,491 municipal governments** in 2022, plus 16,214 townships and 3,031 counties (https://www2.census.gov/programs-surveys/gus/datasets/2022/2022_gov_org_meth_tech_doc.pdf). The 2025 update gives **19,489** municipal governments (https://www.census.gov/content/dam/Census/library/publications/2025/econ/govtorg2225.pdf). **The ~19,500 figure is verified.**
- **City-run write APIs:** about 5 Open311, which is **about 0.03%** of municipalities.
- **SeeClickFix-hosted Open311:** about 300–340 governments, **about 1.5–1.7%** (the client count is third-party and includes counties).
- **Socrata local portals:** about 150, **about 0.8%** of municipalities plus counties.
- **ArcGIS Hub:** probably several thousand US local governments publish *some* GIS data, and it is the broadest read layer. I could not get an exact US-local count; see caveats.
- **Transit:** about 55–60% of federally funded agencies have GTFS. This is the best-covered layer, but it is regional, not per-town.
- **Conclusion:** most of the ~19.5k municipalities are small towns with **no callable API**. Their "API" is a web form or a vendor portal.

**The vendor angle (one integration unlocks many towns):**
- **CivicPlus**, which owns SeeClickFix, says it serves **13,000+ local-government customers** (third-party summary of https://www.civicplus.com/services/). SeeClickFix's Open311 is the **single highest-leverage write integration**.
- **Tyler Technologies:** **45,000 installations across 15,000 locations** (https://www.tylertech.com/Portals/0/Tyler-Fast-Facts-2025.pdf). It owns Socrata (read) and EnerGov/payments, and has no unified public write API.
- **Esri ArcGIS:** the de facto GIS layer for thousands of counties and towns. It is read-only, but uniform REST.
- **Accela:** permits/licensing at "900+ agencies" (third-party) with a real developer API, but each agency must grant access.
- **ParkMobile:** 700+ cities in North America, partner-gated.

## 7. Lisbon (company home base)

Lisbon has a CKAN open-data portal (https://dados.cm-lisboa.pt / https://dadosabertos.cm-lisboa.pt, behind Cloudflare bot protection, so programmatic access may need care). It publishes the **"Ocorrências Na Minha Rua"** dataset of resident reports, per year from 2017 to 2025 and updated quarterly (https://dadosabertos.cm-lisboa.pt/dataset/ocorrencias-na-minha-rua). Reports are filed through the **Na Minha Rua LX** app and web portal (https://www.lisboaparticipa.pt/pt/na-minha-rua-lx, iOS https://apps.apple.com/us/app/naminharua-lx/id1186245468). Filing needs a user account; I found no documented public write API. Lisbon appears on the Open311 wiki as an endpoint **"in development"** (https://wiki.open311.org/GeoReport_v2/Servers), which is worth asking CML about directly.

Transit is well covered:
- **Carris** (municipal bus/tram) GTFS: https://gateway.carris.pt/gateway/gtfs/api/v2.11/GTFS (via https://www.transit.land/feeds/f-carris~pt)
- **Metro de Lisboa** GTFS: https://www.metrolisboa.pt/google_transit/googleTransit.zip, plus an official real-time line status and waiting-times API (OAuth client credentials) at https://api.metrolisboa.pt (https://api.metrolisboa.pt/store/apis/info?name=EstadoServicoML&provider=admin&version=1.0.1)
- **Carris Metropolitana** (regional buses) has an open API with GTFS and real-time data: https://api.carrismetropolitana.pt/v2/ (https://github.com/carrismetropolitana/api)
- **TML** has a unified GTFS for the whole metro area: https://go.tmlmobilidade.pt/hub/api/v1/plans/gtfs

All endpoints responded on Oct 10, 2026.

## Caveats

- The **Open311 wiki list is years out of date.** My live probes ran from a single box on one day. Chicago timed out from here even though status.open311.org shows it up, so it may be geo or IP filtering. I did not test POST on any endpoint, because doing so would file real requests. "Write-capable" means *documented* POST with an API key.
- **The SeeClickFix client count (~340) is third-party** (LeadIQ). The older "300 cities" figure is from Engineering for Change, and CivicPlus doesn't publish one. SeeClickFix's statement that Open311 lets you report issues without a SeeClickFix account still implies an Open311 API key for POST in practice. Verify with CivicPlus.
- **The Socrata ~150 figure is my own dedupe** of a Feb 2025 scrape. The live Discovery API `/domains` endpoint now returns "not found," so I could not refresh it.
- **The ArcGIS Hub count is capped at 10,000**, is global, and includes non-government and duplicate sites. It is not a clean US-local count.
- **Accela "900+," CivicPlus "13,000+," and Tyler "15,000 locations"** are vendor or third-party marketing figures across all products, not API-enabled customers.
- **The transit counts disagree** (41% vs 55% coverage) because of different denominators (2,867 vs 2,238 NTD agencies) and matching methods. Both are cited.
- ParkMobile's 700+ cities covers North America, not just the US.

## Sources

- Open311 GeoReport v2 spec: https://wiki.open311.org/GeoReport_v2/
- Open311 servers list: https://wiki.open311.org/GeoReport_v2/Servers
- Open311 status monitor: http://status.open311.org/
- Chicago Open311 docs: https://github.com/Chicago/open311-api-docs
- Boston Open311: https://311.boston.gov/open311/docs
- Austin Open311: https://311.austintexas.gov/open311/docs
- Bloomington uReport: https://bloomington.in.gov/crm/open311/v2/
- SF 311 explainer: https://sfdigitalservices.gitbook.io/dataset-explainers/311-cases
- NYC API portal: https://api-portal.nyc.gov/
- NYC311 Content API: https://portal.311.nyc.gov/article/?kanumber=KA-01336
- SeeClickFix: https://seeclickfix.com/open311/v2/docs, https://dev.seeclickfix.com/v2/recommendations/
- SeeClickFix client counts: https://leadiq.com/c/seeclickfix/5a1d82e824000024005db700, https://www.engineeringforchange.org/solutions/product/seeclickfix/
- CivicPlus: https://www.civicplus.com/seeclickfix-311-crm/, https://www.civicplus.com/services/
- DC SeeClickFix integration: https://octo.dc.gov/release/district-integrates-311-service-request-system-seeclickfix-0
- Socrata scrape: https://github.com/simonw/scrape-open-data, https://github.com/simonw/scrape-open-data/issues/1
- Socrata acquisition: https://www.govtech.com/biz/Tyler-Technologies-Acquires-Socrata.html
- ArcGIS Hub Search API: https://hub.arcgis.com/api/search/v1/collections/site/items
- Esri Hub 2019 figure: https://www.esri.com/about/newsroom/announcements/esri-helps-government-agencies-meet-new-open-data-law-requirements-using-arcgis-hub
- Open Data Inception: https://www.huwise.com/en/blog/how-we-put-together-a-list-of-1600-open-data-portals-around-the-world-to-help-open-data-community/
- data.gov Catalog API: https://resources.data.gov/catalog-api/, https://api.gsa.gov/technology/datagov/v4/organizations
- Transitland NTD crosswalk: https://www.transit.land/data/id-crosswalks/us-ntd
- GTFS·X Feed Health: https://www.gtfsx.com/feed-health/
- busmaps US feed list: https://busmaps.com/en/usa/feedlist
- Mobility Database: https://mobilitydatabase.org/faq
- WZDx: https://www.transportation.gov/av/data/wzdx
- WZDx registry API: https://data.transportation.gov/resource/69qe-yiui.json
- ParkMobile press release: https://news.cision.com/parkmobile/r/parkmobile-to-expand-parking-network-to-8-000-new-locations-across-the-u-s-,c4269090
- Accela: https://developer.accela.com, https://supergood.ai/api-report-card/accela
- Tyler Fast Facts: https://www.tylertech.com/Portals/0/Tyler-Fast-Facts-2025.pdf
- Census of Governments: https://www2.census.gov/programs-surveys/gus/datasets/2022/2022_gov_org_meth_tech_doc.pdf, https://www.census.gov/content/dam/Census/library/publications/2025/econ/govtorg2225.pdf
- Lisbon: https://dadosabertos.cm-lisboa.pt/dataset/ocorrencias-na-minha-rua, https://www.lisboaparticipa.pt/pt/na-minha-rua-lx, https://api.metrolisboa.pt, https://github.com/carrismetropolitana/api, https://go.tmlmobilidade.pt/reference/open-data, https://www.transit.land/feeds/f-carris~pt
