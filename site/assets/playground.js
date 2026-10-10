// civicbot browser playground: a tiny rule-based router (like the real robot; no AI) over CORS-enabled free APIs.
"use strict";
const $ = id => document.getElementById(id);
const WMO = {0:"clear",1:"mostly clear",2:"partly cloudy",3:"overcast",45:"fog",48:"freezing fog",51:"light drizzle",53:"drizzle",
  55:"heavy drizzle",61:"light rain",63:"rain",65:"heavy rain",66:"freezing rain",67:"freezing rain",71:"light snow",73:"snow",
  75:"heavy snow",77:"snow grains",80:"rain showers",81:"rain showers",82:"violent rain showers",85:"snow showers",
  86:"heavy snow showers",95:"thunderstorms",96:"thunderstorms with hail",99:"thunderstorms with hail"};
const ISSUES = ["pothole","streetlight","street light","graffiti","trash","garbage","litter","sidewalk","tree","sign","signal",
  "noise","parking","abandoned","flooding","leak","water main","snow","ice","dumping","rodent","rat"];
let ENDPOINTS = null, last = 0;
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function j(url) {
  const r = await fetch(url, {headers: {"Accept": "application/json"}});
  if (!r.ok) throw new Error(`${new URL(url).host} answered HTTP ${r.status}`);
  return r.json();
}
function placeOf(text) {
  const m = text.match(/\b(?:in|at|near|for)\s+([A-Za-zÀ-ÿ .,'-]{2,60})$/i);
  return (m ? m[1] : $("city").value).trim().replace(/[?.!]+$/, "");
}
async function geocode(place) {
  const name = place.split(",")[0].trim();
  const d = await j(`https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(name)}&count=5&language=en&format=json`);
  if (!d.results || !d.results.length) throw new Error(`I couldn't find “${place}”.`);
  const hint = (place.split(",")[1] || "").trim().toLowerCase();
  const pick = d.results.find(r => hint && [r.admin1, r.country, r.country_code].some(x => x && x.toLowerCase().startsWith(hint)))
    || d.results.find(r => hint.length === 2 && r.admin1 && STATES[hint.toUpperCase()] === r.admin1) || d.results[0];
  return {lat: pick.latitude, lng: pick.longitude, label: `${pick.name}${pick.admin1 ? ", " + pick.admin1 : ""}`, cc: pick.country_code};
}
const STATES = {AL:"Alabama",AK:"Alaska",AZ:"Arizona",AR:"Arkansas",CA:"California",CO:"Colorado",CT:"Connecticut",DE:"Delaware",
  FL:"Florida",GA:"Georgia",HI:"Hawaii",ID:"Idaho",IL:"Illinois",IN:"Indiana",IA:"Iowa",KS:"Kansas",KY:"Kentucky",LA:"Louisiana",
  ME:"Maine",MD:"Maryland",MA:"Massachusetts",MI:"Michigan",MN:"Minnesota",MS:"Mississippi",MO:"Missouri",MT:"Montana",NE:"Nebraska",
  NV:"Nevada",NH:"New Hampshire",NJ:"New Jersey",NM:"New Mexico",NY:"New York",NC:"North Carolina",ND:"North Dakota",OH:"Ohio",
  OK:"Oklahoma",OR:"Oregon",PA:"Pennsylvania",RI:"Rhode Island",SC:"South Carolina",SD:"South Dakota",TN:"Tennessee",TX:"Texas",
  UT:"Utah",VT:"Vermont",VA:"Virginia",WA:"Washington",WV:"West Virginia",WI:"Wisconsin",WY:"Wyoming",DC:"District of Columbia"};
const r0 = x => Math.round(x);

const SKILLS = [
  {name: "open-meteo-tomorrow", test: t => /\b(tomorrow|tmrw)\b/.test(t), run: async t => {
    const g = await geocode(placeOf(t));
    const d = await j(`https://api.open-meteo.com/v1/forecast?latitude=${g.lat}&longitude=${g.lng}&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code&temperature_unit=fahrenheit&timezone=auto&forecast_days=2`);
    const x = i => d.daily[i][1];
    return `Tomorrow in ${g.label}: ${WMO[x("weather_code")] || "code " + x("weather_code")}, high ${r0(x("temperature_2m_max"))}°F, low ${r0(x("temperature_2m_min"))}°F, ${x("precipitation_probability_max")}% chance of rain. Data: Open-Meteo`; }},
  {name: "air-quality", test: t => /\b(air|aqi|smog|pollution|smoke|haze)\b/.test(t), run: async t => {
    const g = await geocode(placeOf(t));
    const d = await j(`https://air-quality-api.open-meteo.com/v1/air-quality?latitude=${g.lat}&longitude=${g.lng}&current=us_aqi,pm2_5&timezone=auto`);
    return `Air quality in ${g.label}: US AQI ${r0(d.current.us_aqi)}, PM2.5 ${d.current.pm2_5} µg/m³. Data: Open-Meteo/CAMS`; }},
  {name: "uv-index", test: t => /\b(uv|sunscreen|sunburn)\b/.test(t), run: async t => {
    const g = await geocode(placeOf(t));
    const d = await j(`https://api.open-meteo.com/v1/forecast?latitude=${g.lat}&longitude=${g.lng}&current=uv_index&daily=uv_index_max&timezone=auto&forecast_days=1`);
    return `UV index in ${g.label}: ${d.current.uv_index} now, peak ${d.daily.uv_index_max[0]} today. Data: Open-Meteo`; }},
  {name: "sun-times", test: t => /\b(sunrise|sunset|dawn|dusk|daylight)\b/.test(t), run: async t => {
    const g = await geocode(placeOf(t));
    const d = await j(`https://api.open-meteo.com/v1/forecast?latitude=${g.lat}&longitude=${g.lng}&daily=sunrise,sunset&timezone=auto&forecast_days=1`);
    return `${g.label}: sunrise ${d.daily.sunrise[0].slice(11)}, sunset ${d.daily.sunset[0].slice(11)} (local time). Data: Open-Meteo`; }},
  {name: "earthquakes-near", test: t => /\b(earthquakes?|quakes?|seismic|tremor)\b/.test(t), run: async t => {
    const g = await geocode(placeOf(t)), since = new Date(Date.now() - 7 * 864e5).toISOString().slice(0, 10);
    const d = await j(`https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&latitude=${g.lat}&longitude=${g.lng}&maxradiuskm=500&starttime=${since}&minmagnitude=2.5&orderby=time&limit=3`);
    if (!d.features.length) return `No M2.5+ earthquakes within 500 km of ${g.label} in the last week (USGS).`;
    return `Quakes near ${g.label}, last 7 days: ` + d.features.map(f => `M${f.properties.mag} ${f.properties.place} (${new Date(f.properties.time).toISOString().slice(0, 10)})`).join("; ") + ". Data: USGS"; }},
  {name: "nws-alerts", test: t => /\b(alerts?|warnings?|watch|advisory|tornado|severe)\b/.test(t) && !/\b(mbta|tube|t)\b/.test(t), run: async t => {
    const g = await geocode(placeOf(t));
    if (g.cc && g.cc !== "US") return `NWS alerts cover the US only; ${g.label} is outside.`;
    const d = await j(`https://api.weather.gov/alerts/active?point=${g.lat.toFixed(4)},${g.lng.toFixed(4)}`);
    if (!d.features.length) return `No active NWS alerts for ${g.label} right now.`;
    return `NWS alerts for ${g.label}: ` + [...new Set(d.features.map(f => f.properties.event))].slice(0, 3).join("; ") + "."; }},
  {name: "currency-convert", test: t => /\b[a-z]{3}\s+(to|in|into)\s+[a-z]{3}\b/.test(t) || /\b(exchange rate|convert)\b/.test(t), run: async t => {
    const m = t.match(/(\d+(?:\.\d+)?)?\s*\b([a-z]{3})\s+(?:to|in|into)\s+([a-z]{3})\b/) || [null, null, "usd", "eur"];
    const amt = parseFloat(m[1] || "1"), from = m[2].toUpperCase(), to = m[3].toUpperCase();
    const d = await j(`https://api.frankfurter.dev/v1/latest?base=${from}&symbols=${to}`);
    const rate = d.rates[to]; if (rate === undefined) throw new Error(`No ECB rate for ${from}→${to}.`);
    return `${amt} ${from} = ${(amt * rate).toFixed(2)} ${to} (ECB reference rate, ${d.date}). Data: Frankfurter`; }},
  {name: "public-holidays", test: t => /\b(holidays?|feriados?|bank holiday)\b/.test(t), run: async t => {
    const m = t.match(/\b(?:in|for)\s+([a-z]{2})\b/); const cc = (m ? m[1] : "us").toUpperCase();
    const d = await j(`https://date.nager.at/api/v3/NextPublicHolidays/${cc}`);
    return `Next public holidays in ${cc}: ` + d.slice(0, 3).map(h => `${h.name} (${h.date})`).join("; ") + ". Data: Nager.Date"; }},
  {name: "zip-lookup", test: t => /\bzip\b/.test(t) && /\b\d{5}\b/.test(t), run: async t => {
    const z = t.match(/\b(\d{5})\b/)[1], d = await j(`https://api.zippopotam.us/us/${z}`);
    return `ZIP ${z} is ${d.places[0]["place name"]}, ${d.places[0].state}. Data: Zippopotam.us`; }},
  {name: "iss-location", test: t => /\b(iss|space station)\b/.test(t), run: async () => {
    const d = await j("https://api.wheretheiss.at/v1/satellites/25544");
    return `The ISS is over ${d.latitude.toFixed(1)}°, ${d.longitude.toFixed(1)}° at ${r0(d.altitude)} km, moving ${r0(d.velocity)} km/h (${d.visibility}). Data: wheretheiss.at`; }},
  {name: "tube-status", test: t => /\b(tube|underground|tfl)\b/.test(t), run: async () => {
    const d = await j("https://api.tfl.gov.uk/Line/Mode/tube/Status");
    const bad = d.filter(l => l.lineStatuses[0].statusSeverity !== 10);
    return bad.length ? "Tube now: " + bad.map(l => `${l.name}: ${l.lineStatuses[0].statusSeverityDescription}`).join("; ") + "; other lines good service. Data: TfL"
      : "Good service on all Tube lines. Data: TfL"; }},
  {name: "mbta-alerts", test: t => /\b(mbta|red line|orange line|green line|blue line)\b/.test(t), run: async () => {
    const d = await j("https://api-v3.mbta.com/alerts?filter[route_type]=0,1&filter[activity]=BOARD,EXIT,RIDE&filter[datetime]=NOW&page[limit]=4&sort=-severity");
    return d.data.length ? "MBTA subway alerts now: " + d.data.map(a => a.attributes.service_effect || a.attributes.short_header).join("; ") + ". Data: MBTA" : "No active MBTA subway alerts right now."; }},
  {name: "vehicle-recalls", test: t => /\brecalls?\b/.test(t) && /\b(19|20)\d{2}\s+[a-z-]+\s+[a-z0-9-]+/.test(t), run: async t => {
    const m = t.match(/\b((?:19|20)\d{2})\s+([a-z-]+)\s+([a-z0-9-]+)/);
    const d = await j(`https://api.nhtsa.gov/recalls/recallsByVehicle?make=${m[2]}&model=${m[3]}&modelYear=${m[1]}`);
    if (!d.Count) return `NHTSA lists no recalls for the ${m[1]} ${m[2]} ${m[3]}.`;
    return `${m[1]} ${m[2]} ${m[3]}: ${d.Count} NHTSA recalls, e.g. ` + d.results.slice(0, 2).map(r => r.Component).join("; ") + ". Check your VIN at nhtsa.gov"; }},
  {name: "food-recalls", test: t => /\b(food|fda)\b/.test(t) && /\brecalls?\b/.test(t), run: async () => {
    const d = await j("https://api.fda.gov/food/enforcement.json?sort=report_date:desc&limit=3");
    return "Latest FDA food recalls: " + d.results.map(r => `${r.recalling_firm}: ${r.reason_for_recall.slice(0, 70)}`).join("; ") + ". Data: openFDA"; }},
  {name: "wikipedia-summary", test: t => /\b(wiki|wikipedia|tell me about)\b/.test(t), run: async t => {
    const m = t.match(/(?:wiki(?:pedia)?|tell me about)\s+(.{2,60})$/); if (!m) throw new Error("Try: wiki Lisbon");
    const d = await j(`https://en.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(m[1].trim())}`);
    return `${(d.extract || "").slice(0, 230)} (Wikipedia)`; }},
  {name: "city-311-report", test: t => ISSUES.some(w => t.includes(w)), run: async t => {
    const issue = ISSUES.find(w => t.includes(w));
    const m = t.match(/\b(?:at|on|near)\s+(.{3,80})$/);
    const where = m ? m[1] : $("city").value;
    const city = $("city").value;
    const g = await geocode(where.includes(",") ? where : city);
    ENDPOINTS = ENDPOINTS || await j("data/endpoints.json");
    const ep = ENDPOINTS.endpoints.find(e => e.bbox && g.lat >= e.bbox[0] && g.lat <= e.bbox[2] && g.lng >= e.bbox[1] && g.lng <= e.bbox[3]);
    const via = ep ? `${ep.name} 311 (Open311)` : "SeeClickFix (covers many US towns) or your city's 311 site";
    return `Dry run: I'd draft a “${issue}” report at ${m ? m[1] : "your location"} for ${via}. Nothing is filed from the playground, and in free mode the robot never files.`; }},
  {name: "open-meteo-weather", test: t => /\b(weather|temp|temperature|rain|raining|wind|windy|forecast|cold|warm|hot)\b/.test(t), run: async t => {
    const g = await geocode(placeOf(t));
    const d = await j(`https://api.open-meteo.com/v1/forecast?latitude=${g.lat}&longitude=${g.lng}&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone=auto`);
    const c = d.current;
    return `${g.label}: ${r0(c.temperature_2m)}°F (feels like ${r0(c.apparent_temperature)}°F), ${WMO[c.weather_code] || "code " + c.weather_code}, wind ${r0(c.wind_speed_10m)} mph at ${c.time.slice(11)}. Data: Open-Meteo`; }},
];
const HELP = "I answer from free public APIs. Try: weather tomorrow in Lisbon · air quality · sunset · earthquakes near Anchorage · " +
  "any alerts · 100 usd to eur · holidays in PT · wiki Lisbon · zip 47401 · where is the iss · tube status · mbta alerts · " +
  "recalls 2018 honda civic · food recalls · pothole at Kirkwood Ave";

function say(who, text, meta) {
  const d = document.createElement("div"); d.className = "msg " + who;
  const s = document.createElement("span"); s.textContent = text; d.append(s);
  if (meta) { const m = document.createElement("small"); m.className = "meta"; m.textContent = meta; d.append(m); }
  $("chat").append(d); $("chat").scrollTop = $("chat").scrollHeight;
}
async function ask(raw) {
  const text = raw.replace(/@\w+/g, "").trim(); if (!text) return;
  say("you", "@yourrobot " + text);
  const wait = 1000 - (Date.now() - last); if (wait > 0) await sleep(wait); last = Date.now();
  const t = text.toLowerCase(), sk = SKILLS.find(s => s.test(t));
  if (!sk) return say("bot", HELP);
  try {
    let reply = await sk.run(t); if (reply.length > 280) reply = reply.slice(0, 279) + "…";
    say("bot", reply, `skill: ${sk.name} · ${reply.length}/280 chars · on X: @yourrobot learn ${sk.name}`);
  } catch (e) { say("bot", "Sorry: " + e.message, `skill: ${sk.name}`); }
}
["weather tomorrow in Lisbon", "air quality", "earthquakes near Anchorage", "100 usd to eur", "holidays in PT",
 "wiki Bloomington, Indiana", "where is the iss", "tube status", "recalls 2018 honda civic", "pothole at Kirkwood Ave"].forEach(c => {
  const b = document.createElement("button"); b.type = "button"; b.textContent = c; b.onclick = () => ask(c); $("chips").append(b); });
$("ask").addEventListener("submit", e => { e.preventDefault(); const v = $("msg").value; $("msg").value = ""; ask(v); });
say("bot", "Hi! I'm a demo of your civic robot. " + HELP);
