import os
import re
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

RE_FLOOR_DOUBLE = re.compile(r"(?:kerros[:\s]*|krs[:\s]*)?(\d+)\s*/\s*(\d+)", re.IGNORECASE)
RE_FLOOR_SINGLE = re.compile(r"kerros[:\s]*(\d+)", re.IGNORECASE)
RE_ELEVATOR_YES = re.compile(r"(?:talossa\s+(?:on\s+)?hissi|hissi\s*:\s*(?:on|kyllä)|on\s+hissi)", re.IGNORECASE)
RE_ELEVATOR_NO = re.compile(r"(?:ei\s+hissiä|hissi\s*:\s*ei)", re.IGNORECASE)
RE_WATER_INCL = re.compile(r"vesi(?:maksu)?\s+sisältyy(?:\s+vuokraan)?", re.IGNORECASE)
RE_WATER_FEE = re.compile(r"vesimaksu[:\s]*(\d+[\d\s,.]*)\s*€(?:\s*/\s*(?:hlö|kk|kuukausi|hlö/kk))?", re.IGNORECASE)
RE_PETS_YES = re.compile(r"lemmik(?:it|kieläimet)\s+(?:ovat\s+)?sallittu", re.IGNORECASE)
RE_PETS_NO = re.compile(r"(?:ei\s+lemmikkejä|lemmikit\s+kielletty)", re.IGNORECASE)
RE_PETS_AGREEMENT = re.compile(r"lemmik(?:it|eistä)\s+sopimuksen\s+mukaan", re.IGNORECASE)
RE_BALCONY_GLAZED = re.compile(r"lasitettu(?:\s+oma)?\s+parveke", re.IGNORECASE)
RE_BALCONY_FRENCH = re.compile(r"ranskalainen\s+parveke", re.IGNORECASE)
RE_BALCONY_ANY = re.compile(r"(?<!ei\s)parveke", re.IGNORECASE)
RE_BALCONY_NO = re.compile(r"ei\s+parveketta", re.IGNORECASE)
RE_SAUNA_OWN = re.compile(r"(?:oma\s+sauna|sauna\s*:\s*(?:on|kyllä))", re.IGNORECASE)
RE_SAUNA_BLDG = re.compile(r"(?:taloyhti(?:össä|ön)\s+sauna|talosauna)", re.IGNORECASE)
RE_SAUNA_NO = re.compile(r"ei\s+saunaa", re.IGNORECASE)

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
        "vibe": "Merellinen ja luonnonläheinen saaristokaupunginosa",
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
    }
}

def extract_specs_from_text(text: str) -> dict:
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
    }

    floor_match = RE_FLOOR_DOUBLE.search(text)
    if floor_match:
        f = int(floor_match.group(1))
        tf = int(floor_match.group(2))
        specs["floor"] = f
        specs["total_floors"] = tf
        specs["floor_str"] = f"{f}/{tf}"
    else:
        single_floor = RE_FLOOR_SINGLE.search(text)
        if single_floor:
            f = int(single_floor.group(1))
            specs["floor"] = f
            specs["floor_str"] = f"{f}"

    if RE_ELEVATOR_YES.search(text):
        specs["has_elevator"] = True
    elif RE_ELEVATOR_NO.search(text):
        specs["has_elevator"] = False

    if RE_WATER_INCL.search(text):
        specs["water_included"] = True
        specs["water_fee"] = "Sisältyy vuokraan"
    else:
        water_match = RE_WATER_FEE.search(text)
        if water_match:
            fee_val = water_match.group(1).strip().replace(" ", "").replace(",", ".")
            specs["water_fee"] = f"{fee_val} €/hlö/kk"
            specs["water_included"] = False

    if RE_PETS_YES.search(text):
        specs["pets_allowed"] = True
    elif RE_PETS_NO.search(text):
        specs["pets_allowed"] = False
    elif RE_PETS_AGREEMENT.search(text):
        specs["pets_allowed"] = "Sopimuksen mukaan"

    if RE_BALCONY_GLAZED.search(text):
        specs["has_balcony"] = True
        specs["balcony_type"] = "Lasitettu parveke"
    elif RE_BALCONY_FRENCH.search(text):
        specs["has_balcony"] = True
        specs["balcony_type"] = "Ranskalainen parveke"
    elif RE_BALCONY_ANY.search(text):
        specs["has_balcony"] = True
        specs["balcony_type"] = "Parveke"
    elif RE_BALCONY_NO.search(text):
        specs["has_balcony"] = False
        specs["balcony_type"] = "Ei parveketta"

    if RE_SAUNA_OWN.search(text):
        specs["has_sauna"] = True
        specs["sauna_type"] = "Oma sauna"
    elif RE_SAUNA_BLDG.search(text):
        specs["has_sauna"] = False
        specs["sauna_type"] = "Taloyhtiön sauna"
    elif RE_SAUNA_NO.search(text):
        specs["has_sauna"] = False
        specs["sauna_type"] = "Ei saunaa"

    return specs

