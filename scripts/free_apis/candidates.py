"""Candidate free APIs for the civicbot directory. `verify.py` calls each `check` URL live and writes only the
ones that answer into civicbot/data/free_apis.json. Edit here, then re-run verify.py.

auth: "none" = no key, no signup | "demo-key" = works with a public demo key (rate-limited) |
      "free-key" = needs a free signup/key (verified only as reachable)
"""
LAT, LNG = 39.1653, -86.5264          # Bloomington, IN
NYC = (40.7128, -74.0060)
LIS = (38.7223, -9.1393)              # Lisbon

C = []


def add(id, name, category, answers, docs, check, auth="none", limits="", region="Global", expect=None,
        fmt="json", key_note="", terms=""):
    C.append(dict(id=id, name=name, category=category, answers=answers, docs=docs, check=check, auth=auth,
                  limits=limits, region=region, expect=expect, format=fmt, key_note=key_note, terms=terms))


# ---------------- Weather & climate ----------------
W = "Weather & climate"
add("open-meteo-forecast", "Open-Meteo Forecast", W, "Current weather, hourly and 16-day forecasts anywhere",
    "https://open-meteo.com/en/docs", f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LNG}&current=temperature_2m,weather_code",
    limits="Free for non-commercial use, < 10,000 calls/day; CC BY 4.0 attribution", expect="current")
add("open-meteo-archive", "Open-Meteo Historical Weather", W, "What the weather was on a past date (back to 1940)",
    "https://open-meteo.com/en/docs/historical-weather-api",
    f"https://archive-api.open-meteo.com/v1/archive?latitude={LAT}&longitude={LNG}&start_date=2026-10-01&end_date=2026-10-02&daily=temperature_2m_max",
    limits="Non-commercial free tier; CC BY 4.0", expect="daily")
add("open-meteo-climate", "Open-Meteo Climate Change", W, "Long-range climate projections for a place",
    "https://open-meteo.com/en/docs/climate-api",
    f"https://climate-api.open-meteo.com/v1/climate?latitude={LAT}&longitude={LNG}&start_date=2030-01-01&end_date=2030-01-02&models=MRI_AGCM3_2_S&daily=temperature_2m_max",
    limits="Non-commercial free tier; CC BY 4.0", expect="daily")
add("open-meteo-ensemble", "Open-Meteo Ensemble", W, "How uncertain the forecast is (ensemble spread)",
    "https://open-meteo.com/en/docs/ensemble-api",
    f"https://ensemble-api.open-meteo.com/v1/ensemble?latitude={LAT}&longitude={LNG}&hourly=temperature_2m&models=icon_seamless&forecast_days=1",
    limits="Non-commercial free tier; CC BY 4.0", expect="hourly")
add("nws-points", "US National Weather Service (forecast)", W, "Official NWS forecast for a US point",
    "https://www.weather.gov/documentation/services-web-api", f"https://api.weather.gov/points/{LAT},{LNG}",
    limits="No key; send a User-Agent identifying your app; public domain", region="US", expect="forecast")
add("nws-stations-obs", "NWS latest observation", W, "Latest observed conditions at a weather station",
    "https://www.weather.gov/documentation/services-web-api", "https://api.weather.gov/stations/KBMG/observations/latest",
    limits="No key; User-Agent required", region="US", expect="temperature")
add("met-no", "MET Norway Locationforecast", W, "Global forecast from the Norwegian Meteorological Institute",
    "https://api.met.no/weatherapi/locationforecast/2.0/documentation",
    f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={LIS[0]}&lon={LIS[1]}",
    limits="No key; identifying User-Agent required; cache responses; CC BY 4.0", expect="timeseries")
add("ipma-forecast", "IPMA Portugal city forecast", W, "5-day forecast for Portuguese cities (Lisbon = 1110600)",
    "https://api.ipma.pt/", "https://api.ipma.pt/open-data/forecast/meteorology/cities/daily/1110600.json",
    limits="No key; IPMA open data terms (attribution)", region="PT", expect="tMax")
add("ipma-sea", "IPMA sea state", W, "Wave height and sea temperature forecast for Portugal's coast",
    "https://api.ipma.pt/", "https://api.ipma.pt/open-data/forecast/oceanography/daily/hp-daily-sea-forecast-day0.json",
    limits="No key; attribution", region="PT", expect="data")
add("rainviewer", "RainViewer weather maps", W, "Is it raining nearby? Radar frames index",
    "https://www.rainviewer.com/api.html", "https://api.rainviewer.com/public/weather-maps.json",
    limits="Free for personal/non-commercial use; attribution", expect="radar")
add("dwd-brightsky", "Bright Sky (DWD, Germany)", W, "German Weather Service forecasts and observations",
    "https://brightsky.dev/docs/", "https://api.brightsky.dev/current_weather?lat=52.52&lon=13.40",
    limits="No key; DWD open data", region="DE", expect="weather")

# ---------------- Air quality & environment ----------------
A = "Air quality & environment"
add("open-meteo-air", "Open-Meteo Air Quality", A, "US AQI, PM2.5, ozone, pollen (Europe) for a place",
    "https://open-meteo.com/en/docs/air-quality-api",
    f"https://air-quality-api.open-meteo.com/v1/air-quality?latitude={LAT}&longitude={LNG}&current=us_aqi,pm2_5",
    limits="Non-commercial free tier; CAMS data, CC BY 4.0", expect="us_aqi")
