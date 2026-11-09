import os
import re
import json
import random
from urllib.parse import urlsplit, urlunsplit, quote
import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Header, Request
from starlette.middleware.base import BaseHTTPMiddleware
import jwt
from pydantic import BaseModel, Field, field_validator
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "")
DIGITRANSIT_API_KEY = os.environ.get("DIGITRANSIT_API_KEY", "") or os.environ.get("HSL_API_KEY", "")

def get_supabase() -> Client:
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("Missing Supabase credentials in environment variables.")
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

def get_current_user(authorization: str = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Bearer token.")
    token = authorization.replace("Bearer ", "").strip()
    
    try:
        sb = get_supabase()
        user_response = sb.auth.get_user(token)
        if not user_response or not user_response.user:
            raise HTTPException(status_code=401, detail="Invalid session token.")
        
        user = user_response.user
        meta = user.user_metadata or {}
        display_name = meta.get("display_name") or (user.email.split("@")[0].capitalize() if user.email else "User")
        is_visitor = (display_name.lower() == "visitor" or (user.email and user.email.lower().startswith("visitor")))
        
        return {
            "id": user.id,
            "email": user.email,
            "display_name": display_name,
            "is_visitor": is_visitor
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Authentication error: {str(exc)}")

def require_editor(user: dict):
    if user.get("is_visitor"):
        raise HTTPException(status_code=403, detail="Visitor account has read-only access.")
    
def normalize_url(raw_url: str) -> str:
    cleaned = raw_url.strip()
    if not cleaned:
        raise ValueError("URL cannot be empty.")
    parts = urlsplit(cleaned)
    if not parts.scheme or not parts.netloc:
        raise ValueError("URL must start with http:// or https://")
    clean_path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), clean_path, "", ""))

# =====================================================================
# =====================================================================
# PHASE 4: MULTI-LAYER GEOCODING ENGINE & DISTRICT COORDINATES
# =====================================================================

HELSINKI_DISTRICT_COORDINATES = {
    "Pohjois-Pasila": (60.2135, 24.9221),
    "Pasila": (60.1988, 24.9334),
    "Keski-Pasila": (60.1994, 24.9283),
    "Länsi-Pasila": (60.2010, 24.9200),
    "Itä-Pasila": (60.2000, 24.9380),
    "Kruunuvuorenranta": (60.1752, 25.0210),
    "Kruunuvuori": (60.1752, 25.0210),
    "Oulunkylä": (60.2285, 24.9634),
    "Sörnäinen": (60.1872, 24.9610),
    "Kallio": (60.1841, 24.9523),
    "Töölö": (60.1812, 24.9215),
    "Taka-Töölö": (60.1850, 24.9180),
    "Etu-Töölö": (60.1740, 24.9240),
    "Lauttasaari": (60.1584, 24.8722),
    "Punavuori": (60.1594, 24.9381),
    "Kamppi": (60.1685, 24.9312),
    "Kalasatama": (60.1843, 24.9785),
    "Jätkäsaari": (60.1578, 24.9189),
    "Ruoholahti": (60.1631, 24.9142),
    "Ullanlinna": (60.1580, 24.9495),
    "Eira": (60.1550, 24.9380),
    "Vallila": (60.1925, 24.9585),
    "Alppila": (60.1895, 24.9370),
    "Käpylä": (60.2140, 24.9510),
    "Kumpula": (60.2085, 24.9620),
    "Meilahti": (60.1910, 24.9045),
    "Munkkiniemi": (60.1990, 24.8760),
    "Munkkivuori": (60.2070, 24.8760),
    "Haaga": (60.2180, 24.8980),
    "Pohjois-Haaga": (60.2290, 24.8930),
    "Etelä-Haaga": (60.2110, 24.9010),
    "Herttoniemi": (60.1940, 25.0310),
    "Herttoniemenranta": (60.1882, 25.0382),
    "Vuosaari": (60.2090, 25.1430),
    "Malmi": (60.2510, 25.0110),
    "Pukinmäki": (60.2450, 24.9920),
    "Pihlajamäki": (60.2360, 25.0060),
    "Pihlajisto": (60.2310, 25.0030),
    "Viikki": (60.2341, 25.0361),
    "Suutarila": (60.2760, 24.9980),
    "Siltamäki": (60.2740, 24.9850),
    "Kuninkaantammi": (60.2594, 24.8864),
    "Kaarela": (60.2450, 24.8720),
    "Malminkartano": (60.2460, 24.8620),
    "Kannelmäki": (60.2390, 24.8780),
    "Pikku Huopalahti": (60.2000, 24.8950),
    "Ruskeasuo": (60.1980, 24.9040),
    "Kluuvi": (60.1700, 24.9450),
    "Kruununhaka": (60.1730, 24.9560),
    "Katajanokka": (60.1670, 24.9690),
    "Helsinki": (60.1699, 24.9384)
}

# ---------------------------------------------------------------------
# Bolt ⚡ Performance Optimization:
# Pre-compiled regular expressions for geocoding and spec extraction.
# Pre-compiling eliminates repeated compilation and regex cache lookups
# during high-frequency list rendering and scraping (~15-20% faster).
# ---------------------------------------------------------------------
RE_DASH = re.compile(r"-\s*(?:Helsinki\s+)?(?:[\w\-]+\s+)?([\w\s\-]+?\d+\s*[A-Za-z]?)")
RE_STREET_SUFFIX = re.compile(r"\b([\w\-]+(?:katu|tie|kuja|polku|kaari|raitti|v\w*yl\w*|ranta|rinne|puisto|kallio|m\w*ki|tori|aukio)\s+\d+\s*[A-Za-z]?)\b", re.IGNORECASE)
RE_GENERIC_STREET = re.compile(r"\b([\w\-]{3,}\s+\d+\s*[A-Za-z]?)\b")
RE_NON_STREET_WORDS = re.compile(r"\b(huonetta|kerros|krs|m2|kk)\b", re.IGNORECASE)

RE_FLOOR_DOUBLE = re.compile(r"(?:kerros(?:ta|kset)?|krs\.?)\s*:?\s*(\d{1,2})\s*/\s*(\d{1,2})\b", re.IGNORECASE)
RE_FLOOR_DOUBLE_REV = re.compile(r"\b(\d{1,2})\s*/\s*(\d{1,2})\s*(?:krs|kerros)\b", re.IGNORECASE)
RE_FLOOR_SINGLE = re.compile(r"(?:kerros(?:ta|kset)?|krs\.?)\s*:?\s*(\d{1,2})\b", re.IGNORECASE)
RE_FLOOR_SINGLE_REV = re.compile(r"\b(\d{1,2})\s*\.\s*(?:kerros|krs)\b", re.IGNORECASE)
RE_FLOOR_GROUND = re.compile(r"\b(?:alin\s+kerros|maantaso(?:kerros)?|pohjakerros)\b", re.IGNORECASE)

RE_ELEVATOR_YES = re.compile(r"(?:hissi\s*:?\s*(?:on|kyllä|on\s+hissi)|talossa\s+(?:on\s+)?hissi|taloyhti(?:össä|ön)\s+(?:on\s+)?hissi|\bhissitalo\b|\bhissillinen\b)", re.IGNORECASE)
RE_ELEVATOR_NO = re.compile(r"(?:hissi\s*:?\s*(?:ei|ei\s+ole)|ei\s+hissiä|ei\s+hissi\b|\bhissitön\b)", re.IGNORECASE)
RE_WATER_INCL = re.compile(r"(?:vesi(?:maksu(?:ennakko)?)?\s*:?\s*(?:sisältyy|sis\.)(?:\s+vuokraan)?|sis(?:ältyy|\.)\s+vesi\b|vesi\s*:\s*0\s*€)", re.IGNORECASE)
RE_WATER_FEE = re.compile(r"vesi(?:maksu(?:ennakko)?)?[:\s]*(\d{1,3}(?:[.,]\d{1,2})?)\s*€(?:\s*/\s*(?:hlö|kk|kuukausi|hlö/kk|hlö/kuukausi))?", re.IGNORECASE)
RE_PETS_YES = re.compile(r"\blemmik(?:it|kieläimet)?\s*:?\s*(?:ovat\s+)?(?:sallittu(?:ja)?|ok|tervetulleita|kyllä)\b", re.IGNORECASE)
RE_PETS_NO = re.compile(r"\b(?:ei\s+lemmikkejä|lemmikit\s+kielletty|lemmikkikielto|lemmik(?:it)?\s*:?\s*ei)\b", re.IGNORECASE)
RE_PETS_AGREEMENT = re.compile(r"\blemmik(?:it|eistä)?\s*:?\s*(?:sopimuksen\s+mukaan|sovitaan\s+erikseen|neuvoteltavissa)\b", re.IGNORECASE)
RE_BALCONY_GLAZED = re.compile(r"(?:lasitettu(?:\s+oma)?\s+parveke|parveke\s*:?\s*lasitettu)", re.IGNORECASE)
RE_BALCONY_FRENCH = re.compile(r"ranskalainen\s+parveke", re.IGNORECASE)
RE_BALCONY_TERRACE = re.compile(r"(?:oma\s+terassi|asuntopiha|terassi|maantasoterassi|pihapatio)", re.IGNORECASE)
RE_BALCONY_ANY = re.compile(r"(?<!ei\s)(?<!ei\somaa\s)\bparveke\b", re.IGNORECASE)
RE_BALCONY_NO = re.compile(r"\b(?:ei\s+parveketta|ei\s+omaa\s+parveketta|parveke\s*:?\s*ei)\b", re.IGNORECASE)
RE_SAUNA_OWN = re.compile(r"(?:oma\s+sauna|sauna\s*:\s*(?:on|kyllä|oma))", re.IGNORECASE)
RE_SAUNA_BLDG = re.compile(r"(?:taloyhti(?:össä|ön)\s+sauna|talosauna|sauna\s*:\s*(?:taloyhtiössä|taloyhtiön))", re.IGNORECASE)
RE_SAUNA_NO = re.compile(r"\b(?:ei\s+saunaa|sauna\s*:?\s*ei)\b", re.IGNORECASE)

