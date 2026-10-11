"""ISO 3166-1 alpha-2 country codes -> (name, continent). Hand-maintained; continents use the 7-continent model
(plus "Global" for worldwide APIs). Kosovo uses the user-assigned code XK."""
from __future__ import annotations

CONTINENTS = ["Africa", "Antarctica", "Asia", "Europe", "North America", "Oceania", "South America", "Global"]

_RAW = {
    "Africa": "DZ Algeria;AO Angola;BJ Benin;BW Botswana;BF Burkina Faso;BI Burundi;CV Cabo Verde;CM Cameroon;"
              "CF Central African Republic;TD Chad;KM Comoros;CG Congo;CD Congo (DRC);CI Côte d'Ivoire;DJ Djibouti;"
              "EG Egypt;GQ Equatorial Guinea;ER Eritrea;SZ Eswatini;ET Ethiopia;GA Gabon;GM Gambia;GH Ghana;GN Guinea;"
              "GW Guinea-Bissau;KE Kenya;LS Lesotho;LR Liberia;LY Libya;MG Madagascar;MW Malawi;ML Mali;MR Mauritania;"
              "MU Mauritius;YT Mayotte;MA Morocco;MZ Mozambique;NA Namibia;NE Niger;NG Nigeria;RE Réunion;RW Rwanda;"
              "SH Saint Helena;ST São Tomé and Príncipe;SN Senegal;SC Seychelles;SL Sierra Leone;SO Somalia;"
              "ZA South Africa;SS South Sudan;SD Sudan;TZ Tanzania;TG Togo;TN Tunisia;UG Uganda;EH Western Sahara;"
              "ZM Zambia;ZW Zimbabwe",
    "Antarctica": "AQ Antarctica;BV Bouvet Island;GS South Georgia;HM Heard and McDonald Islands;TF French Southern Territories",
    "Asia": "AF Afghanistan;AM Armenia;AZ Azerbaijan;BH Bahrain;BD Bangladesh;BT Bhutan;BN Brunei;KH Cambodia;CN China;"
            "GE Georgia;HK Hong Kong;IN India;ID Indonesia;IR Iran;IQ Iraq;IL Israel;JP Japan;JO Jordan;KZ Kazakhstan;"
            "KW Kuwait;KG Kyrgyzstan;LA Laos;LB Lebanon;MO Macao;MY Malaysia;MV Maldives;MN Mongolia;MM Myanmar;NP Nepal;"
            "KP North Korea;OM Oman;PK Pakistan;PS Palestine;PH Philippines;QA Qatar;SA Saudi Arabia;SG Singapore;"
            "KR South Korea;LK Sri Lanka;SY Syria;TW Taiwan;TJ Tajikistan;TH Thailand;TL Timor-Leste;TR Türkiye;"
            "TM Turkmenistan;AE United Arab Emirates;UZ Uzbekistan;VN Vietnam;YE Yemen;IO British Indian Ocean Territory;"
            "CX Christmas Island;CC Cocos Islands",
    "Europe": "AX Åland Islands;AL Albania;AD Andorra;AT Austria;BY Belarus;BE Belgium;BA Bosnia and Herzegovina;"
              "BG Bulgaria;HR Croatia;CY Cyprus;CZ Czechia;DK Denmark;EE Estonia;FO Faroe Islands;FI Finland;FR France;"
              "DE Germany;GI Gibraltar;GR Greece;GG Guernsey;HU Hungary;IS Iceland;IE Ireland;IM Isle of Man;IT Italy;"
              "JE Jersey;XK Kosovo;LV Latvia;LI Liechtenstein;LT Lithuania;LU Luxembourg;MT Malta;MD Moldova;MC Monaco;"
              "ME Montenegro;NL Netherlands;MK North Macedonia;NO Norway;PL Poland;PT Portugal;RO Romania;RU Russia;"
              "SM San Marino;RS Serbia;SK Slovakia;SI Slovenia;ES Spain;SJ Svalbard and Jan Mayen;SE Sweden;"
              "CH Switzerland;UA Ukraine;GB United Kingdom;VA Vatican City;EU European Union",
    "North America": "AI Anguilla;AG Antigua and Barbuda;AW Aruba;BS Bahamas;BB Barbados;BZ Belize;BM Bermuda;"
                     "BQ Caribbean Netherlands;VG British Virgin Islands;CA Canada;KY Cayman Islands;CR Costa Rica;CU Cuba;"
                     "CW Curaçao;DM Dominica;DO Dominican Republic;SV El Salvador;GL Greenland;GD Grenada;GP Guadeloupe;"
                     "GT Guatemala;HT Haiti;HN Honduras;JM Jamaica;MQ Martinique;MX Mexico;MS Montserrat;NI Nicaragua;"
                     "PA Panama;PR Puerto Rico;BL Saint Barthélemy;KN Saint Kitts and Nevis;LC Saint Lucia;"
                     "MF Saint Martin;PM Saint Pierre and Miquelon;VC Saint Vincent and the Grenadines;SX Sint Maarten;"
                     "TT Trinidad and Tobago;TC Turks and Caicos;US United States;VI US Virgin Islands;UM US Minor Outlying Islands",
    "Oceania": "AS American Samoa;AU Australia;CK Cook Islands;FJ Fiji;PF French Polynesia;GU Guam;KI Kiribati;"
               "MH Marshall Islands;FM Micronesia;NR Nauru;NC New Caledonia;NZ New Zealand;NU Niue;NF Norfolk Island;"
               "MP Northern Mariana Islands;PW Palau;PG Papua New Guinea;PN Pitcairn;WS Samoa;SB Solomon Islands;"
               "TK Tokelau;TO Tonga;TV Tuvalu;VU Vanuatu;WF Wallis and Futuna",
    "South America": "AR Argentina;BO Bolivia;BR Brazil;CL Chile;CO Colombia;EC Ecuador;FK Falkland Islands;"
                     "GF French Guiana;GY Guyana;PY Paraguay;PE Peru;SR Suriname;UY Uruguay;VE Venezuela",
}