add("uk-carbon-intensity", "UK Carbon Intensity", A, "How clean the UK grid is right now (good time to run the dishwasher?)",
    "https://carbon-intensity.github.io/api-definitions/", "https://api.carbonintensity.org.uk/intensity",
    limits="No key; CC BY 4.0", region="UK", expect="intensity")
add("sensor-community", "Sensor.Community", A, "Citizen-science PM sensors near a point",
    "https://github.com/opendata-stuttgart/meta/wiki/EN-APIs",
    f"https://data.sensor.community/airrohr/v1/filter/area={LIS[0]},{LIS[1]},2", limits="No key; ODbL; don't poll faster than 5 min")
add("currentuvindex", "Current UV Index", A, "UV index now and forecast for a place",
    "https://currentuvindex.com/api", f"https://currentuvindex.com/api/v1/uvi?latitude={LAT}&longitude={LNG}",
    limits="No key; free; fair use", expect="uvi")
add("openaq", "OpenAQ", A, "Official air-quality station readings worldwide", "https://docs.openaq.org/",
    "https://api.openaq.org/v3/locations?limit=1", auth="free-key", key_note="Free API key (X-API-Key header) since v3",
    limits="Free key; 60 req/min")
add("nasa-power", "NASA POWER", A, "Solar radiation and climate data for a point (solar panel questions)",
    "https://power.larc.nasa.gov/docs/services/api/",
    f"https://power.larc.nasa.gov/api/temporal/daily/point?parameters=ALLSKY_SFC_SW_DWN&community=RE&longitude={LNG}&latitude={LAT}&start=20260901&end=20260902&format=JSON",
    limits="No key; NASA open data", expect="properties")

# ---------------- Alerts & hazards ----------------
H = "Alerts & hazards"
add("nws-alerts", "NWS active alerts", H, "Weather warnings and watches for a US point",
    "https://www.weather.gov/documentation/services-web-api", f"https://api.weather.gov/alerts/active?point={LAT},{LNG}",
    limits="No key; User-Agent required", region="US", expect="features")
