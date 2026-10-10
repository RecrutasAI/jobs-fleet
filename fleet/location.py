"""Location text → country, US state, city, remote (normalization step 1).

Every hiring system writes locations differently ("Houston, TX, United States",
"Chicago, IL, us", "Remote (US)", "Montreal, Quebec, CA, H4S 2B4", several
locations separated by ";" or "|"). Rules are deterministic and tested against
real strings from the dataset. Unknown stays unknown (None): never a guess.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

US_STATES = {
    "AL": "alabama", "AK": "alaska", "AZ": "arizona", "AR": "arkansas", "CA": "california", "CO": "colorado",
    "CT": "connecticut", "DE": "delaware", "FL": "florida", "GA": "georgia", "HI": "hawaii", "ID": "idaho",
    "IL": "illinois", "IN": "indiana", "IA": "iowa", "KS": "kansas", "KY": "kentucky", "LA": "louisiana",
    "ME": "maine", "MD": "maryland", "MA": "massachusetts", "MI": "michigan", "MN": "minnesota",
    "MS": "mississippi", "MO": "missouri", "MT": "montana", "NE": "nebraska", "NV": "nevada",
    "NH": "new hampshire", "NJ": "new jersey", "NM": "new mexico", "NY": "new york", "NC": "north carolina",
    "ND": "north dakota", "OH": "ohio", "OK": "oklahoma", "OR": "oregon", "PA": "pennsylvania",
    "RI": "rhode island", "SC": "south carolina", "SD": "south dakota", "TN": "tennessee", "TX": "texas",
    "UT": "utah", "VT": "vermont", "VA": "virginia", "WA": "washington", "WV": "west virginia",
    "WI": "wisconsin", "WY": "wyoming", "DC": "district of columbia", "PR": "puerto rico",
}
STATE_BY_NAME = {name: code for code, name in US_STATES.items()} | {"washington dc": "DC", "washington d.c.": "DC"}

CA_PROVINCES = {
    "AB": "alberta", "BC": "british columbia", "MB": "manitoba", "NB": "new brunswick", "NL": "newfoundland and labrador",
    "NS": "nova scotia", "NT": "northwest territories", "NU": "nunavut", "ON": "ontario", "PE": "prince edward island",
    "QC": "quebec", "SK": "saskatchewan", "YT": "yukon",
}
PROVINCE_NAMES = set(CA_PROVINCES.values()) | {"québec"}

# Country names and aliases → ISO 3166-1 alpha-2. Extend as new strings appear.
COUNTRIES = {
    "united states": "US", "united states of america": "US", "usa": "US", "u.s.": "US", "u.s.a.": "US", "us": "US",
    "america": "US", "canada": "CA", "mexico": "MX", "méxico": "MX", "united kingdom": "GB", "uk": "GB",
    "great britain": "GB", "england": "GB", "scotland": "GB", "ireland": "IE", "india": "IN", "germany": "DE",
    "france": "FR", "spain": "ES", "portugal": "PT", "italy": "IT", "netherlands": "NL", "belgium": "BE",
    "switzerland": "CH", "austria": "AT", "sweden": "SE", "norway": "NO", "denmark": "DK", "finland": "FI",
    "poland": "PL", "estonia": "EE", "bulgaria": "BG", "romania": "RO", "czech republic": "CZ", "czechia": "CZ",
    "hungary": "HU", "greece": "GR", "turkey": "TR", "türkiye": "TR", "israel": "IL", "saudi arabia": "SA",
    "united arab emirates": "AE", "uae": "AE", "qatar": "QA", "egypt": "EG", "morocco": "MA", "tunisia": "TN",
    "south africa": "ZA", "nigeria": "NG", "kenya": "KE", "brazil": "BR", "argentina": "AR", "chile": "CL",
    "colombia": "CO", "peru": "PE", "costa rica": "CR", "philippines": "PH", "singapore": "SG", "malaysia": "MY",
    "indonesia": "ID", "thailand": "TH", "vietnam": "VN", "japan": "JP", "south korea": "KR", "korea": "KR",
    "china": "CN", "hong kong": "HK", "taiwan": "TW", "australia": "AU", "new zealand": "NZ", "pakistan": "PK",
    "bangladesh": "BD", "sri lanka": "LK", "ukraine": "UA", "serbia": "RS", "croatia": "HR", "lithuania": "LT",
    "latvia": "LV", "luxembourg": "LU", "slovakia": "SK", "slovenia": "SI", "puerto rico": "US",
}
ISO2 = set(COUNTRIES.values())

POSTAL = re.compile(r"^(\d{5}(-\d{4})?|[A-Z]\d[A-Z] ?\d[A-Z]\d|\d{4,6})$", re.IGNORECASE)
REMOTE = re.compile(r"\b(remote|anywhere|work from home|wfh|telecommute|distributed)\b", re.IGNORECASE)
SEGMENT_SPLIT = re.compile(r"\s*[;|]\s*")


@dataclass
class Place:
    country: str | None = None
    state: str | None = None
    city: str | None = None


@dataclass
class Location:
    countries: list[str] = field(default_factory=list)   # every country mentioned, in order
    country_iso: str | None = None                        # the first one
    us_state: str | None = None                           # set only when the job names one US state
    city: str | None = None
    is_remote: bool = False
    is_us: bool = False


def _country_token(tok: str) -> str | None:
    """A token that is a country by itself: a name, an alias, or a lower-case ISO code ("us", "ca", "tn")."""
    t = tok.strip().strip(".").strip()
    low = t.lower()
    if low in COUNTRIES:
        return COUNTRIES[low]
    if len(t) == 2 and t.islower() and t.upper() in ISO2 | {"MX", "TN", "MA", "EG", "RO", "DE"}:
        return t.upper()  # SmartRecruiters writes country codes in lower case
    if len(t) == 2 and t.isupper() and t in ISO2 and t not in US_STATES and t not in CA_PROVINCES:
        return t  # "GB", "IN", "MX" in upper case, when it can't be a state or province
    return None


def _segment(text: str) -> tuple[Place, bool]:
    remote = bool(REMOTE.search(text))
    s = REMOTE.sub(" ", text) if remote else text
    s = re.sub(r"[()\[\]]", " ", s)
    s = re.sub(r"\s+-\s*|\s*-\s+", ", ", s)      # "Remote - Canada" / "Remote- Canada" → separators
    parts = [p.strip() for p in s.split(",")]
    parts = [p for p in parts if p and not POSTAL.match(p)]
    place = Place()
    if not parts:
        return place, remote

    # 1. Explicit country at the end (allowing "Michigan USA" written without a comma).
    last = parts[-1]
    m = re.match(r"^(.*?)\s+(usa|u\.s\.a?\.?|united states)$", last, re.IGNORECASE)
    if m and m.group(1):
        parts = parts[:-1] + [m.group(1), m.group(2)]
        last = parts[-1]
    country = _country_token(last)
    if country:
        parts = parts[:-1]
    elif last == "CA" and len(parts) >= 2 and (parts[-2].lower() in PROVINCE_NAMES or parts[-2] in CA_PROVINCES):
        country, parts = "CA", parts[:-1]          # "Montreal, Quebec, CA"

    # 2. State / province from what's left.
    if parts:
        tail = parts[-1].strip(".")
        if tail in US_STATES and country in (None, "US"):
            country, place.state, parts = "US", tail, parts[:-1]
        elif tail.lower() in STATE_BY_NAME and country in (None, "US"):
            country, place.state, parts = "US", STATE_BY_NAME[tail.lower()], parts[:-1]
        elif (tail in CA_PROVINCES or tail.lower() in PROVINCE_NAMES) and country in (None, "CA"):
            country, parts = "CA", parts[:-1]
        elif country:
            parts = parts[:-1] if len(parts) > 1 else parts   # drop a region we don't model ("Karnataka")

    if parts:
        place.city = parts[0].strip() or None
    place.country = country
    return place, remote


def parse(text: str | None, is_remote: bool | None = None) -> Location:
    loc = Location(is_remote=bool(is_remote))
    if not text or not text.strip():
        return loc
    places: list[Place] = []
    for seg in SEGMENT_SPLIT.split(text.strip()):
        if seg:
            place, remote = _segment(seg)
            loc.is_remote = loc.is_remote or remote
            places.append(place)
    for p in places:
        if p.country and p.country not in loc.countries:
            loc.countries.append(p.country)
    loc.country_iso = loc.countries[0] if loc.countries else None
    loc.is_us = "US" in loc.countries
    us_states = {p.state for p in places if p.state}
    if len(us_states) == 1:
        loc.us_state = us_states.pop()
    if len(places) == 1:
        loc.city = places[0].city
    return loc
