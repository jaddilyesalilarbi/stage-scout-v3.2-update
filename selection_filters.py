"""Conservative Europe-only and non-summer internship selection rules.

Explicitly non-European postings are excluded. An unrecognized or missing
location is kept with a warning: guessing a country would lose valid jobs.
"""
from __future__ import annotations

from functools import lru_cache
import re
import unicodedata


# Geographic Europe for this user's search, not just EU membership. Countries
# on a continental boundary without a specified European city are uncertain.
EUROPE_ALPHA2 = frozenset({
    "AD", "AL", "AT", "BA", "BE", "BG", "BY", "CH", "CY", "CZ", "DE",
    "DK", "EE", "ES", "FI", "FR", "GB", "GR", "HR", "HU", "IE", "IS",
    "IT", "LI", "LT", "LU", "LV", "MC", "MD", "ME", "MK", "MT", "NL",
    "NO", "PL", "PT", "RO", "RS", "SE", "SI", "SK", "SM", "UA", "VA", "XK",
})
UNCERTAIN_BORDER_COUNTRIES = {"AM", "AZ", "GE", "KZ", "RU", "TR"}

EUROPE_ALIASES = {
    "europe", "european union", "eu", "eea", "european economic area",
    "uk", "united kingdom", "great britain", "britain", "england", "scotland",
    "wales", "northern ireland", "kosovo", "pays bas", "suisse", "schweiz",
    "deutschland", "osterreich", "espana", "italia", "belgique", "nederland",
    "suede", "sverige", "danmark", "norge", "suomi", "polska", "tchequie",
    "republique tcheque", "croatie", "roumanie", "grece", "portugal",
}
OUTSIDE_ALIASES = {
    "usa", "u s a", "us", "u s", "united states", "america", "etats unis",
    "canada", "australia", "australie", "new zealand", "nouvelle zelande",
    "singapore", "singapour", "hong kong", "taiwan", "south korea", "north korea",
    "uae", "united arab emirates", "emirats arabes unis", "china", "chine",
    "india", "inde", "japan", "japon", "south africa", "afrique du sud",
    "mexico", "mexique", "brazil", "bresil", "argentina", "argentine",
    "french guiana", "guyane", "reunion", "guadeloupe", "martinique", "mayotte",
    "new caledonia", "nouvelle caledonie", "french polynesia", "polynesie francaise",
    "asia", "africa", "north america", "south america", "oceania",
    "texas", "california", "arizona", "alaska", "alabama", "arkansas",
    "colorado", "connecticut", "delaware", "florida", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
    "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york", "north carolina",
    "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania",
    "rhode island", "south carolina", "south dakota", "tennessee", "utah",
    "vermont", "virginia", "washington", "west virginia", "wisconsin",
    "wyoming", "district of columbia", "ontario", "quebec", "british columbia",
    "alberta", "manitoba", "saskatchewan", "nova scotia", "new brunswick",
    "prince edward island", "newfoundland and labrador", "nunavut",
    "northwest territories", "yukon",
}