add("usgs-quakes-feed", "USGS earthquakes (feed)", H, "Earthquakes M2.5+ worldwide in the last day",
    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php",
    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson", limits="No key; public domain", expect="features")
add("usgs-quakes-query", "USGS earthquake search", H, "Recent earthquakes near a place",
    "https://earthquake.usgs.gov/fdsnws/event/1/",
    f"https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&latitude={LAT}&longitude={LNG}&maxradiuskm=1000&limit=3&orderby=time",
    limits="No key; public domain", expect="features")
add("emsc-quakes", "EMSC Seismic Portal", H, "European-Mediterranean earthquakes (great for Portugal)",
    "https://www.seismicportal.eu/fdsn-wsevent.html", "https://www.seismicportal.eu/fdsnws/event/1/query?format=json&limit=3",
    limits="No key; fair use", region="EU", expect="features")
add("nasa-eonet", "NASA EONET", H, "Open natural events: wildfires, storms, volcanoes",
    "https://eonet.gsfc.nasa.gov/docs/v3", "https://eonet.gsfc.nasa.gov/api/v3/events?limit=3&status=open",
    limits="No key; NASA open data", expect="events")
add("nhc-storms", "NOAA National Hurricane Center", H, "Active Atlantic/Pacific tropical storms",
    "https://www.nhc.noaa.gov/aboutrss.shtml", "https://www.nhc.noaa.gov/CurrentStorms.json",
    limits="No key; public domain", region="US", expect="activeStorms")
add("fema-declarations", "OpenFEMA disaster declarations", H, "Recent federal disaster declarations for a state",
    "https://www.fema.gov/about/openfema/api",
    "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries?$top=2&$orderby=declarationDate%20desc&$filter=state%20eq%20%27IN%27",
    limits="No key; public domain", region="US", expect="DisasterDeclarationsSummaries")
add("swpc-kp", "NOAA Space Weather (Kp)", H, "Geomagnetic activity: chance of northern lights",
    "https://www.swpc.noaa.gov/products/planetary-k-index", "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json",
    limits="No key; public domain")
add("swpc-aurora", "NOAA aurora forecast", H, "30-minute aurora probability grid",
    "https://www.swpc.noaa.gov/products/aurora-30-minute-forecast", "https://services.swpc.noaa.gov/json/ovation_aurora_latest.json",
    limits="No key; public domain; large (~1 MB)")
add("uk-floods", "UK Environment Agency floods", H, "Current flood warnings in England",
    "https://environment.data.gov.uk/flood-monitoring/doc/reference", "https://environment.data.gov.uk/flood-monitoring/id/floods?_limit=3",
    limits="No key; Open Government Licence", region="UK", expect="items")
add("gdacs", "GDACS disaster alerts", H, "Global disaster alerts (UN/EC)", "https://www.gdacs.org/",
    "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH?pagesize=2", limits="No key; fair use", expect="features")

# ---------------- Water, tides & marine ----------------
M = "Water, tides & marine"
add("noaa-tides", "NOAA tide predictions", M, "Today's high and low tides at a US station",
    "https://api.tidesandcurrents.noaa.gov/api/prod/",
    "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?date=today&station=8443970&product=predictions&datum=MLLW&time_zone=lst_ldt&units=english&interval=hilo&format=json&application=civicbot",
    limits="No key; public domain; pass application=<your app>", region="US", expect="predictions")
add("noaa-water-level", "NOAA water level", M, "Latest observed water level at a tide gauge",
    "https://api.tidesandcurrents.noaa.gov/api/prod/",
    "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?date=latest&station=8443970&product=water_level&datum=MLLW&time_zone=lst_ldt&units=english&format=json&application=civicbot",
    limits="No key; public domain", region="US", expect="data")
add("usgs-water-iv", "USGS Water Services (instantaneous)", M, "River flow and gauge height right now",
    "https://waterservices.usgs.gov/docs/instantaneous-values/",
    "https://waterservices.usgs.gov/nwis/iv/?format=json&sites=03353000&parameterCd=00060",
    limits="No key; public domain (legacy service; USGS is moving to api.waterdata.usgs.gov)", region="US", expect="timeSeries")
add("usgs-waterdata", "USGS Water Data OGC API", M, "Monitoring locations and latest values (new USGS API)",
    "https://api.waterdata.usgs.gov/", "https://api.waterdata.usgs.gov/ogcapi/v0/collections/monitoring-locations/items?f=json&limit=1",
    limits="No key for low volume (free key raises limits); public domain", region="US", expect="features")
add("open-meteo-marine", "Open-Meteo Marine", M, "Wave height and swell for a coastal point",
    "https://open-meteo.com/en/docs/marine-weather-api",
    f"https://marine-api.open-meteo.com/v1/marine?latitude=38.68&longitude=-9.35&current=wave_height",
    limits="Non-commercial free tier; CC BY 4.0", expect="current")
add("open-meteo-flood", "Open-Meteo Flood (GloFAS)", M, "River discharge forecast near a place",
    "https://open-meteo.com/en/docs/flood-api",
    f"https://flood-api.open-meteo.com/v1/flood?latitude={LAT}&longitude={LNG}&daily=river_discharge&forecast_days=3",
    limits="Non-commercial free tier; CC BY 4.0", expect="daily")

# ---------------- Transit ----------------
T = "Transit"
add("mbta-v3", "MBTA V3", T, "Boston subway/bus predictions, alerts, stops",
    "https://www.mbta.com/developers/v3-api", "https://api-v3.mbta.com/predictions?filter[stop]=place-pktrm&page[limit]=2",
    limits="No key: 20 req/min; free key: 1000 req/min", region="US", expect="data")
add("mbta-alerts", "MBTA service alerts", T, "Current Boston transit disruptions",
    "https://www.mbta.com/developers/v3-api", "https://api-v3.mbta.com/alerts?filter[activity]=BOARD&page[limit]=2",
    limits="No key: 20 req/min", region="US", expect="data")
add("tfl-status", "TfL Unified API (line status)", T, "London Tube line status", "https://api-portal.tfl.gov.uk/",
    "https://api.tfl.gov.uk/Line/Mode/tube/Status", limits="Works without a key at low volume; free key for 500 req/min",
    region="UK", expect="lineStatuses")
add("tfl-bikepoints", "TfL BikePoints", T, "Santander Cycles docks in London", "https://api-portal.tfl.gov.uk/",
    "https://api.tfl.gov.uk/BikePoint/BikePoints_1", limits="No key at low volume", region="UK", expect="commonName")
add("carris-metropolitana", "Carris Metropolitana", T, "Lisbon-area bus arrivals, stops, alerts",
    "https://github.com/carrismetropolitana/api", "https://api.carrismetropolitana.pt/v2/arrivals/by_stop/020429",
    limits="No key; fair use", region="PT")
add("carris-alerts", "Carris Metropolitana alerts", T, "Service alerts for Lisbon-area buses",
    "https://github.com/carrismetropolitana/api", "https://api.carrismetropolitana.pt/v2/alerts",
    limits="No key", region="PT")
add("mta-subway-alerts", "MTA subway alerts (JSON)", T, "NYC subway service alerts",
    "https://api.mta.info/", "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/camsys%2Fsubway-alerts.json",
    limits="No key (since 2024)", region="US", expect="entity")
add("mta-gtfs-rt", "MTA subway GTFS-Realtime", T, "NYC subway arrivals (protobuf; civicbot's gtfs-transit built-in reads it)",
    "https://api.mta.info/", "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-ace",
    limits="No key", region="US", fmt="protobuf")
add("mbta-gtfs-rt", "MBTA GTFS-Realtime", T, "Boston trip updates (protobuf)", "https://www.mbta.com/developers/gtfs-realtime",
    "https://cdn.mbta.com/realtime/TripUpdates.pb", limits="No key", region="US", fmt="protobuf")
add("bart-legacy", "BART API", T, "SF Bay Area real-time departures", "https://api.bart.gov/docs/overview/index.aspx",
    "https://api.bart.gov/api/etd.aspx?cmd=etd&orig=12th&key=MW9S-E7SL-26DU-VV8V&json=y", auth="demo-key",
    key_note="BART publishes a shared public key in its docs; register for your own", region="US", expect="etd")
add("irail", "iRail (Belgian railways)", T, "Belgian train departures", "https://docs.irail.be/",
    "https://api.irail.be/v1/liveboard/?station=Gent-Sint-Pieters&format=json&lang=en", limits="No key; 3 req/s; send User-Agent",
    region="EU", expect="departures")
add("swiss-transport", "Swiss public transport (transport.opendata.ch)", T, "Swiss departures and connections",
    "https://transport.opendata.ch/docs.html", "https://transport.opendata.ch/v1/stationboard?station=Zurich%20HB&limit=2",
    limits="No key; fair use", region="EU", expect="stationboard")
add("db-rest", "db-rest (Deutsche Bahn, community)", T, "German rail departures", "https://v6.db.transport.rest/",
    "https://v6.db.transport.rest/stations?query=berlin%20hbf&limit=1", limits="Community-run; 100 req/min; may be flaky",
    region="EU")
add("entur", "Entur (Norway)", T, "Norwegian journey planner (GraphQL, POST)", "https://developer.entur.org/",
    "https://api.entur.io/geocoder/v1/autocomplete?text=oslo&size=1", limits="No key; send ET-Client-Name header",
    region="EU", expect="features")
add("opensky", "OpenSky Network", "Flights & space", "Planes overhead right now (bounding box)", "https://openskynetwork.github.io/opensky-api/rest.html",
    "https://opensky-network.org/api/states/all?lamin=40.6&lomin=-74.1&lamax=40.8&lomax=-73.9",
    limits="Anonymous: 400 credits/day, 10 s resolution; non-commercial", expect="states")
add("adsb-lol", "adsb.lol", "Flights & space", "Aircraft within N nautical miles of a point", "https://api.adsb.lol/docs",
    "https://api.adsb.lol/v2/point/40.64/-73.78/5", limits="No key; ODbL; fair use", expect="ac")

# ---------------- Bikeshare ----------------
B = "Bikeshare & micromobility"
for bid, nm, url, reg in [("citibike", "Citi Bike (NYC)", "https://gbfs.citibikenyc.com/gbfs/en/station_status.json", "US"),
                          ("divvy", "Divvy (Chicago)", "https://gbfs.divvybikes.com/gbfs/en/station_status.json", "US"),
                          ("baywheels", "Bay Wheels (SF)", "https://gbfs.lyftbikes.com/gbfs/en/station_status.json", "US"),
                          ("capital-bikeshare", "Capital Bikeshare (DC)", "https://gbfs.capitalbikeshare.com/gbfs/en/station_status.json", "US"),
                          ("bluebikes", "Bluebikes (Boston)", "https://gbfs.bluebikes.com/gbfs/en/station_status.json", "US"),
                          ("biketown", "BIKETOWN (Portland)", "https://gbfs.biketownpdx.com/gbfs/en/station_status.json", "US")]:
    add(f"gbfs-{bid}", f"{nm} GBFS", B, "Bikes and docks available at each station", "https://github.com/MobilityData/gbfs",
        url, limits="No key; GBFS open data (operator license)", region=reg, expect="stations")
add("citybikes", "CityBikes API", B, "Bikeshare availability in 600+ cities (incl. Lisbon GIRA)", "https://api.citybik.es/v2/",
    "https://api.citybik.es/v2/networks/gira", limits="No key; fair use; AGPL project", expect="stations")
add("nrel-ev", "NREL Alternative Fuel Stations", "Bikeshare & micromobility", "EV chargers near a US point",
    "https://developer.nrel.gov/docs/transportation/alt-fuel-stations-v1/",
    f"https://developer.nrel.gov/api/alt-fuel-stations/v1/nearest.json?api_key=DEMO_KEY&latitude={LAT}&longitude={LNG}&fuel_type=ELEC&limit=1",
    auth="demo-key", key_note="DEMO_KEY: 30 req/hour, 50/day per IP; free api.data.gov key for real use", region="US",
    expect="fuel_stations")
add("open-charge-map", "Open Charge Map", "Bikeshare & micromobility", "EV chargers worldwide",
    "https://openchargemap.org/site/develop/api", "https://api.openchargemap.io/v3/poi?maxresults=1&countrycode=PT",
    auth="free-key", key_note="Free API key required", limits="Free key; CC BY-SA 4.0")

# ---------------- 311 & service requests ----------------
S = "311 & service requests"
for eid, nm, base in [("bloomington", "Bloomington, IN Open311", "https://bloomington.in.gov/crm/open311/v2"),
                      ("boston", "Boston Open311", "https://311.boston.gov/open311/v2"),
                      ("chicago", "Chicago Open311", "https://311api.cityofchicago.org/open311/v2"),
                      ("austin", "Austin Open311", "https://311.austintexas.gov/open311/v2"),
                      ("brookline", "Brookline, MA Open311", "https://spot.brooklinema.gov/open311/v2")]:
    add(f"open311-{eid}", nm, S, "Which problems the city accepts (GET services); reads are keyless",
        "https://wiki.open311.org/GeoReport_v2/", f"{base}/services.json",
        limits="Reads keyless; FILING needs a city-issued key (civicbot keeps filing dry-run)", region="US")
add("seeclickfix", "SeeClickFix API v2", S, "Recent issues reported near a point (hundreds of US towns)",
    "https://dev.seeclickfix.com/", "https://seeclickfix.com/api/v2/issues?lat=41.3083&lng=-72.9259&per_page=2",
    limits="No key for reads; fair use", region="US", expect="issues")
add("nyc-311", "NYC 311 requests (Socrata)", S, "Recent NYC 311 complaints near a place",
    "https://dev.socrata.com/foundry/data.cityofnewyork.us/erm2-nwe9", "https://data.cityofnewyork.us/resource/erm2-nwe9.json?$limit=1",
    limits="No key: throttled per IP; free app token raises limits", region="US")
add("chicago-311", "Chicago 311 requests (Socrata)", S, "Recent Chicago 311 requests near a place",
    "https://dev.socrata.com/foundry/data.cityofchicago.org/v6vf-nfxy", "https://data.cityofchicago.org/resource/v6vf-nfxy.json?$select=sr_type,status,created_date&$where=within_circle(location,41.8837,-87.6319,400)&$order=created_date%20DESC&$limit=2",
    limits="No key: throttled; free app token raises limits", region="US")
add("sf-311", "San Francisco 311 cases (Socrata)", S, "Recent SF 311 cases near a place",
    "https://dev.socrata.com/foundry/data.sf.gov/vw6y-z8j6", "https://data.sf.gov/resource/vw6y-z8j6.json?$limit=1",
    limits="No key: throttled", region="US")
add("seattle-csr", "Seattle customer service requests (Socrata)", S, "Recent Seattle service requests",
    "https://dev.socrata.com/foundry/data.seattle.gov/5ngg-rpne", "https://data.seattle.gov/resource/5ngg-rpne.json?$limit=1",
    limits="No key: throttled", region="US")
add("austin-311", "Austin 311 (Transportation & Public Works)", S, "Recent Austin street/traffic 311 requests",
    "https://dev.socrata.com/foundry/data.austintexas.gov/38mr-dwji", "https://data.austintexas.gov/resource/38mr-dwji.json?$limit=1",
    limits="No key: throttled", region="US")
add("nola-311", "New Orleans 311 (Socrata)", S, "Recent New Orleans 311 calls",
    "https://dev.socrata.com/foundry/data.nola.gov/2jgv-pqrq", "https://data.nola.gov/resource/2jgv-pqrq.json?$limit=1",
    limits="No key: throttled", region="US")
add("kc-311", "Kansas City 311 (Socrata)", S, "Kansas City 311 reported issues",
    "https://dev.socrata.com/foundry/data.kcmo.org/d4px-6rwg", "https://data.kcmo.org/resource/d4px-6rwg.json?$limit=1",
    limits="No key: throttled", region="US")
add("boston-311-ckan", "Boston 311 (CKAN datastore)", S, "Boston 311 requests, new system",
    "https://data.boston.gov/dataset/311-service-requests",
    "https://data.boston.gov/api/3/action/datastore_search?resource_id=254adca6-64ab-4c5c-9fc0-a6da622be185&limit=1",
    limits="No key; ODC PDDL", region="US", expect="records")

# ---------------- City open data ----------------
D = "City open data"
add("nyc-restaurants", "NYC restaurant inspections", D, "Latest health grade for a NYC restaurant",
    "https://dev.socrata.com/foundry/data.cityofnewyork.us/43nn-pn8j", "https://data.cityofnewyork.us/resource/43nn-pn8j.json?$limit=1",
    limits="No key: throttled", region="US")
add("chicago-food", "Chicago food inspections", D, "Food inspection results by restaurant",
    "https://dev.socrata.com/foundry/data.cityofchicago.org/4ijn-s7e5", "https://data.cityofchicago.org/resource/4ijn-s7e5.json?$limit=1",
    limits="No key: throttled", region="US")
add("chicago-crimes", "Chicago crimes", D, "Reported crimes near a place (last 7 days lag)",
    "https://dev.socrata.com/foundry/data.cityofchicago.org/ijzp-q8t2", "https://data.cityofchicago.org/resource/ijzp-q8t2.json?$limit=1",
    limits="No key: throttled", region="US")
add("sf-fire-calls", "SF fire department calls", D, "Recent SF fire/EMS calls for service",
    "https://dev.socrata.com/foundry/data.sf.gov/nuek-vuh3", "https://data.sf.gov/resource/nuek-vuh3.json?$limit=1",
    limits="No key: throttled", region="US")
add("seattle-911-fire", "Seattle Real-Time Fire 911", D, "Fire/EMS dispatches in Seattle, near real time",
    "https://dev.socrata.com/foundry/data.seattle.gov/kzjm-xkqj", "https://data.seattle.gov/resource/kzjm-xkqj.json?$limit=1",
    limits="No key: throttled", region="US")
add("la-crime", "Los Angeles NIBRS offenses", D, "Reported offenses in LA",
    "https://dev.socrata.com/foundry/data.lacity.org/k7nn-b2ep", "https://data.lacity.org/resource/k7nn-b2ep.json?$limit=1",
    limits="No key: throttled", region="US")
add("socrata-discovery", "Socrata Discovery API", D, "Find datasets on 100s of city portals",
    "https://dev.socrata.com/docs/other/discovery", "https://api.us.socrata.com/api/catalog/v1?q=311&limit=1",
    limits="No key", region="US", expect="results")
add("data-gov", "Data.gov catalog (CKAN)", D, "Search 300k+ US government datasets",
    "https://catalog.data.gov/", "https://catalog.data.gov/api/3/action/package_search?q=311&rows=1", limits="No key", region="US", expect="results")
add("census-acs", "US Census Data API", D, "Population and demographics for a state/county/tract",
    "https://www.census.gov/data/developers.html", "https://api.census.gov/data/2022/acs/acs5?get=NAME,B01003_001E&for=state:18",
    limits="No key up to 500 calls/day per IP; free key beyond", region="US")
add("lisboa-ckan", "Lisboa Aberta (Lisbon open data)", "Portugal & EU", "Lisbon city datasets (CKAN)",
    "https://dados.cm-lisboa.pt/", "https://dados.cm-lisboa.pt/api/3/action/package_search?rows=1",
    limits="No key; dataset licenses vary", region="PT", expect="results")
add("dados-gov-pt", "dados.gov.pt", "Portugal & EU", "Portugal's national open data portal",
    "https://dados.gov.pt/pt/docapi/", "https://dados.gov.pt/api/1/datasets/?q=transportes&page_size=1",
    limits="No key", region="PT", expect="data")
add("geoapi-pt", "GeoAPI.pt", "Portugal & EU", "Which Portuguese parish/municipality a point is in",
    "https://geoapi.pt/", f"https://json.geoapi.pt/gps/{LIS[0]},{LIS[1]}", limits="No key; fair use", region="PT")
add("data-europa", "data.europa.eu search", "Portugal & EU", "Search EU open datasets", "https://data.europa.eu/en/about/api",
    "https://data.europa.eu/api/hub/search/search?q=bicycle&limit=1", limits="No key", region="EU", expect="result")
add("eurostat", "Eurostat statistics", "Portugal & EU", "EU statistics (population, prices) by country",
    "https://wikis.ec.europa.eu/display/EUROSTATHELP/API+Statistics+-+data+query",
    "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/demo_pjan?geo=PT&sex=T&age=TOTAL&lastTimePeriod=1",
    limits="No key", region="EU", expect="value")
add("ecb-fx", "ECB exchange rates (SDMX)", "Money", "Official euro reference rates",
    "https://data.ecb.europa.eu/help/api/overview",
    "https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A?lastNObservations=1&format=jsondata",
    limits="No key", region="EU", expect="dataSets")
add("uk-police", "UK Police data", "City open data", "Street-level crimes near a UK point", "https://data.police.uk/docs/",
    "https://data.police.uk/api/crimes-street/all-crime?lat=51.5074&lng=-0.1278", limits="No key; 15 req/s; OGL", region="UK")
add("postcodes-io", "Postcodes.io", "Geocoding & places", "UK postcode lookup", "https://postcodes.io/docs",
    "https://api.postcodes.io/postcodes/SW1A1AA", limits="No key; MIT; OGL data", region="UK", expect="result")

# ---------------- Geocoding & places ----------------
G = "Geocoding & places"
add("census-geocoder", "US Census Geocoder", G, "US street address to coordinates (+ districts)",
    "https://geocoding.geo.census.gov/geocoder/Geocoding_Services_API.html",
    "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress?address=401%20N%20Morton%20St%2C%20Bloomington%2C%20IN&benchmark=Public_AR_Current&format=json",
    limits="No key; public domain", region="US", expect="addressMatches")
add("census-geographies", "Census geographies by point", G, "Which county, tract and congressional district a point is in",
    "https://geocoding.geo.census.gov/geocoder/Geocoding_Services_API.html",
    f"https://geocoding.geo.census.gov/geocoder/geographies/coordinates?x={LNG}&y={LAT}&benchmark=Public_AR_Current&vintage=Current_Current&format=json",
    limits="No key; public domain", region="US", expect="geographies")
add("nominatim", "OpenStreetMap Nominatim", G, "Address/place search worldwide", "https://nominatim.org/release-docs/latest/api/Search/",
    "https://nominatim.openstreetmap.org/search?q=Rossio%2C%20Lisboa&format=jsonv2&limit=1",
    limits="Max 1 req/s, identifying User-Agent, no bulk geocoding, attribution (ODbL)",
    terms="https://operations.osmfoundation.org/policies/nominatim/")
add("photon", "Photon (komoot)", G, "Fast OSM place search / autocomplete", "https://photon.komoot.io/",
    "https://photon.komoot.io/api/?q=lisboa&limit=1", limits="No key; fair use; ODbL", expect="features")
add("open-meteo-geocoding", "Open-Meteo Geocoding", G, "City name to coordinates (great for chat)",
    "https://open-meteo.com/en/docs/geocoding-api", "https://geocoding-api.open-meteo.com/v1/search?name=Lisbon&count=1",
    limits="Non-commercial free tier", expect="results")
add("fcc-area", "FCC Area API", G, "County and FIPS code for a US point", "https://geo.fcc.gov/api/census/",
    f"https://geo.fcc.gov/api/census/area?lat={LAT}&lon={LNG}&format=json", limits="No key", region="US", expect="results")
add("zippopotam", "Zippopotam.us", G, "Postal code to place name (60+ countries)", "https://www.zippopotam.us/",
    "https://api.zippopotam.us/us/47401", limits="No key", expect="places")
add("overpass", "Overpass API (OSM)", G, "What's nearby: cafes, toilets, water fountains, benches",
    "https://wiki.openstreetmap.org/wiki/Overpass_API",
    f"https://overpass-api.de/api/interpreter?data=%5Bout%3Ajson%5D%3Bnode(around%3A500%2C{LAT}%2C{LNG})%5Bamenity%3Dcafe%5D%3Bout%203%3B",
    limits="No key; fair use (< 10,000 queries/day); ODbL", expect="elements")
add("open-meteo-elevation", "Open-Meteo Elevation", G, "Elevation of a point", "https://open-meteo.com/en/docs/elevation-api",
    f"https://api.open-meteo.com/v1/elevation?latitude={LAT}&longitude={LNG}", limits="Non-commercial free tier", expect="elevation")
add("rest-countries", "REST Countries", G, "Facts about a country: capital, currency, languages",
    "https://restcountries.com/", "https://restcountries.com/v3.1/alpha/pt", limits="No key; MPL-2.0")
add("wikipedia-geosearch", "Wikipedia nearby", G, "Wikipedia articles about places near a point",
    "https://www.mediawiki.org/wiki/API:Geosearch",
    f"https://en.wikipedia.org/w/api.php?action=query&list=geosearch&gscoord={LAT}%7C{LNG}&gsradius=2000&gslimit=3&format=json&origin=*",
    limits="No key; send User-Agent; CC BY-SA", expect="geosearch")

# ---------------- Sun, time & holidays ----------------
Z = "Sun, time & holidays"
add("sunrise-sunset", "Sunrise-Sunset.org", Z, "Sunrise, sunset and twilight for a place/date", "https://sunrise-sunset.org/api",
    f"https://api.sunrise-sunset.org/json?lat={LAT}&lng={LNG}&formatted=0", limits="No key; attribution requested", expect="sunrise")
add("usno-rstt", "US Naval Observatory sun & moon", Z, "Sun/moon rise and set, moon phase",
    "https://aa.usno.navy.mil/data/api", f"https://aa.usno.navy.mil/api/rstt/oneday?date=2026-10-10&coords={LAT},{LNG}&tz=-4",
    limits="No key; public domain", region="US", expect="sundata")
add("usno-moon", "USNO moon phases", Z, "Upcoming moon phases", "https://aa.usno.navy.mil/data/api",
    "https://aa.usno.navy.mil/api/moon/phases/date?date=2026-10-10&nump=4", limits="No key", region="US", expect="phasedata")
add("nager-date", "Nager.Date public holidays", Z, "Public holidays for 100+ countries", "https://date.nager.at/Api",
    "https://date.nager.at/api/v3/PublicHolidays/2026/US", limits="No key; fair use; MIT")
add("nager-next", "Nager.Date next holidays", Z, "Next public holidays in a country",
    "https://date.nager.at/Api", "https://date.nager.at/api/v3/NextPublicHolidays/PT", limits="No key")
add("openholidays", "OpenHolidays API", Z, "Public and school holidays in Europe (by region)",
    "https://www.openholidaysapi.org/en/",
    "https://openholidaysapi.org/PublicHolidays?countryIsoCode=PT&languageIsoCode=EN&validFrom=2026-01-01&validTo=2026-12-31",
    limits="No key; fair use", region="EU")
add("timeapi", "TimeAPI.io", Z, "Current time in a time zone", "https://timeapi.io/swagger/index.html",
    "https://timeapi.io/api/time/current/zone?timeZone=Europe%2FLisbon", limits="No key; fair use", expect="dateTime")

# ---------------- Money ----------------
F = "Money"
add("frankfurter", "Frankfurter", F, "Currency conversion (ECB reference rates)", "https://frankfurter.dev/",
    "https://api.frankfurter.dev/v1/latest?base=USD&symbols=EUR", limits="No key; no limits stated; ECB data", expect="rates")
add("treasury-fiscal", "US Treasury Fiscal Data", F, "Debt to the penny, interest rates, exchange rates",
    "https://fiscaldata.treasury.gov/api-documentation/",
    "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/debt_to_penny?sort=-record_date&page%5Bsize%5D=1",
    limits="No key", region="US", expect="data")
add("bls-v1", "BLS Public Data API v1", F, "Consumer price index (inflation) and jobs data",
    "https://www.bls.gov/developers/", "https://api.bls.gov/publicAPI/v1/timeseries/data/CUUR0000SA0",
    limits="v1 needs no key: 25 queries/day; free v2 key: 500/day", region="US", expect="Results")
add("coinbase-spot", "Coinbase spot price", F, "Spot price of BTC/ETH in a currency",
    "https://docs.cdp.coinbase.com/coinbase-app/track-apis/prices", "https://api.coinbase.com/v2/prices/BTC-USD/spot",
    limits="No key for public prices", expect="amount")

# ---------------- Books, words & knowledge ----------------
K = "Books, words & knowledge"
add("wikipedia-summary", "Wikipedia page summary", K, "Short summary of any topic", "https://en.wikipedia.org/api/rest_v1/",
    "https://en.wikipedia.org/api/rest_v1/page/summary/Lisbon", limits="No key; 200 req/s; send User-Agent; CC BY-SA", expect="extract")
add("wikipedia-onthisday", "Wikipedia On this day", K, "Historical events on today's date",
    "https://api.wikimedia.org/wiki/Feed_API/Reference/On_this_day",
    "https://api.wikimedia.org/feed/v1/wikipedia/en/onthisday/selected/10/10", limits="No key at low volume; CC BY-SA", expect="selected")
add("open-library", "Open Library search", K, "Find a book, author, first published year", "https://openlibrary.org/developers/api",
    "https://openlibrary.org/search.json?q=the+power+broker&limit=1", limits="No key; send User-Agent; be gentle", expect="docs")
add("gutendex", "Gutendex (Project Gutenberg)", K, "Free public-domain e-books", "https://gutendex.com/",
    "https://gutendex.com/books/?search=dickens", limits="No key", expect="results")
add("loc", "Library of Congress", K, "Search Library of Congress collections", "https://www.loc.gov/apis/",
    "https://www.loc.gov/search/?q=bloomington&fo=json&c=1", limits="No key; rate limited (~20 req/10 s)", region="US", expect="results")
add("dictionaryapi", "Free Dictionary API", K, "Definitions and pronunciation of English words", "https://dictionaryapi.dev/",
    "https://api.dictionaryapi.dev/api/v2/entries/en/civic", limits="No key; CC BY-SA (Wiktionary)")
add("datamuse", "Datamuse", K, "Words that mean/rhyme/sound like", "https://www.datamuse.com/api/",
    "https://api.datamuse.com/words?ml=city&max=3", limits="No key; 100,000 req/day")
add("artic", "Art Institute of Chicago", K, "Artworks, artists and exhibitions", "https://api.artic.edu/docs/",
    "https://api.artic.edu/api/v1/artworks?limit=1&fields=id,title", limits="No key; 60 req/min; CC0 data", region="US", expect="data")
add("met-museum", "The Met Collection", K, "Objects in The Metropolitan Museum of Art", "https://metmuseum.github.io/",
    "https://collectionapi.metmuseum.org/public/collection/v1/objects/436535", limits="No key; 80 req/s; CC0", region="US", expect="title")

# ---------------- Government & safety ----------------
P = "Government & safety"
add("federal-register", "Federal Register", P, "New federal rules and notices", "https://www.federalregister.gov/developers/documentation/api/v1",
    "https://www.federalregister.gov/api/v1/documents.json?per_page=1", limits="No key", region="US", expect="results")
add("usaspending", "USAspending.gov", P, "Federal spending by agency or place", "https://api.usaspending.gov/",
    "https://api.usaspending.gov/api/v2/references/toptier_agencies/", limits="No key", region="US", expect="results")
add("openfda-food", "openFDA food recalls", P, "Recent food recalls (by state or product)", "https://open.fda.gov/apis/food/enforcement/",
    "https://api.fda.gov/food/enforcement.json?limit=1", limits="No key: 240 req/min, 1,000/day per IP; free key: 120,000/day",
    region="US", expect="results")
add("nhtsa-recalls", "NHTSA vehicle recalls", P, "Recalls for a car make/model/year", "https://www.nhtsa.gov/nhtsa-datasets-and-apis",
    "https://api.nhtsa.gov/recalls/recallsByVehicle?make=honda&model=accord&modelYear=2012", limits="No key", region="US", expect="results")
add("nhtsa-vpic", "NHTSA vPIC VIN decoder", P, "Decode a VIN", "https://vpic.nhtsa.dot.gov/api/",
    "https://vpic.nhtsa.dot.gov/api/vehicles/decodevinvalues/1HGCM82633A004352?format=json", limits="No key", region="US", expect="Results")
add("cpsc-recalls", "CPSC product recalls", P, "Consumer product recalls", "https://www.cpsc.gov/Recalls/CPSC-Recalls-Application-Program-Interface-API-Information",
    "https://www.saferproducts.gov/RestWebServices/Recall?format=json&RecallDateStart=2026-09-01", limits="No key", region="US")
add("open-food-facts", "Open Food Facts", P, "Ingredients, allergens and Nutri-Score by barcode",
    "https://openfoodfacts.github.io/openfoodfacts-server/api/", "https://world.openfoodfacts.org/api/v2/product/737628064502.json?fields=product_name,brands",
    limits="No key; 100 req/min for product reads; send User-Agent; ODbL", expect="product")

# ---------------- Flights & space ----------------
X = "Flights & space"
add("wheretheiss", "Where the ISS at?", X, "Where the space station is right now", "https://wheretheiss.at/w/developer",
    "https://api.wheretheiss.at/v1/satellites/25544", limits="No key; ~1 req/s", expect="latitude")
add("launch-library", "Launch Library 2", X, "Next rocket launches", "https://thespacedevs.com/llapi",
    "https://ll.thespacedevs.com/2.3.0/launches/upcoming/?limit=1&mode=list", limits="No key: 15 req/hour", expect="results")
add("nasa-apod", "NASA APOD", X, "NASA Astronomy Picture of the Day", "https://api.nasa.gov/",
    "https://api.nasa.gov/planetary/apod?api_key=DEMO_KEY", auth="demo-key",
    key_note="DEMO_KEY: 30 req/hour, 50/day per IP; free api.nasa.gov key: 1,000/hour", expect="title")
add("nasa-neows", "NASA Near Earth Objects", X, "Asteroids passing Earth today", "https://api.nasa.gov/",
    "https://api.nasa.gov/neo/rest/v1/feed/today?detailed=false&api_key=DEMO_KEY", auth="demo-key",
    key_note="DEMO_KEY rate limits as above", expect="near_earth_objects")