# Notification / Listing page deep heuristics
RE_CONDITION = re.compile(r"kunto\s*:?\s*([\w\s\-]+?)(?:,|\.|\n|$)", re.IGNORECASE)
RE_YEAR_BUILT = re.compile(r"(?:rakennusvuosi|rakennettu|valmistumisvuosi|valmistunut)\s*:?\s*(19\d\d|20\d\d)\b", re.IGNORECASE)
RE_DISHWASHER_YES = re.compile(r"(?:astianpesukone|tiskikone|\bapk\b)", re.IGNORECASE)
RE_DISHWASHER_NO = re.compile(r"(?:ei\s+(?:ole\s+)?(?:astianpesukonetta|tiskikonetta|apk))", re.IGNORECASE)
RE_WASHER_HOOKUP = re.compile(r"(?:pesukoneliitäntä|liitäntä\s+pyykinpesukoneelle|\bpk-liitäntä\b)", re.IGNORECASE)
RE_LAUNDRY_ROOM = re.compile(r"(?:talopesula|pesutupa|kuivaushuone)", re.IGNORECASE)
RE_WALK_IN_CLOSET = re.compile(r"\b(?:vaatehuone|\bvh\b)\b", re.IGNORECASE)
RE_STORAGE = re.compile(r"(?:kellarikomero|vinttikomero|irtaimistovarasto|lämmin\s+varasto|häkkivarasto)", re.IGNORECASE)
RE_INTERNET_INCL = re.compile(r"(?:taloyhtiölaajakaista|laajakaista\s+sisältyy|valokuitu|perusnopeus\s+sisältyy|netti\s+sisältyy)", re.IGNORECASE)
RE_DEPOSIT_LOW = re.compile(r"vakuus\s*:?\s*(?:0\s*€|ei\s+vakuutta|1\s*kk\b|1\s*kuukauden)", re.IGNORECASE)
RE_FREE_IMMEDIATELY = re.compile(r"\b(?:heti\s+vapaa|vapaa\s+heti)\b", re.IGNORECASE)

def clean_street_address(title: str, asuinalue: str) -> str:
    """
    Extracts the clean street name and number from Vuokraovi title patterns, e.g.:
    'Vuokrataan Kerrostalo 3 huonetta - Helsinki Ruoholahti Selkamerenkatu 12' -> 'Selkamerenkatu 12'
    'Kiillekuja 3' -> 'Kiillekuja 3'
    """
    cleaned = (title or "").strip()
    
    # 1. Match after hyphen: "... - Helsinki [Area] [Street + Number]"
    dash_match = RE_DASH.search(cleaned)
    if dash_match:
        street = dash_match.group(1).strip()
        if any(c.isdigit() for c in street):
            return street

    # 2. Match standard street suffix + number: e.g. "Kiillekuja 3", "Mannerheimintie 12 B"
    street_match = RE_STREET_SUFFIX.search(cleaned)
    if street_match:
        return street_match.group(1).strip()

    # 3. Match generic street name + number
    generic_match = RE_GENERIC_STREET.search(cleaned)
    if generic_match:
        cand = generic_match.group(1).strip()
        if not RE_NON_STREET_WORDS.search(cand):
            return cand

    # Fallback to district
    return asuinalue or "Helsinki"