EUROPE_CITIES = {
    "paris", "lyon", "toulouse", "grenoble", "marseille", "bordeaux", "lille",
    "strasbourg", "nantes", "nice", "montpellier", "saclay", "palaiseau",
    "lausanne", "geneva", "geneve", "zurich", "basel", "bale", "bern",
    "berne", "neuchatel", "fribourg", "lucerne", "winterthur", "zug",
    "st gallen", "eindhoven", "delft", "amsterdam", "rotterdam", "utrecht",
    "the hague", "leiden", "leuven", "brussels", "bruxelles", "antwerp",
    "anvers", "luxembourg", "london", "oxford", "cambridge", "bristol",
    "manchester", "edinburgh", "glasgow", "dublin", "cork", "munich",
    "muenchen", "munchen", "berlin", "hamburg", "stuttgart", "frankfurt",
    "cologne", "koln", "karlsruhe", "freiburg", "nuremberg", "aachen",
    "darmstadt", "dresden", "vienna", "wien", "graz", "salzburg", "linz",
    "innsbruck", "milan", "milano", "turin", "torino", "rome", "roma",
    "bologna", "florence", "genoa", "pisa", "barcelona", "madrid",
    "valencia", "bilbao", "seville", "stockholm", "gothenburg", "goteborg",
    "uppsala", "malmo", "copenhagen", "kobenhavn", "aarhus", "odense",
    "oslo", "bergen", "trondheim", "helsinki", "tampere", "espoo",
    "warsaw", "warszawa", "krakow", "wroclaw", "gdansk", "prague", "praha",
    "brno", "bratislava", "budapest", "ljubljana", "zagreb", "bucharest",
    "sofia", "tallinn", "riga", "vilnius", "lisbon", "lisboa", "porto",
    "reykjavik", "moscow", "saint petersburg", "st petersburg", "istanbul",
}
OUTSIDE_CITIES = {
    "san francisco", "new york", "los angeles", "alameda", "mountain view",
    "palo alto", "berkeley", "boston", "seattle", "austin", "houston",
    "chicago", "san jose", "san diego", "atlanta", "washington dc",
    "washington d c", "wilmington", "portland", "denver", "detroit",
    "dallas", "miami", "philadelphia", "minneapolis", "toronto",
    "vancouver", "montreal", "ottawa", "quebec", "calgary", "waterloo",
    "ontario", "edmonton", "mexico city", "sao paulo", "buenos aires",
    "santiago", "bogota", "lima", "sydney", "melbourne", "brisbane",
    "perth", "auckland", "wellington", "singapore", "bangalore",
    "bengaluru", "mumbai", "hyderabad", "new delhi", "delhi", "dubai",
    "abu dhabi", "tel aviv", "jerusalem", "tokyo", "osaka", "beijing",
    "shanghai", "shenzhen", "seoul", "busan", "taipei", "hong kong",
    "cairo", "cape town", "johannesburg", "casablanca", "rabat",
    "algiers", "nairobi", "lagos", "shanghai", "shenyang",
    # Asia-Pacific cities frequently published without a country field.
    "ho chi minh city", "ho chi minh", "saigon", "hanoi", "ha noi",
    "rayong", "bangkok", "chonburi", "pattaya", "samud prakan",
    "ayutthaya", "da nang", "danang", "hai phong", "bien hoa",
    "kuala lumpur", "penang", "johor bahru", "kulim", "ipoh",
    "manila", "makati", "quezon city", "cebu", "jakarta", "surabaya",
    "bandung", "batam", "yogyakarta", "phnom penh", "siem reap",
    "dhaka", "chittagong", "kolkata", "chennai", "pune", "noida",
    "gurugram", "gurgaon", "ahmedabad", "nagoya", "yokohama",
    "fukuoka", "kyoto", "sapporo", "taichung", "kaohsiung",
    "guangzhou", "dongguan", "suzhou", "chengdu", "wuhan", "qingdao",
}
# Most common North American state/province suffixes. These take precedence
# over shared city names such as Paris (TX), London (ON), Berlin (CT).
NORTH_AMERICAN_REGION_CODES = frozenset({
    "AK", "AL", "AR", "AZ", "BC", "CA", "CO", "CT", "DC", "DE", "FL", "GA",
    "HI", "IA", "ID", "IL", "IN", "KS", "KY", "LA", "MA", "MB", "MD", "ME",
    "MI", "MN", "MO", "MS", "MT", "NB", "NC", "ND", "NE", "NH", "NJ", "NL",
    "NM", "NS", "NT", "NU", "NV", "NY", "OH", "OK", "ON", "OR", "PA",
    "PE", "QC", "RI", "SC", "SD", "SK", "TN", "TX", "UT", "VA", "VT",
    "WA", "WI", "WV", "WY", "YT",
})
# There are collisions with European ISO codes, e.g. DE=Germany/Delaware,
# NL=Netherlands/Newfoundland. Do not mark them as North American without
# an outside-Europe city/country signal.
AMBIGUOUS_REGION_CODES = {"DE", "NL", "ME", "AL", "MD"}