COUNTRIES: dict = {}
for _cont, _s in _RAW.items():
    for _item in _s.split(";"):
        _code, _name = _item.split(" ", 1)
        COUNTRIES[_code] = (_name, _cont)
_ALIASES = {"UK": "GB", "EL": "GR"}
_NAME_TO_CODE = {v[0].lower(): k for k, v in COUNTRIES.items()}
_NAME_TO_CODE.update({"usa": "US", "united states of america": "US", "the netherlands": "NL", "england": "GB",
                      "scotland": "GB", "wales": "GB", "korea": "KR", "brasil": "BR", "méxico": "MX",
                      "italia (ita)": "IT", "italia": "IT", "turkey": "TR", "czech republic": "CZ", "uk": "GB",
                      "dublin": "IE", "toronto": "CA", "prague": "CZ", "milan": "IT", "london": "GB",
                      "barcelona": "ES", "santander": "ES", "mendoza": "AR", "minnesota": "US", "québec": "CA",
                      "mexico city": "MX", "chicago metro area": "US"})
_US_STATES = {"ny", "nv", "mi", "ca", "tx", "il", "wa", "va", "co", "ma", "or", "pa", "nc", "fl", "ga", "oh", "md", "nj",
              "mn", "az", "ut", "ky", "in", "mo", "wi", "tn"}


def norm_code(code: str | None) -> str | None:
    c = (code or "").strip().upper()
    c = _ALIASES.get(c, c)
    return c if c in COUNTRIES else None


def continent(code: str | None) -> str:
    c = norm_code(code)
    return COUNTRIES[c][1] if c else "Global"


def country_name(code: str | None) -> str:
    c = norm_code(code)
    return COUNTRIES[c][0] if c else ""


def code_from_text(text: str) -> str | None:
    """Best-effort country code from a free-text location such as 'Hamburg, Germany' or 'Reno, NV, USA'."""
    t = (text or "").strip().rstrip(".").lower()
    if not t:
        return None
    if t in _NAME_TO_CODE:
        return _NAME_TO_CODE[t]
    parts = [p.strip() for p in t.replace(" - ", ",").split(",") if p.strip()]
    for p in reversed(parts):
        if p in _NAME_TO_CODE:
            return _NAME_TO_CODE[p]
        if p in _US_STATES:
            return "US"
    for name, code in sorted(_NAME_TO_CODE.items(), key=lambda kv: -len(kv[0])):
        if len(name) > 4 and name in t:
            return code
    return None


def slug(text: str) -> str:
    import re
    import unicodedata
    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:60] or "x"