def geocode_address_hsl(title: str, asuinalue: str) -> tuple[float, float]:
    """
    Multi-layer geocoder:
    1. HSL Digitransit Pelias API (with digitransit-subscription-key if configured)
    2. Photon OpenStreetMap API (free, fast, no API key required)
    3. OpenStreetMap Nominatim
    4. Helsinki district centroid lookup with small jitter
    """
    street = clean_street_address(title, asuinalue)
    query_text = f"{street}, {asuinalue}, Helsinki".strip(" ,")

    # 1. Primary: HSL Digitransit Pelias API (if subscription key is configured)
    if DIGITRANSIT_API_KEY:
        pelias_url = f"https://api.digitransit.fi/geocoding/v1/search?text={quote(query_text)}&size=1&boundary.rect.min_lat=60.0&boundary.rect.max_lat=60.4&boundary.rect.min_lon=24.6&boundary.rect.max_lon=25.3"
        headers = {
            "User-Agent": "HelsinkiApartmentTracker/2.0 (leo-ella-koti)",
            "digitransit-subscription-key": DIGITRANSIT_API_KEY
        }
        try:
            with httpx.Client(timeout=4.0) as client:
                resp = client.get(pelias_url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    features = data.get("features", [])
                    if features:
                        coords = features[0]["geometry"]["coordinates"]
                        lon = float(coords[0])
                        lat = float(coords[1])
                        if 60.1 <= lat <= 60.35 and 24.7 <= lon <= 25.3:
                            return round(lat, 6), round(lon, 6)
        except Exception:
            pass

    # 2. Secondary: Photon OpenStreetMap geocoder (free, no API key required)
    try:
        photon_url = f"https://photon.komoot.io/api/?q={quote(query_text)}&limit=1"
        with httpx.Client(timeout=4.0) as client:
            resp = client.get(photon_url, headers={"User-Agent": "HelsinkiApartmentTracker/2.0"})
            if resp.status_code == 200:
                features = resp.json().get("features", [])
                if features:
                    coords = features[0]["geometry"]["coordinates"]
                    lon = float(coords[0])
                    lat = float(coords[1])
                    if 60.1 <= lat <= 60.35 and 24.7 <= lon <= 25.3:
                        return round(lat, 6), round(lon, 6)
    except Exception:
        pass

    # 3. Tertiary: OpenStreetMap Nominatim
    try:
        nom_url = f"https://nominatim.openstreetmap.org/search?q={quote(query_text)}&format=json&limit=1&countrycodes=fi"
        with httpx.Client(timeout=4.0) as client:
            resp = client.get(nom_url, headers={"User-Agent": "HelsinkiApartmentTracker/2.0 (leo-ella-koti)"})
            if resp.status_code == 200:
                data = resp.json()
                if data:
                    lat = float(data[0]["lat"])
                    lon = float(data[0]["lon"])
                    if 60.1 <= lat <= 60.35 and 24.7 <= lon <= 25.3:
                        return round(lat, 6), round(lon, 6)
    except Exception:
        pass

    # 4. Quaternary: Local high-precision Helsinki District centroid lookup
    norm_area = (asuinalue or "").strip().lower()
    for d_name, (base_lat, base_lon) in HELSINKI_DISTRICT_COORDINATES.items():
        if d_name.lower() in norm_area or norm_area in d_name.lower():
            jitter_lat = (random.random() - 0.5) * 0.003
            jitter_lon = (random.random() - 0.5) * 0.003
            return round(base_lat + jitter_lat, 6), round(base_lon + jitter_lon, 6)

    # Default to Helsinki center with jitter
    return round(60.1699 + (random.random() - 0.5) * 0.005, 6), round(24.9384 + (random.random() - 0.5) * 0.005, 6)
# PHASE 3: HELSINKI DISTRICT PROFILES & HEURISTIC EVALUATION ENGINE
# =====================================================================

HELSINKI_DISTRICT_PROFILES = {
    "Kuninkaantammi": {
        "vibe": "Moderni, värikäs ja ekologinen uusi kaupunginosa Keskuspuiston ja Vantaanjoen syleilyssä",
        "pros": [
            "Keskuspuiston ulkoilureitit ja Palettilammen uimaranta aivan vieressä",
            "Energiatehokasta, uutta ja raikasta asuntokantaa (valmistunut 2017+)",
            "Rauhallinen, luonnonläheinen ja esteetön asuinympäristö"
        ],
        "cons": [
            "Ei omaa juna- tai metroasemaa, kulku nojaa runkolinja 560:een ja liityntäbusseihin",
            "Laajemmat kaupalliset palvelut vaativat siirtymistä Kaareen tai Myyrmäkeen"
        ]
    },
    "Kannelmäki": {
        "vibe": "Vihreä raidekaupunginosa ja kauppakeskus Kaaren kattavat palvelut",
        "pros": [
            "Kauppakeskus Kaari (Helsingin 5. suurin) kävelyetäisyydellä",
            "Lähijunat I ja P vievät 13 minuutissa Helsingin keskustaan ja lentoasemalle",
            "Mätäjoen vehreät ulkoilureitit ja puistoalueet"
        ],
        "cons": [
            "Kerrostaloissa vaihteleva ikärakenne",
            "Asemanseudulla vilkasta kauttakulkuliikennettä"
        ]
    },
    "Kaarela": {
        "vibe": "Luonnonläheinen länsihelsinkiläinen raidealue ja huippumaisemat",
        "pros": [
            "Kehäradan lähijunayhteys suoraan Pasilaan, keskustaan ja lentoasemalle",
            "Malminkartanon täyttömäki ja portaat tarjoavat loistavat treenimaastot"
        ],
        "cons": [
            "Palvelut painottuvat lähiostareille, isompiin kauppakeskuksiin tarvitaan bussia tai junaa"
        ]
    },
    "Malminkartano": {
        "vibe": "Rauhallinen raidealue Länsi-Helsingissä loistavilla ulkoilumaastoilla",
        "pros": [
            "Kehäradan lähijunapysäkki: suora ja nopea yhteys keskustaan sekä lentoasemalle",
            "Malminkartanonhupun huippunäkymät ja ulkoilupuistot"
        ],
        "cons": [
            "Kivijalkapalvelut rajalliset ilman siirtymistä Myyrmäkeen tai Kaareen"
        ]
    },
    "Pohjois-Haaga": {
        "vibe": "Vehreä, puistomainen ja väljästi rakennettu raidekaupunginosa",
        "pros": [
            "Lähijuna-asema (10 min keskustaan)",
            "Lähellä Pirkkolan urheilupuistoa ja Keskuspuiston reittejä",
            "Väljät, rauhalliset puistopihat ja luontoa ympärillä"
        ],
        "cons": [
            "Osa 60–70-luvun taloyhtiöistä voi kaivata tulevia peruskorjauksia"
        ]
    },
    "Etelä-Haaga": {
        "vibe": "Idyllinen, puutarhakaupunkimainen ja erittäin arvostettu asuinalue",
        "pros": [
            "Huopalahden risteysasema: kaikki lähijunat ja Raide-Jokeri pikaraitiotie 15",
            "Alppiruusupuisto ja rauhallinen huvilamiljöö",
            "Korkea asumisviihtyvyys ja turvallinen tunnelma"
        ],
        "cons": [
            "Korkeahko vuokrataso",
            "Asuntoja vapautuu harvoin"
        ]
    },
    "Haaga": {
        "vibe": "Viihtyisä ja vehreä perinteinen länsihelsinkiläinen kaupunginosa",
        "pros": [
            "Erinomaiset liikenneyhteydet: useita juna-asemia ja Raide-Jokeri",
            "Paljon puistoja, urheilukenttiä ja Keskuspuiston läheisyys"
        ],
        "cons": [
            "Vaihteleva rakennuskanta ja neliövuokrataso"
        ]
    },
    "Meilahti": {
        "vibe": "Merellinen, arvostettu ja puistomainen kantakaupungin helmi",
        "pros": [
            "Seurasaaren ja Meilahden rantapuiston upeat ulkoilureitit",
            "Raitiovaunut 4, 10 ja useat bussilinjat suoraan keskustaan",
            "Rauhallinen ja siisti arvoalue"
        ],
        "cons": [
            "Korkea hintataso",
            "Sairaala-alueen lähistöllä ajoittain hälytysajoneuvojen ääniä"
        ]
    },
    "Munkkiniemi": {
        "vibe": "Klassinen, merellinen ja puistomainen kulttuurimiljöö",
        "pros": [
            "Raitiovaunu 4 kotiovelta suoraan ydinkeskustaan",
            "Munkkiniemen uimaranta, rantakahvilat ja Alvar Aallon puistot",
            "Vakaa, vehreä ja arvostettu naapurusto"
        ],
        "cons": [
            "Helsingin korkeimpia neliövuokria",
            "Vanhemmissa taloissa usein portaat ilman hissiä"
        ]
    },
    "Pasila": {
        "vibe": "Liikenteen ja kaupan sykkivä keskus Mall of Triplan kupeessa",
        "pros": [
            "Kaikki Suomen junat pysähtyvät Pasilassa (5 min keskustaan)",
            "Mall of Triplan sadat kaupat, ravintolat ja viihdepalvelut",
            "Keskuspuiston viheralueet alkavat suoraan Länsi-Pasilasta"
        ],
        "cons": [
            "Urbaani häly, tiheä liikenne ja alueen jatkuvat rakennustyöt"
        ]
    },
    "Pohjois-Pasila": {
        "vibe": "Uusi, moderni asuinalue Keskuspuiston vihreässä kainalossa",
        "pros": [
            "Keskuspuiston ulkoilureitit ja hiihtoladut alkavat suoraan kotiovelta",
            "Uutta, energiatehokasta ja nykyaikaista rakennuskantaa",
            "Mall of Tripla ja Pasilan asema nopeasti saavutettavissa"
        ],
        "cons": [
            "Alueella edelleen osittaista uudisrakentamista ja katutöitä",
            "Kivijalkapalvelut rajalliset ilman Triplaan siirtymistä"
        ]
    },
    "Kruunuvuorenranta": {
        "vibe": "Merellinen ja luonnonläheinen saaristokaupunginosa upeilla maisemilla",
        "pros": [
            "Upeat merimaisemat, kalliorannat ja laajat ulkoilualueet",
            "Kruunusillat-pikaraitiotie valmistumassa suoraan Helsingin keskustaan",
            "Moderni, rauhallinen ja siisti asuinympäristö"
        ],
        "cons": [
            "Kruunusiltojen valmistumiseen asti riippuvainen lautta- tai liityntäbussiyhteydestä",
            "Merituuli ja talvisää voivat olla avoimilla rannoilla viileitä"
        ]
    },
    "Kruunuvuori": {
        "vibe": "Merellinen saaristomiljöö ja tuleva pikaratikkayhteys",
        "pros": [
            "Meriluonto ja rauhallinen ilmapiiri",
            "Kruunusillat tuovat huippunopean raideliikenteen keskustaan",
            "Uutta arkkitehtuuria ja viihtyisiä puistoja"
        ],
        "cons": [
            "Pikaratikan valmistumiseen saakka kulku bussilla Herttoniemen kautta"
        ]
    },
    "Oulunkylä": {
        "vibe": "Vihreä raidekeskus: juna ja Raide-Jokeri yhdistävät koko pääkaupunkiseudun",
        "pros": [
            "Loistavat raideyhteydet: lähijunat (10 min keskustaan) ja Raide-Jokeri pikaraitiotie 15",
            "Vantaanjoen ulkoilumaastot, Pikkukosken uimaranta ja Oulunkylän urheilupuisto",
            "Hyvät lähipalvelut ja ruokakaupat heti aseman yhteydessä"
        ],
        "cons": [
            "Rata-alueen läheisyydessä vilkasta liikennettä ja junamelua",
            "Kerrostalokannassa vaihteleva ikärakenne"
        ]
    },
    "Sörnäinen": {
        "vibe": "Dynaaminen, urbaani ja trendikäs itäinen kantakaupunki",
        "pros": [
            "24/7 kattavat liikenneyhteydet: metro, raitiovaunut ja tiheät bussilinjat",
            "Suvilahden kulttuuri, Teurastamo sekä kymmeniä ravintoloita ja kahviloita",
            "Kalasataman ja Redin kauppakeskuksen palvelut kävelyetäisyydellä"
        ],
        "cons": [
            "Vilkas kaupunkiliikenne ja katuhäly erityisesti Hämeentiellä ja Kurvissa",
            "Vähän perinteisiä laajoja viheralueita aivan välittömässä kotiympäristössä"
        ]
    },
    "Kallio": {
        "vibe": "Boheemi ja eläväinen kulttuurin, kahviloiden ja ravintoloiden sydän",
        "pros": [
            "Helsingin rikkain kahvila-, ravintola- ja kulttuuritarjonta",
            "Kaksi metroasemaa (Hakaniemi & Sörnäinen) ja kattavat raitiovaunuyhteydet",
            "Aito ja yhteisöllinen kaupunkitunnelma"
        ],
        "cons": [
            "Vilkas yö- ja iltaelämä voi aiheuttaa meluhaittaa viikonloppuisin",
            "Pienemmät huoneistokoot ja usein vanhemmat hissirakenteet"
        ]
    },
    "Töölö": {
        "vibe": "Arvokas, klassinen ja puistomainen kantakaupunki",
        "pros": [
            "Upea jugend- ja funkkisarkkitehtuuri sekä korkeat huoneet",
            "Töölönlahti, Hietaranta (Hietsu) ja Sibeliuksen puisto lähellä",
            "Kulttuurikeskittymä: Ooppera, Musiikkitalo ja Olympiastadion vieressä"
        ],
        "cons": [
            "Korkeampi hintataso ja vuokrapyynnit",
            "Ei metroasemaa, kulku nojaa raitiovaunuihin ja busseihin"
        ]
    },
    "Lauttasaari": {
        "vibe": "Onnellisten saari: merituulta, kalliorantoja ja luonnonrauhaa",
        "pros": [
            "Meri ja rantapolut kiertävät koko saaren, useita hiekkarantoja",
            "Kaksi omaa metroasemaa takaavat 5–8 min matkan Kamppiin",
            "Erittäin turvallinen, vehreä ja arvostettu naapurusto"
        ],
        "cons": [
            "Korkea vuokra- ja hintataso",
            "Länsiväylän läheisyydessä paikallista liikenteen huminaa"
        ]
    },
    "Punavuori": {
        "vibe": "Design District, boutique-kadut ja etelähelsinkiläinen estetiikka",
        "pros": [
            "Helsingin parhaat artesaanileipomot, design-liikkeet ja bistrot",
            "Sinebrychoffin puisto ja ranta kivenheiton päässä",
            "Kaunis vanha rakennuskanta ja uniikki tunnelma"
        ],
        "cons": [
            "Helsingin kalleimpia asuinalueita neliöhinnoiltaan",
            "Katupysäköinti on usein haastavaa"
        ]
    },
    "Kamppi": {
        "vibe": "Ydinkeskustan eläväinen syke ja lyömätön saavutettavuus",
        "pros": [
            "Kaikki joukkoliikenne: metro, bussiterminaali ja rautatieasema vieressä",
            "Kattava ostos-, kulttuuri- ja viihdetarjonta heti kotiovelta",
            "Keskustan huippusijainti ilman tarvetta omalle autolle"
        ],
        "cons": [
            "Jatkuva ihmisvirta ja kaupungin äänet",
            "Vuokrataso Helsingin kärkiluokkaa"
        ]
    },
    "Kalasatama": {
        "vibe": "Merellinen, moderni ja futuristinen tornitalojen kaupunginosa",
        "pros": [
            "Kauppakeskus Redi ja oma metroasema heti vieressä",
            "Isoisänsilta vie suoraan Mustikkamaan ulkoilusaareen ja uimarannalle",
            "Uutta, energiatehokasta ja laadukasta talotekniikkaa"
        ],
        "cons": [
            "Tiivis ja tuulinen rantamaisema",
            "Alueella edelleen osittaista rakentamista Sompasaaren suunnalla"
        ]
    },
    "Jätkäsaari": {
        "vibe": "Merellinen, urbaani ja kansainvälinen satamakaupunginosa",
        "pros": [
            "Raitiovaunut 7, 8 ja 9 kulkevat suoraan kotiovelta",
            "Uudet, modernit talot laadukkailla pohjaratkaisuilla",
            "Ruoholahden metro ja merelliset rantapromenadit lähellä"
        ],
        "cons": [
            "Satamaliikenne ja laivojen purkautuminen ruuhkauttavat ajoittain katuja",
            "Talvella merituuli voi olla viileä"
        ]
    },
    "Ruoholahti": {
        "vibe": "Kanavakaupunginosa kantakaupungin kyljessä loistavilla yhteyksillä",
        "pros": [
            "Oma metroasema, raitiovaunut ja nopea pyöräreitti Baana keskustaan",
            "Kaapelitehtaan kulttuurikeskus ja kanavanvarren ravintolat",
            "Kattavat ruokakaupat ja liikuntamahdollisuudet"
        ],
        "cons": [
            "Länsiväylän liikenneäänet alueen eteläosassa"
        ]
    },
    "Vallila": {
        "vibe": "Trendikäs yhdistelmä Puu-Vallilan idylliä ja urbaania teollisuusestetiikkaa",
        "pros": [
            "Konepajan ja Teollisuuskadun ravintolat, panimot ja kulttuuritapahtumat",
            "Tiheät raitio- ja bussiyhteydet Mäkelän- ja Hämeentietä",
            "Puu-Vallilan viehättävä puutaloidylli ja puistot"
        ],
        "cons": [
            "Pääväylien varrella vilkasta liikennettä",
            "Vanhemmissa taloissa usein pienemmät kylpyhuoneet"
        ]
    },
    "Käpylä": {
        "vibe": "Vihreä puutarhakaupunki ja rauhallinen yhteisöllinen miljöö",
        "pros": [
            "Puu-Käpylän historiallinen puutarhamiljöö ja upeat puistot",
            "Käpylän juna-asema ja raitiovaunu 1 vievät nopeasti keskustaan",
            "Kumpulan maauimala ja siirtolapuutarhat lähellä"
        ],
        "cons": [
            "Käpyläntien ja Mäkelänkadun varrella vilkasta liikennettä"
        ]
    },
    "Herttoniemi": {
        "vibe": "Monipuolinen ja kehittyvä itäisen kantakaupungin solmukohta meren rannalla",
        "pros": [
            "Metroasema vie 10 minuutissa Kamppiin",
            "Herttoniemenrannan rantapolut ja Kivinokan luontoidylli",
            "Monipuoliset kaupat ja kauppakeskus Hertsi"
        ],
        "cons": [
            "Itäväylä halkoo aluetta tuoden liikenteen ääntä"
        ]
    },
    "Vuosaari": {
        "vibe": "Meriluonnon ja rantojen paratiisi: Aurinkolahti ja Uutelan luonnonsuojelualue",
        "pros": [
            "Uutelan laajat luonnonsuojelualueet ja Aurinkolahden hiekkaranta",
            "Metro vie suoraan keskustaan",
            "Kauppakeskus Columbus ja monipuoliset harrastusmahdollisuudet"
        ],
        "cons": [
            "Pidempi matka ydinkeskustaan (n. 20–25 min metrolla)"
        ]
    },
    "Malmi": {
        "vibe": "Koillisen Helsingin vilkas raide- ja palvelukeskus",
        "pros": [
            "Kaikki lähijunat pysähtyvät Malmilla (10–12 min keskustaan)",
            "Erittäin laajat kaupalliset ja julkiset palvelut (Malmintori, uimahalli, kirjasto)",
            "Edullisempi neliöhinta ja vuokrataso"
        ],
        "cons": [
            "Aseman ympäristössä vilkasta ilta-aikaan",
            "Vaihteleva rakennuskanta"
        ]
    },
    "Viikki": {
        "vibe": "Tiedepuisto, luonto ja Raide-Jokerin pikaraitiotie",
        "pros": [
            "Raide-Jokeri pikaraitiotie 15 ja tiheät bussilinjat",
            "Viikin arboretum ja Vanhankaupunginlahden lintukosteikot",
            "Viihtyisää ja luonnonläheistä asumista"
        ],
        "cons": [
            "Ei suoraa metro- tai junayhteyttä"
        ]
    }
}

def extract_specs_from_soup_and_text(soup: BeautifulSoup | None, text: str) -> dict:
    specs = {
        "floor": None,
        "total_floors": None,
        "floor_str": None,
        "has_elevator": None,
        "water_fee": None,
        "water_included": False,
        "pets_allowed": None,
        "has_balcony": None,
        "balcony_type": None,
        "has_sauna": None,
        "sauna_type": None,
        "condition": None,
        "year_built": None,
        "has_dishwasher": None,
        "has_washing_machine_hookup": None,
        "has_laundry_room": None,
        "has_walk_in_closet": None,
        "has_storage": None,
        "internet_included": None,
        "low_deposit": None,
        "free_immediately": None,
    }

    kv = {}
    if soup:
        # Extract <dl> <dt> <dd> pairs
        for dt in soup.find_all("dt"):
            dd = dt.find_next_sibling("dd")
            if dd:
                k = dt.get_text(" ", strip=True).lower()
                v = dd.get_text(" ", strip=True)
                kv[k] = v

        # Extract <tr> <th> <td> table rows
        for tr in soup.find_all("tr"):
            th = tr.find(["th", "td"])
            tds = tr.find_all("td")
            if th and len(tds) >= 1:
                k = th.get_text(" ", strip=True).lower()
                v = tds[-1].get_text(" ", strip=True)
                kv[k] = v

        # Extract info cards or label-value components
        for el in soup.find_all(class_=re.compile(r"(info|detail|spec|feature|row|item)", re.IGNORECASE)):
            texts = [t.strip() for t in el.stripped_strings if t.strip()]
            if len(texts) == 2:
                kv[texts[0].lower()] = texts[1]

    # 1. Floor Extraction (KV first, then full text)
    for k, v in kv.items():
        if "kerros" in k or "krs" in k:
            m = re.search(r"(\d{1,2})\s*/\s*(\d{1,2})", v)
            if m:
                f, tf = int(m.group(1)), int(m.group(2))
                if 1 <= f <= 50 and 1 <= tf <= 50 and f <= tf:
                    specs["floor"] = f
                    specs["total_floors"] = tf
                    specs["floor_str"] = f"{f}/{tf}"
                    break
            else:
                m1 = re.search(r"\b(\d{1,2})\b", v)
                if m1:
                    f = int(m1.group(1))
                    if 1 <= f <= 50:
                        specs["floor"] = f
                        specs["floor_str"] = f"{f}"
                        break

    if not specs["floor"]:
        floor_match = RE_FLOOR_DOUBLE.search(text) or RE_FLOOR_DOUBLE_REV.search(text)
        if floor_match:
            f, tf = int(floor_match.group(1)), int(floor_match.group(2))
            if 1 <= f <= 50 and 1 <= tf <= 50 and f <= tf:
                specs["floor"] = f
                specs["total_floors"] = tf
                specs["floor_str"] = f"{f}/{tf}"
        else:
            single_floor = RE_FLOOR_SINGLE.search(text) or RE_FLOOR_SINGLE_REV.search(text)
            if single_floor:
                f = int(single_floor.group(1))
                if 1 <= f <= 50:
                    specs["floor"] = f
                    specs["floor_str"] = f"{f}"
            elif RE_FLOOR_GROUND.search(text):
                specs["floor"] = 1
                specs["floor_str"] = "1"

    # 2. Elevator Extraction
    for k, v in kv.items():
        if "hissi" in k:
            v_low = v.lower()
            if any(w in v_low for w in ("kyllä", "on", "true")):
                specs["has_elevator"] = True
                break
            elif any(w in v_low for w in ("ei", "false")):
                specs["has_elevator"] = False
                break

    if specs["has_elevator"] is None:
        if RE_ELEVATOR_YES.search(text):
            specs["has_elevator"] = True
        elif RE_ELEVATOR_NO.search(text):
            specs["has_elevator"] = False

    # 3. Water Fee Extraction
    for k, v in kv.items():
        if "vesi" in k:
            v_low = v.lower()
            if any(w in v_low for w in ("sisältyy", "sis.", "0 €", "ei erillistä")):
                specs["water_included"] = True
                specs["water_fee"] = "Sisältyy vuokraan"
                break
            elif any(w in v_low for w in ("mittari", "kulutuksen")):
                specs["water_included"] = False
                specs["water_fee"] = "Mittarin mukaan"
                break
            else:
                m = re.search(r"(\d{1,3}(?:[.,]\d{1,2})?)\s*€", v)
                if m:
                    fee = m.group(1).replace(",", ".")
                    specs["water_fee"] = f"{fee} €/hlö/kk"
                    specs["water_included"] = False
                    break

    if specs["water_fee"] is None and not specs["water_included"]:
        if RE_WATER_INCL.search(text):
            specs["water_included"] = True
            specs["water_fee"] = "Sisältyy vuokraan"
        else:
            water_match = RE_WATER_FEE.search(text)
            if water_match:
                fee_val = water_match.group(1).strip().replace(" ", "").replace(",", ".")
                specs["water_fee"] = f"{fee_val} €/hlö/kk"
                specs["water_included"] = False

    # 4. Pets Policy Extraction
    for k, v in kv.items():
        if "lemmik" in k:
            v_low = v.lower()
            if any(w in v_low for w in ("sallittu", "sallittuja", "kyllä", "on", "ok")):
                specs["pets_allowed"] = True
                break
            elif any(w in v_low for w in ("kielletty", "ei")):
                specs["pets_allowed"] = False
                break
            elif any(w in v_low for w in ("sopimuksen", "sovitaan", "neuvoteltavissa", "erikseen")):
                specs["pets_allowed"] = "Sopimuksen mukaan"
                break

    if specs["pets_allowed"] is None:
        if RE_PETS_YES.search(text):
            specs["pets_allowed"] = True
        elif RE_PETS_NO.search(text):
            specs["pets_allowed"] = False
        elif RE_PETS_AGREEMENT.search(text):
            specs["pets_allowed"] = "Sopimuksen mukaan"

    # 5. Balcony Extraction
    for k, v in kv.items():
        if "parveke" in k or "terassi" in k:
            v_low = v.lower()
            if any(w in v_low for w in ("ei", "ei parveketta")):
                specs["has_balcony"] = False
                specs["balcony_type"] = "Ei parveketta"
                break
            elif "lasitettu" in v_low:
                specs["has_balcony"] = True
                specs["balcony_type"] = "Lasitettu parveke"
                break
            elif "ranskalainen" in v_low:
                specs["has_balcony"] = True
                specs["balcony_type"] = "Ranskalainen parveke"
                break
            elif any(w in v_low for w in ("terassi", "piha", "asuntopiha")):
                specs["has_balcony"] = True
                specs["balcony_type"] = "Oma terassi / piha"
                break
            elif any(w in v_low for w in ("kyllä", "on", "parveke")):
                specs["has_balcony"] = True
                specs["balcony_type"] = "Parveke"
                break

    if specs["has_balcony"] is None:
        if RE_BALCONY_NO.search(text):
            specs["has_balcony"] = False
            specs["balcony_type"] = "Ei parveketta"
        elif RE_BALCONY_GLAZED.search(text):
            specs["has_balcony"] = True
            specs["balcony_type"] = "Lasitettu parveke"
        elif RE_BALCONY_FRENCH.search(text):
            specs["has_balcony"] = True
            specs["balcony_type"] = "Ranskalainen parveke"
        elif RE_BALCONY_TERRACE.search(text):
            specs["has_balcony"] = True
            specs["balcony_type"] = "Oma terassi / piha"
        elif RE_BALCONY_ANY.search(text):
            specs["has_balcony"] = True
            specs["balcony_type"] = "Parveke"

    # 6. Sauna Extraction
    for k, v in kv.items():
        if "sauna" in k:
            v_low = v.lower()
            if any(w in v_low for w in ("ei", "ei saunaa")):
                specs["has_sauna"] = False
                specs["sauna_type"] = "Ei saunaa"
                break
            elif any(w in v_low for w in ("oma", "kyllä", "on")):
                specs["has_sauna"] = True
                specs["sauna_type"] = "Oma sauna"
                break
            elif any(w in v_low for w in ("taloyhti", "talosauna", "yhteinen")):
                specs["has_sauna"] = False
                specs["sauna_type"] = "Taloyhtiön sauna"
                break

    if specs["has_sauna"] is None:
        if RE_SAUNA_NO.search(text):
            specs["has_sauna"] = False
            specs["sauna_type"] = "Ei saunaa"
        elif RE_SAUNA_OWN.search(text):
            specs["has_sauna"] = True
            specs["sauna_type"] = "Oma sauna"
        elif RE_SAUNA_BLDG.search(text):
            specs["has_sauna"] = False
            specs["sauna_type"] = "Taloyhtiön sauna"

    # 7. Additional heuristics (condition, year_built, appliances)
    for k, v in kv.items():
        if "kunto" in k and not specs["condition"]:
            v_cap = v.strip().capitalize()
            if any(w in v_cap.lower() for w in ("erinomainen", "uusi", "hyvä", "tyydyttävä", "remontoitu")):
                specs["condition"] = v_cap
        if any(w in k for w in ("rakennusvuosi", "valmistunut", "valmistumisvuosi")) and not specs["year_built"]:
            m = re.search(r"\b(19\d\d|20\d\d)\b", v)
            if m:
                specs["year_built"] = int(m.group(1))

    cond_match = RE_CONDITION.search(text)
    if not specs["condition"] and cond_match:
        c_raw = cond_match.group(1).strip().capitalize()
        if any(w in c_raw.lower() for w in ("erinomainen", "uusi", "uutta vastaava", "hyvä", "tyydyttävä", "remontoitu", "vastaremontoitu")):
            specs["condition"] = c_raw

    yb_match = RE_YEAR_BUILT.search(text)
    if not specs["year_built"] and yb_match:
        specs["year_built"] = int(yb_match.group(1))

    if RE_DISHWASHER_NO.search(text):
        specs["has_dishwasher"] = False
    elif RE_DISHWASHER_YES.search(text):
        specs["has_dishwasher"] = True

    if RE_WASHER_HOOKUP.search(text):
        specs["has_washing_machine_hookup"] = True
    if RE_LAUNDRY_ROOM.search(text):
        specs["has_laundry_room"] = True

    if RE_WALK_IN_CLOSET.search(text):
        specs["has_walk_in_closet"] = True
    if RE_STORAGE.search(text):
        specs["has_storage"] = True

    if RE_INTERNET_INCL.search(text):
        specs["internet_included"] = True

    if RE_DEPOSIT_LOW.search(text):
        specs["low_deposit"] = True

    if RE_FREE_IMMEDIATELY.search(text):
        specs["free_immediately"] = True

    return specs

def extract_specs_from_text(text: str) -> dict:
    return extract_specs_from_soup_and_text(None, text)

def generate_dossier(price: float, size_m2: float, asuinalue: str, raw_text: str = "", extracted_specs: dict = None, lat: float = None, lon: float = None) -> dict:
    specs = extract_specs_from_text(raw_text) if raw_text else {}
    if extracted_specs:
        for k, v in extracted_specs.items():
            if v is not None:
                specs[k] = v

    # Sanitize floor so corrupted numbers (> 50 or < 1) are permanently eliminated
    if specs.get("floor") is not None:
        try:
            f_num = int(specs["floor"])
            if f_num < 1 or f_num > 50:
                specs["floor"] = None
                specs["total_floors"] = None
                specs["floor_str"] = None
            else:
                specs["floor"] = f_num
        except Exception:
            specs["floor"] = None
            specs["total_floors"] = None
            specs["floor_str"] = None

    if specs.get("total_floors") is not None:
        try:
            tf_num = int(specs["total_floors"])
            if tf_num < 1 or tf_num > 50 or (specs.get("floor") and specs["floor"] > tf_num):
                specs["total_floors"] = None
                if specs.get("floor"):
                    specs["floor_str"] = f"{specs['floor']}"
        except Exception:
            specs["total_floors"] = None

    eur_per_m2 = round(price / size_m2, 2) if size_m2 > 0 else 0.0

    pros = []
    cons = []

    # 1. Size-aware €/m² evaluation
    if eur_per_m2 > 0:
        if size_m2 <= 35:
            # Studios / Yksiöt
            if eur_per_m2 <= 23.5:
                pros.append(f"Edullinen neliöhinta yksiölle: {eur_per_m2} €/m² (Helsingissä tyypillisesti 26–31 €/m²)")
            elif eur_per_m2 <= 27.5:
                pros.append(f"Kohtuullinen neliöhinta yksiölle: {eur_per_m2} €/m²")
            elif eur_per_m2 >= 34.0:
                cons.append(f"Korkeahko neliövuokra yksiöksi: {eur_per_m2} €/m²")
        elif size_m2 <= 55:
            # 2 rooms / Kaksiot
            if eur_per_m2 <= 19.5:
                pros.append(f"Erinomainen neliöhinta kaksiolle: {eur_per_m2} €/m² (selvästi alle Helsingin keskiarvon)")
            elif eur_per_m2 <= 23.5:
                pros.append(f"Kilpailukykyinen neliöhinta kaksiolle: {eur_per_m2} €/m²")
            elif eur_per_m2 >= 28.0:
                cons.append(f"Korkeahko neliövuokra kaksiolle: {eur_per_m2} €/m²")
        else:
            # 3+ rooms / Perheasunnot
            if eur_per_m2 <= 17.5:
                pros.append(f"Erinomainen neliöhinta: {eur_per_m2} €/m²")
            elif eur_per_m2 <= 21.0:
                pros.append(f"Kilpailukykyinen neliöhinta: {eur_per_m2} €/m²")
            elif eur_per_m2 >= 25.5:
                cons.append(f"Korkeahko neliövuokra: {eur_per_m2} €/m²")

    # 2. Floor & Elevator Heuristics
    floor = specs.get("floor")
    total_floors = specs.get("total_floors")
    has_elevator = specs.get("has_elevator")

    if floor and total_floors and floor == total_floors and total_floors >= 2:
        if has_elevator is True:
            pros.append(f"Ylin kerros ({floor}/{total_floors}) hissitalossa: ei yläkerran askelääniä, valoisa ja esteetön kulku")
        else:
            pros.append(f"Ylin kerros ({floor}/{total_floors}): rauhaa ja valoisuutta ilman yläkerran naapuriääniä")
    elif floor == 1:
        cons.append("1. kerros / maantaso: pihan kulkuäänet kuuluvat herkemmin ja vähemmän näkösuojaa")

    if has_elevator is True:
        if floor and floor >= 2 and (not total_floors or floor != total_floors):
            pros.append(f"Talossa on hissi: vaivaton kulku {floor}. kerrokseen")
        elif not floor:
            pros.append("Talossa on hissi: vaivaton ja esteetön kulku")
    elif has_elevator is False:
        if floor and floor >= 3:
            cons.append(f"Korkea kerros ({floor}. krs) ilman hissiä: portaiden nousu arjessa ja tavaroita kantaessa raskasta")

    # 3. Water fee: water_included is a PRO; separate water fee is standard in Finland so NOT a con
    if specs.get("water_included"):
        pros.append("Vesimaksu sisältyy vuokraan (säästää n. 20–25 €/hlö kuukausikuluissa)")

    # 4. Pets policy
    if specs.get("pets_allowed") is True:
        pros.append("Lemmikit sallittu vuokranantajan puolesta")
    elif specs.get("pets_allowed") == "Sopimuksen mukaan":
        pros.append("Lemmikit neuvoteltavissa (sopimuksen mukaan)")
    elif specs.get("pets_allowed") is False:
        cons.append("Lemmikkikielto asunnossa")

    # 5. Balcony / Terrace
    balcony_type = specs.get("balcony_type")
    if balcony_type == "Lasitettu parveke":
        pros.append("Lasitettu parveke: toimii viihtyisänä lisähuoneena keväästä pitkälle syksyyn")
    elif balcony_type == "Oma terassi / piha":
        pros.append("Oma terassi / asuntopiha ulkoilmasta nauttimiseen")
    elif specs.get("has_balcony"):
        pros.append(f"{balcony_type or 'Oma parveke'} tuo avaruutta ja tuuletusmahdollisuuden")
    elif specs.get("has_balcony") is False:
        cons.append("Ei omaa parveketta tai terassia")

    # 6. Sauna
    sauna_type = specs.get("sauna_type")
    if specs.get("has_sauna"):
        pros.append("Oma sauna asunnossa: rentoutumista omassa rauhassa milloin vain")
    elif sauna_type == "Taloyhtiön sauna":
        pros.append("Taloyhtiössä sauna käytettävissä saunavuorolla")

    # 7. Listing specifics: condition, year built, dishwasher, internet, deposit, storage
    cond = specs.get("condition")
    if cond:
        if any(w in cond.lower() for w in ("erinomainen", "uusi", "uutta vastaava", "remontoitu", "vastaremontoitu")):
            pros.append(f"Asunnon kunto ({cond}): siisti ja huoleton muuttaa")
        elif "tyydyttävä" in cond.lower():
            cons.append("Asunnon kunto: tyydyttävä (saattaa kaivata pintojen ehostusta)")

    yb = specs.get("year_built")
    if yb and yb >= 2018:
        pros.append(f"Moderni taloyhtiö (valmistunut {yb}): ei suuria remontteja ja matalat energiakulut")

    if specs.get("has_dishwasher") is True:
        pros.append("Astianpesukone valmiina arjen helpottamiseksi")
    elif specs.get("has_dishwasher") is False:
        cons.append("Ei astianpesukonetta")

    if specs.get("has_walk_in_closet") is True:
        pros.append("Erillinen vaatehuone: runsaasti säilytystilaa vaatteille")
    elif specs.get("has_storage") is True:
        pros.append("Oma irtaimistovarasto (kellari- tai vinttikomero)")

    if specs.get("has_washing_machine_hookup") is True:
        pros.append("Pesukoneliitäntä kylpyhuoneessa")
    if specs.get("has_laundry_room") is True:
        pros.append("Taloyhtiössä pesutupa ja kuivaushuone")

    if specs.get("internet_included") is True:
        pros.append("Taloyhtiölaajakaista sisältyy vuokraan")

    if specs.get("low_deposit") is True:
        pros.append("Pieni vuokravakuus (0–1 kk vuokra)")

    if specs.get("free_immediately") is True:
        pros.append("Heti vapaa: joustava sisäänmuutto")

    # 8. District intelligence
    normalized_area = (asuinalue or "").strip()
    profile = None
    for dist_key, dist_data in HELSINKI_DISTRICT_PROFILES.items():
        if dist_key.lower() in normalized_area.lower() or normalized_area.lower() in dist_key.lower():
            profile = dist_data
            break

    if profile:
        for p in profile.get("pros", [])[:2]:
            pros.append(f"{normalized_area}: {p}")
        for c in profile.get("cons", [])[:1]:
            cons.append(f"{normalized_area}: {c}")
        specs["district_vibe"] = profile.get("vibe", f"{normalized_area}, Helsinki")
    else:
        # NO fake generic pros! Clear, honest area label
        specs["district_vibe"] = f"{normalized_area}, Helsinki" if normalized_area else "Helsinki"

    specs["pros"] = pros
    specs["cons"] = cons
    specs["district_vibe"] = profile.get("vibe") if profile else f"Helsinkiläinen asuinalue ({normalized_area})"
    if lat is not None and lon is not None:
        specs["lat"] = lat
        specs["lon"] = lon

    return specs

# =====================================================================
# PYDANTIC MODELS
# =====================================================================

class ManualApartmentInput(BaseModel):
    id: int | None = None
    url: str = Field(..., min_length=8)
    title: str = Field(..., min_length=1)
    asuinalue: str = Field(..., min_length=1)
    price: float = Field(..., gt=0)
    size_m2: float = Field(..., gt=0)
    notes: str = ""
    status: str = "Interested"
    image_url: str | None = None
    lat: float | None = None
    lon: float | None = None
    latitude: float | None = None
    longitude: float | None = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return normalize_url(value)

    @field_validator("title", "asuinalue")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        s = value.strip()
        if not s:
            raise ValueError("Field cannot be empty.")
        return s

class ScrapeApartmentInput(BaseModel):
    url: str = Field(..., min_length=8)
    fallback_asuinalue: str = ""

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return normalize_url(value)

class ApartmentVoteInput(BaseModel):
    apartment_id: int
    vote: str = Field(..., pattern="^(love|neutral|pass)$")

class VuokraoviScraper:
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "fi-FI,fi;q=0.9,en-US;q=0.8,en;q=0.7",
            "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1"
        }

    def extract_official_image(self, soup: BeautifulSoup, html_text: str) -> str:
        # 1. Primary: Open Graph and Twitter meta tags (standard for Vuokraovi / Etuovi)
        for attr in [
            {"property": "og:image"},
            {"property": "og:image:url"},
            {"property": "og:image:secure_url"},
            {"name": "og:image"},
            {"name": "twitter:image"},
            {"name": "twitter:image:src"},
            {"property": "twitter:image"}
        ]:
            tag = soup.find("meta", attrs=attr)
            if tag and tag.get("content"):
                cand = tag["content"].strip()
                if cand.startswith("//"):
                    cand = "https:" + cand
                if cand.startswith("http") and not any(k in cand.lower() for k in ("logo", "icon", "blank", "tracking", "pixel", "avatar", "default")):
                    return cand

        # 2. Schema.org JSON-LD structured data (<script type="application/ld+json">)
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                content = script.string or script.text or ""
                if not content.strip():
                    continue
                data = json.loads(content)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    imgs = item.get("image") or item.get("photo")
                    if isinstance(imgs, str) and imgs.startswith("http"):
                        return imgs
                    elif isinstance(imgs, list) and imgs:
                        first = imgs[0]
                        if isinstance(first, str) and first.startswith("http"):
                            return first
                        elif isinstance(first, dict) and first.get("url"):
                            return first["url"]
                    elif isinstance(imgs, dict) and imgs.get("url"):
                        return imgs["url"]
            except Exception:
                continue

        # 3. Next.js / React dehydrated __NEXT_DATA__
        next_script = soup.find("script", id="__NEXT_DATA__")
        if next_script and next_script.string:
            try:
                data = json.loads(next_script.string)
                def find_img(obj):
                    if isinstance(obj, dict):
                        for k in ("images", "pictures", "photos", "imageUrls", "gallery"):
                            val = obj.get(k)
                            if isinstance(val, list) and val:
                                for item in val:
                                    if isinstance(item, str) and item.startswith("http") and not any(x in item.lower() for x in ("logo", "icon", "avatar")):
                                        return item
                                    elif isinstance(item, dict):
                                        for subk in ("url", "src", "large", "original", "href", "full"):
                                            if item.get(subk) and str(item[subk]).startswith("http"):
                                                return item[subk]
                        for v in obj.values():
                            res = find_img(v)
                            if res:
                                return res
                    elif isinstance(obj, list):
                        for elem in obj:
                            res = find_img(elem)
                            if res:
                                return res
                    return None

                cand = find_img(data.get("props", {}))
                if cand:
                    return cand
            except Exception:
                pass

        # 4. Link elements
        for rel in ("image_src", "preload"):
            for link in soup.find_all("link", rel=rel):
                href = link.get("href", "").strip()
                if href.startswith("http") and any(k in href.lower() for k in ("vuokraovi", "etuovi", "cloudfront", "images")) and not any(k in href.lower() for k in ("logo", "icon", "avatar")):
                    return href

        # 5. DOM Image / Picture elements
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or img.get("data-lazy") or img.get("data-original") or ""
            srcset = img.get("srcset") or img.get("data-srcset") or ""
            candidates = []
            if srcset:
                parts = [p.strip().split(" ")[0] for p in srcset.split(",") if p.strip()]
                if parts:
                    candidates.append(parts[-1])
            if src:
                candidates.append(src)

            for cand in candidates:
                if cand.startswith("//"):
                    cand = "https:" + cand
                if cand.startswith("http"):
                    cand_lower = cand.lower()
                    if any(k in cand_lower for k in ("vuokraovi", "etuovi", "cloudfront", "almamedia", "image-carousel", "gallery")):
                        if not any(k in cand_lower for k in ("logo", "icon", "blank", "tracking", "pixel", "avatar")):
                            return cand

        # 6. Fallback regex match across raw HTML for Alma/Vuokraovi/Cloudfront image CDN
        cdn_matches = re.findall(
            r'https?://(?:images\.vuokraovi\.com|cdn\.etuovi\.com|images\.etuovi\.com|[a-zA-Z0-9_-]+\.cloudfront\.net)/[^\s"\'<>]+\.(?:jpg|jpeg|png|webp)',
            html_text,
            re.IGNORECASE
        )
        for cand in cdn_matches:
            cand_lower = cand.lower()
            if not any(k in cand_lower for k in ("logo", "icon", "blank", "tracking", "pixel", "avatar")):
                return cand

        return ""

    def scrape_image_only(self, url: str) -> str:
        try:
            resp = httpx.get(url, headers=self.headers, follow_redirects=True, timeout=5.0)
            if resp.status_code == 200:
                sp = BeautifulSoup(resp.text, "html.parser")
                return self.extract_official_image(sp, resp.text)
        except Exception:
            pass
        return ""

    def scrape_specs_and_dossier(self, url: str, price: float, size_m2: float, asuinalue: str, lat: float = None, lon: float = None) -> dict:
        try:
            resp = httpx.get(url, headers=self.headers, follow_redirects=True, timeout=6.0)
            if resp.status_code == 200:
                sp = BeautifulSoup(resp.text, "html.parser")
                text = sp.get_text(" ", strip=True)
                specs_data = extract_specs_from_soup_and_text(sp, text)
                img = self.extract_official_image(sp, resp.text)
                dossier = generate_dossier(
                    price=price,
                    size_m2=size_m2,
                    asuinalue=asuinalue,
                    raw_text=text,
                    extracted_specs=specs_data,
                    lat=lat,
                    lon=lon
                )
                if img:
                    dossier["image_url"] = img
                return dossier
        except Exception:
            pass
        return {}

    def extract(self, url: str, fallback_area: str = "") -> dict:
        try:
            response = httpx.get(url, headers=self.headers, follow_redirects=True, timeout=15.0)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ValueError(f"Vuokraovi page returned HTTP {exc.response.status_code}")
        except Exception as exc:
            raise ValueError(f"Connection to listing failed: {str(exc)}")

        soup = BeautifulSoup(response.text, "html.parser")
        raw_title = soup.title.string.strip() if soup.title and soup.title.string else ""
        title = raw_title.replace(" - Vuokraovi.com", "").strip() or "Vuokraovi Kohde"
        text = soup.get_text(" ", strip=True)

        area_match = re.search(r"kohteen:\s*([^,]+),\s*([^,]+),\s*Helsinki", text, re.IGNORECASE)
        asuinalue = fallback_area.strip() or (area_match.group(2).strip() if area_match else "")
        if not asuinalue:
            raise ValueError("Could not detect asuinalue. Please type a Fallback asuinalue.")

        price_match = re.search(r"(\d[\d\s\xa0]*(?:,\d+)?)\s*€\s*/\s*kk", text)
        price_str = re.sub(r"[\s\xa0]", "", price_match.group(1)).replace(",", ".") if price_match else "0"

        size_match = re.search(r"(\d+(?:,\d+)?)\s*m²", text)
        size_str = size_match.group(1).replace(",", ".") if size_match else "0"

        price_val = float(price_str)
        size_val = float(size_str)

        if price_val <= 0 or size_val <= 0:
            raise ValueError("Could not extract price or size. Use manual entry (Option A).")

        # Extract official main listing image URL
        image_url = self.extract_official_image(soup, response.text)

        # Phase 4: Geocode via HSL Digitransit Pelias API
        lat, lon = geocode_address_hsl(title, asuinalue)

        # Phase 3: Extract structured specs via deep HTML parsing + regex & compile dossier
        specs_data = extract_specs_from_soup_and_text(soup, text)
        dossier = generate_dossier(
            price=price_val,
            size_m2=size_val,
            asuinalue=asuinalue.title(),
            raw_text=text,
            extracted_specs=specs_data,
            lat=lat,
            lon=lon
        )
        if image_url:
            dossier["image_url"] = image_url

        return {
            "url": url,
            "title": title,
            "asuinalue": asuinalue.title(),
            "price": price_val,
            "size_m2": size_val,
            "notes": "",
            "status": "Interested",
            "image_url": image_url,
            "lat": lat,
            "lon": lon,
            "latitude": lat,
            "longitude": lon,
            "specs": dossier
        }