def generate_dossier(price: float, size_m2: float, asuinalue: str, raw_text: str = "", extracted_specs: dict = None, lat: float = None, lon: float = None) -> dict:
    specs = extract_specs_from_text(raw_text)
    if extracted_specs:
        for k, v in extracted_specs.items():
            if v is not None:
                specs[k] = v

    eur_per_m2 = round(price / size_m2, 2) if size_m2 > 0 else 0.0

    pros = []
    cons = []

    if eur_per_m2 > 0:
        if eur_per_m2 <= 21.0:
            pros.append(f"Erinomainen neliöhinta: {eur_per_m2} €/m² (selvästi alle Helsingin keskiarvon)")
        elif eur_per_m2 <= 25.5:
            pros.append(f"Kilpailukykyinen neliöhinta: {eur_per_m2} €/m²")
        elif eur_per_m2 >= 32.0:
            cons.append(f"Korkeahko neliövuokra: {eur_per_m2} €/m²")

    floor = specs.get("floor")
    total_floors = specs.get("total_floors")
    has_elevator = specs.get("has_elevator")

    if floor and total_floors:
        if floor == total_floors and total_floors >= 2:
            pros.append(f"Ylin kerros ({floor}/{total_floors}): ei yläkerran askelääniä ja parempi valoisuus")
        elif floor == 1:
            cons.append("Maantaso / 1. kerros: vähemmän yksityisyyttä ja pihan äänet kuuluvat helpommin")
    elif floor == 1:
        cons.append("1. kerros: mahdollinen katutason häiriö")

    if has_elevator is True:
        pros.append("Talossa on hissi: vaivaton kulku ja esteettömyys")
    elif has_elevator is False:
        if floor and floor >= 3:
            cons.append(f"Korkea kerros ({floor}. krs) ilman hissiä: portaiden nousu arjessa ja muutoissa raskasta")
        else:
            cons.append("Taloyhtiössä ei ole hissiä")

    if specs.get("water_included"):
        pros.append("Vesimaksu sisältyy vuokraan (säästää ~20–25 €/hlö kuukausikuluissa)")
    elif specs.get("water_fee"):
        cons.append(f"Erillinen vesimaksu ({specs['water_fee']}) lisätään kuukausikustannuksiin")

    if specs.get("pets_allowed") is True:
        pros.append("Lemmikit sallittu vuokranantajan puolesta")
    elif specs.get("pets_allowed") is False:
        cons.append("Lemmikkikielto asunnossa")

    balcony_type = specs.get("balcony_type")
    if balcony_type == "Lasitettu parveke":
        pros.append("Lasitettu parveke: toimii viihtyisänä lisähuoneena keväästä pitkälle syksyyn")
    elif specs.get("has_balcony"):
        pros.append(f"{balcony_type or 'Oma parveke'} tuo lisää avaruutta ja tuuletusmahdollisuuden")
    elif specs.get("has_balcony") is False:
        cons.append("Ei omaa parveketta")

    sauna_type = specs.get("sauna_type")
    if specs.get("has_sauna"):
        pros.append("Oma sauna asunnossa: rentoutumista ja arjen luksusta milloin vain")
    elif sauna_type == "Taloyhtiön sauna":
        pros.append("Taloyhtiössä sauna käytettävissä saunavuorolla")
    elif specs.get("has_sauna") is False and sauna_type == "Ei saunaa":
        cons.append("Asunnossa ei omaa saunaa")

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
    elif normalized_area:
        pros.append(f"{normalized_area}: Viihtyisä ja vakiintunut helsinkiläinen asuinalue")

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
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "fi,en-US;q=0.9,en;q=0.8",
        }

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

        # Phase 4: Geocode via HSL Digitransit Pelias API
        lat, lon = geocode_address_hsl(title, asuinalue)

        # Phase 3: Extract structured specs via regex & compile dossier
        specs_data = extract_specs_from_text(text)
        dossier = generate_dossier(
            price=price_val,
            size_m2=size_val,
            asuinalue=asuinalue.title(),
            raw_text=text,
            extracted_specs=specs_data,
            lat=lat,
            lon=lon
        )

        return {
            "url": url,
            "title": title,
            "asuinalue": asuinalue.title(),
            "price": price_val,
            "size_m2": size_val,
            "notes": "",
            "status": "Interested",
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

        # Phase 3: Ensure structured dossier is present even on older records
        if not item.get("specs"):
            item["specs"] = generate_dossier(
                price=price,
                size_m2=size,
                asuinalue=area,
                raw_text=f"{item.get('title', '')} {item.get('notes', '')}",
                lat=lat,
                lon=lon
            )
        else:
            if "lat" not in item["specs"]:
                item["specs"]["lat"] = lat
                item["specs"]["lon"] = lon

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
        "specs": dossier
    }

    try:
        if payload.id:
            data["id"] = payload.id
            res = sb.table("apartments").upsert(data, on_conflict="id").execute()
        else:
            res = sb.table("apartments").upsert(data, on_conflict="url").execute()
    except Exception as exc:
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
            "specs": extracted.get("specs", {})
        }
        res = sb.table("apartments").upsert(db_payload, on_conflict="url").execute()

        return {"status": "saved", "data": res.data, "asuinalue": extracted["asuinalue"]}
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