def normalize(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[\u2013\u2014\u2011]", "-", text)
    return re.sub(r"\s+", " ", text).strip()


@lru_cache(maxsize=10)
def _compiled_phrases(phrases: frozenset[str]) -> re.Pattern:
    # A single compiled alternation is far faster than hundreds of regex
    # searches for every worldwide ATS posting (especially unknown locations).
    tokens = "|".join(re.escape(p) for p in sorted(phrases, key=len, reverse=True))
    return re.compile(r"(?<![a-z0-9])(?:" + tokens + r")(?![a-z0-9])")


def has_phrase(text: str, phrases: set[str] | frozenset[str]) -> bool:
    if not phrases:
        return False
    return bool(_compiled_phrases(frozenset(phrases)).search(text))


@lru_cache(maxsize=1)
def country_phrases() -> tuple[frozenset[str], frozenset[str]]:
    """Use ISO names to recognize locations worldwide, not just popular cities."""
    import pycountry
    europe, other = set(EUROPE_ALIASES), set(OUTSIDE_ALIASES)
    for country in pycountry.countries:
        code = country.alpha_2
        if code in UNCERTAIN_BORDER_COUNTRIES:
            continue
        dest = europe if code in EUROPE_ALPHA2 else other
        for attribute in ("name", "official_name", "common_name"):
            value = normalize(getattr(country, attribute, ""))
            if value:
                dest.add(value)
                if "," in value:
                    dest.add(value.split(",", 1)[0].strip())
    return frozenset(europe), frozenset(other)


@lru_cache(maxsize=4096)
def classify_location(location: str) -> str:
    """Return europe, outside, mixed or unknown for a free-text LOCATION only."""
    raw = str(location or "")
    text = normalize(raw)
    if not text:
        return "unknown"
    europe_countries, other_countries = country_phrases()
    eu_country = has_phrase(text, europe_countries)
    other_country = has_phrase(text, other_countries)
    eu_city = has_phrase(text, EUROPE_CITIES)
    other_city = has_phrase(text, OUTSIDE_CITIES)

    # The ATS datasets frequently use lower-case ISO suffixes like
    # "Ho Chi Minh City, vn" or "Rayong, th". The old parser recognized ONLY
    # uppercase suffixes; this caused non-European jobs to be marked unknown
    # and retained. Accept upper/lower/mixed case for ISO-2 and ISO-3 codes.
    #
    # Only treat an abbreviation as a code if it appears AFTER a location
    # delimiter (comma, slash, semicolon, parenthesis, or spaced hyphen).
    # That avoids reading normal words like "in" as India or "it" as Italy.
    region_codes = {
        token.upper() for token in re.findall(
            r"(?:[,(/;|\[]|\s+-\s+)\s*([a-z]{2,3})\b", raw, flags=re.I
        )
    }
    # Also accept locations consisting solely of an ISO code (e.g. "VN").
    if re.fullmatch(r"[a-z]{2,3}", raw.strip(), flags=re.I):
        region_codes.add(raw.strip().upper())

    alpha2 = {code for code in region_codes if len(code) == 2}
    alpha3 = {code for code in region_codes if len(code) == 3}
    north_american_region = bool((alpha2 & NORTH_AMERICAN_REGION_CODES) - AMBIGUOUS_REGION_CODES)
    if alpha2 & NORTH_AMERICAN_REGION_CODES and other_city:
        north_american_region = True
    if north_american_region:
        other_country = True

    # Country code alone is more authoritative than a city name, which may
    # be shared by multiple countries (e.g. Paris, Texas; London, Ontario).
    import pycountry
    for code in alpha2:
        if code in EUROPE_ALPHA2 and not (north_american_region and not eu_country):
            eu_country = True
        elif code not in EUROPE_ALPHA2 and code not in UNCERTAIN_BORDER_COUNTRIES:
            if pycountry.countries.get(alpha_2=code):
                other_country = True
    for code in alpha3:
        country = pycountry.countries.get(alpha_3=code)
        if country:
            country_code = country.alpha_2
            if country_code in EUROPE_ALPHA2:
                if not (north_american_region and not eu_country):
                    eu_country = True
            elif country_code not in UNCERTAIN_BORDER_COUNTRIES:
                other_country = True
    has_europe = eu_country or eu_city
    has_outside = other_country or other_city
    if has_europe and has_outside:
        # Explicit non-Europe country/state should override an identical city
        # name in Europe unless a European country is ALSO explicitly listed.
        if not eu_country and (other_country or north_american_region):
            return "outside"
        return "mixed"
    if has_outside:
        return "outside"
    if has_europe:
        return "europe"
    return "unknown"


SUMMER_TERM = r"(?:summer|sommer|ete|estival|estivo|verano)"
INTERNSHIP_TERM = r"(?:intern(?:ship)?|stage|stagiaire|placement|traineeship|co[ -]?op|pfe|thesis)"
MONTH = r"(?:june|july|august|jun|jul|aug|juin|juillet|aout|juni|juli|agosto|junio|julio)"


def excluded_summer(job: dict, config: dict) -> bool:
    settings = config.get("season_filter", {})
    title = normalize(job.get("title", ""))
    kind = normalize(job.get("kind_hint", ""))
    desc = normalize(job.get("description", ""))
    if settings.get("exclude_summer_internships", True):
        seasonal_title = re.search(r"\b" + SUMMER_TERM + r"\b", title)
        internship_title = re.search(r"\b" + INTERNSHIP_TERM + r"\b", title + " " + kind)
        if seasonal_title and internship_title:
            return True
        # Explicit 'summer internship program' in the main role description.
        if re.search(r"\b" + SUMMER_TERM + r"\b.{0,30}\b" + INTERNSHIP_TERM + r"\b", desc[:950]):
            return True
        if re.search(r"\b" + INTERNSHIP_TERM + r"\b.{0,20}\b" + SUMMER_TERM + r"\b", title):
            return True
    years = settings.get("excluded_summer_years", [2027])
    for year in years:
        year = str(year)
        seasonal_year = (r"\b" + SUMMER_TERM + r"\s*(?:of\s+|in\s+)?" + year + r"\b|"
                         r"\b" + year + r"\s*" + SUMMER_TERM + r"\b")
        if re.search(seasonal_year, title + " " + desc[:2500]):
            return True
        date_expression = (
            r"(?:\b" + MONTH + r"\b(?:\s+[0-3]?\d\s*,?)?\s*" + year + r"\b|"
            r"\b" + year + r"[-/.]0?[678](?:[-/.][0-3]?\d)?\b|"
            r"\b(?:[0-3]?\d[-/.])?0?[678][-/.]" + year + r"\b)"
        )
        # A dated title such as 'Mechanical Intern - July 2027'.
        if re.search(date_expression, title):
            return True
        start_expression = (
            r"(?:\b(?:start(?:ing|s)?|begin(?:ning)?|commenc(?:e|ing)|debut|"
            r"from|a partir de|start date|date de debut|prise de poste)\b)"
            r".{0,48}" + date_expression
        )
        if re.search(start_expression, desc[:4500]):
            return True
    return False


def geography_excluded(job: dict, config: dict) -> bool:
    options = config.get("geography_filter", {})
    if not options.get("enabled", True):
        return False
    status = classify_location(job.get("location", ""))
    return status == "outside" or (status == "unknown" and not options.get("keep_unknown_locations", True)) or (
        status == "mixed" and not options.get("keep_mixed_locations", True))