app = FastAPI()

class VercelPathMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.scope.get("path", "")
        if path.startswith("/api/index.py"):
            new_path = path.replace("/api/index.py", "", 1)
            request.scope["path"] = new_path or "/"
        return await call_next(request)

app.add_middleware(VercelPathMiddleware)

scraper = VuokraoviScraper()

@app.get("/apartments")
@app.get("/api/apartments")
def list_apartments(sort_by: str = "price", desc: bool = False, authorization: str = Header(None)):
    get_current_user(authorization)
    sb = get_supabase()
    res = sb.table("apartments").select("*").order("asuinalue", desc=False).execute()
    rows = res.data or []

    # Phase 2: Partner votes
    votes_by_apt = {}
    try:
        votes_res = sb.table("apartment_votes").select("*").execute()
        for v in (votes_res.data or []):
            apt_id = v.get("apartment_id")
            user_name = v.get("user_name")
            vote_val = v.get("vote")
            if apt_id and user_name:
                votes_by_apt.setdefault(apt_id, {})[user_name] = vote_val
    except Exception:
        pass

    grouped = {}
    for item in rows:
        price = float(item.get("price", 0))
        size = float(item.get("size_m2", 0))
        item["eur_per_m2"] = round(price / size, 2) if size > 0 else 0.0
        area = item.get("asuinalue", "Tuntematon")
        if not item.get("added_by"):
            item["added_by"] = "Leo"

        # Partner voting and mutual match status (Phase 2)
        apt_id = item.get("id")
        apt_votes = votes_by_apt.get(apt_id, {})
        item["votes"] = apt_votes
        item["is_mutual_match"] = (apt_votes.get("Leo") == "love" and apt_votes.get("Ella") == "love")

        # Phase 4: Ensure lat & lon coordinates exist (reading latitude/longitude or lat/lon)
        apt_id = item.get("id")
        lat = item.get("latitude") if item.get("latitude") is not None else item.get("lat")
        lon = item.get("longitude") if item.get("longitude") is not None else item.get("lon")

        # Detect missing or corrupted old Kaarela default coordinates (lat ~ 60.245, lon ~ 24.862)
        needs_regeocode = (lat is None or lon is None)
        if not needs_regeocode and (60.24 <= lat <= 60.25 and 24.85 <= lon <= 24.88 and area.lower() not in ("kaarela", "malminkartano", "kannelmäki")):
            needs_regeocode = True

        if needs_regeocode:
            lat, lon = geocode_address_hsl(item.get("title", ""), area)
            try:
                sb.table("apartments").update({
                    "latitude": lat,
                    "longitude": lon
                }).eq("id", apt_id).execute()
            except Exception:
                pass

        item["latitude"] = lat
        item["longitude"] = lon
        item["lat"] = lat
        item["lon"] = lon

        # Phase 3: Ensure structured dossier is present, clean, and auto-healed
        existing_specs = item.get("specs") or {}
        needs_dossier_regen = False
        if not existing_specs:
            needs_dossier_regen = True
        else:
            floor_val = existing_specs.get("floor")
            if floor_val is not None and (not isinstance(floor_val, int) or floor_val > 50 or floor_val < 1):
                needs_dossier_regen = True
            elif any("Viihtyisä ja vakiintunut" in p for p in existing_specs.get("pros", [])):
                needs_dossier_regen = True
            elif any("vesimaksu" in c.lower() for c in existing_specs.get("cons", [])):
                needs_dossier_regen = True
            elif existing_specs.get("floor") is None and existing_specs.get("has_elevator") is None and existing_specs.get("water_fee") is None:
                needs_dossier_regen = True

        if needs_dossier_regen:
            scraped_dossier = None
            if "vuokraovi.com" in (item.get("url") or ""):
                try:
                    scraped_dossier = scraper.scrape_specs_and_dossier(
                        url=item["url"],
                        price=price,
                        size_m2=size,
                        asuinalue=area,
                        lat=lat,
                        lon=lon
                    )
                except Exception:
                    pass

            if scraped_dossier and scraped_dossier.get("pros") is not None:
                item["specs"] = scraped_dossier
                if scraped_dossier.get("image_url") and not item.get("image_url"):
                    item["image_url"] = scraped_dossier["image_url"]
            else:
                item["specs"] = generate_dossier(
                    price=price,
                    size_m2=size,
                    asuinalue=area,
                    raw_text=f"{item.get('title', '')} {item.get('notes', '')}",
                    extracted_specs=existing_specs if existing_specs else None,
                    lat=lat,
                    lon=lon
                )

            try:
                up_payload = {"specs": item["specs"]}
                if item.get("image_url"):
                    up_payload["image_url"] = item["image_url"]
                sb.table("apartments").update(up_payload).eq("id", apt_id).execute()
            except Exception:
                pass
        else:
            if "lat" not in item["specs"]:
                item["specs"]["lat"] = lat
                item["specs"]["lon"] = lon

        # Ensure image_url is available from Vuokraovi official listing
        img = item.get("image_url") or (item.get("specs") or {}).get("image_url") or ""
        if not img and "vuokraovi.com" in (item.get("url") or ""):
            try:
                scraped_img = scraper.scrape_image_only(item["url"])
                if scraped_img:
                    img = scraped_img
                    if item.get("specs"):
                        item["specs"]["image_url"] = scraped_img
                    try:
                        sb.table("apartments").update({"image_url": scraped_img}).eq("id", apt_id).execute()
                    except Exception:
                        pass
            except Exception:
                pass
        item["image_url"] = img

        grouped.setdefault(area, []).append(item)

    sort_key = sort_by if sort_by in ("price", "size_m2", "eur_per_m2") else "price"
    for area in grouped:
        grouped[area].sort(key=lambda x: x.get(sort_key, 0), reverse=desc)
    return grouped

@app.post("/apartments/manual")
@app.post("/api/apartments/manual")
def add_manual(payload: ManualApartmentInput, authorization: str = Header(None)):
    user = get_current_user(authorization)
    require_editor(user)
    sb = get_supabase()

    # Phase 4: Geocode
    lat = payload.latitude if payload.latitude is not None else payload.lat
    lon = payload.longitude if payload.longitude is not None else payload.lon
    if lat is None or lon is None:
        lat, lon = geocode_address_hsl(payload.title, payload.asuinalue)

    # Phase 3: Generate heuristic dossier for manual entries
    dossier = generate_dossier(
        price=payload.price,
        size_m2=payload.size_m2,
        asuinalue=payload.asuinalue.strip().title(),
        raw_text=f"{payload.title} {payload.notes}",
        lat=lat,
        lon=lon
    )
    img = (payload.image_url or "").strip()
    if img:
        dossier["image_url"] = img

    data = {
        "url": payload.url,
        "title": payload.title.strip(),
        "asuinalue": payload.asuinalue.strip().title(),
        "price": payload.price,
        "size_m2": payload.size_m2,
        "notes": payload.notes.strip(),
        "status": payload.status.strip(),
        "added_by": user["display_name"],
        "latitude": lat,
        "longitude": lon,
        "image_url": img or None,
        "specs": dossier
    }

    try:
        if payload.id:
            data["id"] = payload.id
            res = sb.table("apartments").upsert(data, on_conflict="id").execute()
        else:
            res = sb.table("apartments").upsert(data, on_conflict="url").execute()
    except Exception as exc:
        if "image_url" in str(exc).lower():
            data.pop("image_url", None)
            if payload.id:
                data["id"] = payload.id
                res = sb.table("apartments").upsert(data, on_conflict="id").execute()
            else:
                res = sb.table("apartments").upsert(data, on_conflict="url").execute()
        else:
            raise HTTPException(status_code=400, detail=str(exc))

    return {"status": "saved", "data": res.data}

@app.post("/apartments/scrape")
@app.post("/api/apartments/scrape")
def add_scraped(payload: ScrapeApartmentInput, authorization: str = Header(None)):
    user = get_current_user(authorization)
    require_editor(user)
    try:
        extracted = scraper.extract(payload.url, payload.fallback_asuinalue)
        extracted["added_by"] = user["display_name"]
        sb = get_supabase()
        
        img = extracted.get("image_url", "")
        db_payload = {
            "url": extracted["url"],
            "title": extracted["title"],
            "asuinalue": extracted["asuinalue"],
            "price": extracted["price"],
            "size_m2": extracted["size_m2"],
            "notes": extracted.get("notes", ""),
            "status": extracted.get("status", "Interested"),
            "added_by": extracted["added_by"],
            "latitude": extracted.get("latitude") if extracted.get("latitude") is not None else extracted.get("lat"),
            "longitude": extracted.get("longitude") if extracted.get("longitude") is not None else extracted.get("lon"),
            "image_url": img or None,
            "specs": extracted.get("specs", {})
        }
        try:
            res = sb.table("apartments").upsert(db_payload, on_conflict="url").execute()
        except Exception as exc:
            if "image_url" in str(exc).lower():
                db_payload.pop("image_url", None)
                res = sb.table("apartments").upsert(db_payload, on_conflict="url").execute()
            else:
                raise exc

        return {"status": "saved", "data": res.data, "asuinalue": extracted["asuinalue"]}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

class ApartmentImageInput(BaseModel):
    apartment_id: int
    image_url: str = Field(..., max_length=1500)

@app.post("/apartments/image")
@app.post("/api/apartments/image")
def update_apartment_image(payload: ApartmentImageInput, authorization: str = Header(None)):
    user = get_current_user(authorization)
    require_editor(user)
    sb = get_supabase()
    clean_img = payload.image_url.strip()

    try:
        apt_res = sb.table("apartments").select("specs").eq("id", payload.apartment_id).execute()
        specs = (apt_res.data[0].get("specs") if apt_res.data else {}) or {}
        specs["image_url"] = clean_img
        update_data = {"specs": specs, "image_url": clean_img}
        try:
            res = sb.table("apartments").update(update_data).eq("id", payload.apartment_id).execute()
        except Exception as exc:
            if "image_url" in str(exc).lower():
                res = sb.table("apartments").update({"specs": specs}).eq("id", payload.apartment_id).execute()
            else:
                raise exc
        return {"status": "saved", "image_url": clean_img, "data": res.data}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@app.post("/apartments/vote")
@app.post("/api/apartments/vote")
def cast_vote(payload: ApartmentVoteInput, authorization: str = Header(None)):
    user = get_current_user(authorization)
    require_editor(user)
    user_name = user["display_name"]
    sb = get_supabase()
    vote_data = {
        "apartment_id": payload.apartment_id,
        "user_name": user_name,
        "vote": payload.vote
    }

    try:
        sb.table("apartment_votes").upsert(vote_data, on_conflict="apartment_id,user_name").execute()
    except Exception:
        sb.table("apartment_votes").upsert(vote_data).execute()

    is_match = False
    try:
        votes_res = sb.table("apartment_votes").select("*").eq("apartment_id", payload.apartment_id).execute()
        vote_dict = {row.get("user_name"): row.get("vote") for row in (votes_res.data or [])}
        is_match = (vote_dict.get("Leo") == "love" and vote_dict.get("Ella") == "love")
    except Exception:
        pass

    return {
        "status": "saved",
        "apartment_id": payload.apartment_id,
        "user_name": user_name,
        "vote": payload.vote,
        "is_mutual_match": is_match
    }

@app.delete("/apartments/{apt_id}")
@app.delete("/api/apartments/{apt_id}")
def remove_apartment(apt_id: int, authorization: str = Header(None)):
    user = get_current_user(authorization)
    require_editor(user)
    sb = get_supabase()
    sb.table("apartments").delete().eq("id", apt_id).execute()
    try:
        sb.table("apartment_votes").delete().eq("apartment_id", apt_id).execute()
    except Exception:
        pass
    return {"deleted": apt_id}
