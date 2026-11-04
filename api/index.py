import os
import re
from urllib.parse import urlsplit, urlunsplit
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
        
        return {
            "id": user.id,
            "email": user.email,
            "display_name": display_name
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Authentication error: {str(exc)}")
    
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
    """
    Extracts structured apartment specifications from raw Finnish listing text using regex.
    """
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

    # 1. Floor & Total floors (e.g. "Kerros: 4/6", "4/6", "Kerros 2/5", "3. kerros", "1/4")
    floor_match = re.search(r"(?:kerros[:\s]*|krs[:\s]*)?(\d+)\s*/\s*(\d+)", text, re.IGNORECASE)
    if floor_match:
        f = int(floor_match.group(1))
        tf = int(floor_match.group(2))
        specs["floor"] = f
        specs["total_floors"] = tf
        specs["floor_str"] = f"{f}/{tf}"
    else:
        single_floor = re.search(r"kerros[:\s]*(\d+)", text, re.IGNORECASE)
        if single_floor:
            f = int(single_floor.group(1))
            specs["floor"] = f
            specs["floor_str"] = f"{f}"

    # 2. Elevator status ("on hissi", "talossa on hissi", "hissi: on", "ei hissiä", "hissi: ei")
    if re.search(r"(?:talossa\s+(?:on\s+)?hissi|hissi\s*:\s*(?:on|kyllä)|on\s+hissi)", text, re.IGNORECASE):
        specs["has_elevator"] = True
    elif re.search(r"(?:ei\s+hissiä|hissi\s*:\s*ei)", text, re.IGNORECASE):
        specs["has_elevator"] = False

    # 3. Water fee ("vesimaksu: 20 €/hlö", "vesi sisältyy vuokraan", "vesimaksu sisältyy")
    if re.search(r"vesi(?:maksu)?\s+sisältyy(?:\s+vuokraan)?", text, re.IGNORECASE):
        specs["water_included"] = True
        specs["water_fee"] = "Sisältyy vuokraan"
    else:
        water_match = re.search(r"vesimaksu[:\s]*(\d+[\d\s,.]*)\s*€(?:\s*/\s*(?:hlö|kk|kuukausi|hlö/kk))?", text, re.IGNORECASE)
        if water_match:
            fee_val = water_match.group(1).strip().replace(" ", "").replace(",", ".")
            specs["water_fee"] = f"{fee_val} €/hlö/kk"
            specs["water_included"] = False

    # 4. Pet policy ("lemmikit sallittu", "lemmikkieläimet sallittu", "ei lemmikkejä", "lemmikit kielletty", "sopimuksen mukaan")
    if re.search(r"lemmik(?:it|kieläimet)\s+(?:ovat\s+)?sallittu", text, re.IGNORECASE):
        specs["pets_allowed"] = True
    elif re.search(r"(?:ei\s+lemmikkejä|lemmikit\s+kielletty)", text, re.IGNORECASE):
        specs["pets_allowed"] = False
    elif re.search(r"lemmik(?:it|eistä)\s+sopimuksen\s+mukaan", text, re.IGNORECASE):
        specs["pets_allowed"] = "Sopimuksen mukaan"

    # 5. Balcony (parveke / lasitettu / ranskalainen / ei parveketta)
    if re.search(r"lasitettu(?:\s+oma)?\s+parveke", text, re.IGNORECASE):
        specs["has_balcony"] = True
        specs["balcony_type"] = "Lasitettu parveke"
    elif re.search(r"ranskalainen\s+parveke", text, re.IGNORECASE):
        specs["has_balcony"] = True
        specs["balcony_type"] = "Ranskalainen parveke"
    elif re.search(r"(?<!ei\s)parveke", text, re.IGNORECASE):
        specs["has_balcony"] = True
        specs["balcony_type"] = "Parveke"
    elif re.search(r"ei\s+parveketta", text, re.IGNORECASE):
        specs["has_balcony"] = False
        specs["balcony_type"] = "Ei parveketta"

    # 6. Sauna (oma sauna, sauna: on, taloyhtiössä sauna, ei saunaa)
    if re.search(r"(?:oma\s+sauna|sauna\s*:\s*(?:on|kyllä))", text, re.IGNORECASE):
        specs["has_sauna"] = True
        specs["sauna_type"] = "Oma sauna"
    elif re.search(r"(?:taloyhti(?:össä|ön)\s+sauna|talosauna)", text, re.IGNORECASE):
        specs["has_sauna"] = False
        specs["sauna_type"] = "Taloyhtiön sauna"
    elif re.search(r"ei\s+saunaa", text, re.IGNORECASE):
        specs["has_sauna"] = False
        specs["sauna_type"] = "Ei saunaa"

    return specs

def generate_dossier(price: float, size_m2: float, asuinalue: str, raw_text: str = "", extracted_specs: dict = None) -> dict:
    """
    Evaluates apartment metrics and pairs them with district profiles to produce
    a comprehensive rules-based dossier with structured specs and pros/cons arrays.
    """
    specs = extract_specs_from_text(raw_text)
    if extracted_specs:
        for k, v in extracted_specs.items():
            if v is not None:
                specs[k] = v

    eur_per_m2 = round(price / size_m2, 2) if size_m2 > 0 else 0.0

    pros = []
    cons = []

    # 1. Price / €/m² evaluation
    if eur_per_m2 > 0:
        if eur_per_m2 <= 21.0:
            pros.append(f"Erinomainen neliöhinta: {eur_per_m2} €/m² (selvästi alle Helsingin keskiarvon)")
        elif eur_per_m2 <= 25.5:
            pros.append(f"Kilpailukykyinen neliöhinta: {eur_per_m2} €/m²")
        elif eur_per_m2 >= 32.0:
            cons.append(f"Korkeahko neliövuokra: {eur_per_m2} €/m²")

    # 2. Floor & Elevator evaluation
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

    # 3. Water fee evaluation
    if specs.get("water_included"):
        pros.append("Vesimaksu sisältyy vuokraan (säästää ~20–25 €/hlö kuukausikuluissa)")
    elif specs.get("water_fee"):
        cons.append(f"Erillinen vesimaksu ({specs['water_fee']}) lisätään kuukausikustannuksiin")

    # 4. Pet policy evaluation
    if specs.get("pets_allowed") is True:
        pros.append("Lemmikit sallittu vuokranantajan puolesta")
    elif specs.get("pets_allowed") is False:
        cons.append("Lemmikkikielto asunnossa")

    # 5. Balcony evaluation
    balcony_type = specs.get("balcony_type")
    if balcony_type == "Lasitettu parveke":
        pros.append("Lasitettu parveke: toimii viihtyisänä lisähuoneena keväästä pitkälle syksyyn")
    elif specs.get("has_balcony"):
        pros.append(f"{balcony_type or 'Oma parveke'} tuo lisää avaruutta ja tuuletusmahdollisuuden")
    elif specs.get("has_balcony") is False:
        cons.append("Ei omaa parveketta")

    # 6. Sauna evaluation
    sauna_type = specs.get("sauna_type")
    if specs.get("has_sauna"):
        pros.append("Oma sauna asunnossa: rentoutumista ja arjen luksusta milloin vain")
    elif sauna_type == "Taloyhtiön sauna":
        pros.append("Taloyhtiössä sauna käytettävissä saunavuorolla")
    elif specs.get("has_sauna") is False and sauna_type == "Ei saunaa":
        cons.append("Asunnossa ei omaa saunaa")

    # 7. District Profile pairing
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

    return specs

# =====================================================================
# PYDANTIC MODELS
# =====================================================================

class ManualApartmentInput(BaseModel):
    url: str = Field(..., min_length=8)
    title: str = Field(..., min_length=1)
    asuinalue: str = Field(..., min_length=1)
    price: float = Field(..., gt=0)
    size_m2: float = Field(..., gt=0)
    notes: str = ""
    status: str = "Interested"

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

        # Phase 3: Extract structured specs via regex & compile dossier
        specs_data = extract_specs_from_text(text)
        dossier = generate_dossier(
            price=price_val,
            size_m2=size_val,
            asuinalue=asuinalue.title(),
            raw_text=text,
            extracted_specs=specs_data
        )

        return {
            "url": url,
            "title": title,
            "asuinalue": asuinalue.title(),
            "price": price_val,
            "size_m2": size_val,
            "notes": "",
            "status": "Interested",
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

    # Retrieve votes from apartment_votes table if available (Phase 2)
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

        # Phase 3: Ensure structured dossier is present even on older records
        if not item.get("specs"):
            item["specs"] = generate_dossier(
                price=price,
                size_m2=size,
                asuinalue=area,
                raw_text=f"{item.get('title', '')} {item.get('notes', '')}"
            )

        grouped.setdefault(area, []).append(item)

    sort_key = sort_by if sort_by in ("price", "size_m2", "eur_per_m2") else "price"
    for area in grouped:
        grouped[area].sort(key=lambda x: x.get(sort_key, 0), reverse=desc)
    return grouped

@app.post("/apartments/manual")
@app.post("/api/apartments/manual")
def add_manual(payload: ManualApartmentInput, authorization: str = Header(None)):
    user = get_current_user(authorization)
    sb = get_supabase()

    # Phase 3: Generate heuristic dossier for manual entries
    dossier = generate_dossier(
        price=payload.price,
        size_m2=payload.size_m2,
        asuinalue=payload.asuinalue.strip().title(),
        raw_text=f"{payload.title} {payload.notes}"
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
        "specs": dossier
    }

    try:
        res = sb.table("apartments").upsert(data, on_conflict="url").execute()
    except Exception as exc:
        # Fallback if specs column is not yet provisioned in Supabase table
        if "specs" in str(exc).lower():
            fallback_data = {k: v for k, v in data.items() if k != "specs"}
            res = sb.table("apartments").upsert(fallback_data, on_conflict="url").execute()
        else:
            raise

    return {"status": "saved", "data": res.data}

@app.post("/apartments/scrape")
@app.post("/api/apartments/scrape")
def add_scraped(payload: ScrapeApartmentInput, authorization: str = Header(None)):
    user = get_current_user(authorization)
    try:
        extracted = scraper.extract(payload.url, payload.fallback_asuinalue)
        extracted["added_by"] = user["display_name"]
        sb = get_supabase()
        
        try:
            res = sb.table("apartments").upsert(extracted, on_conflict="url").execute()
        except Exception as exc:
            # Fallback if specs column is not yet provisioned in Supabase table
            if "specs" in str(exc).lower():
                fallback_data = {k: v for k, v in extracted.items() if k != "specs"}
                res = sb.table("apartments").upsert(fallback_data, on_conflict="url").execute()
            else:
                raise

        return {"status": "saved", "data": res.data, "asuinalue": extracted["asuinalue"]}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@app.post("/apartments/vote")
@app.post("/api/apartments/vote")
def cast_vote(payload: ApartmentVoteInput, authorization: str = Header(None)):
    user = get_current_user(authorization)
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
    get_current_user(authorization)
    sb = get_supabase()
    sb.table("apartments").delete().eq("id", apt_id).execute()
    try:
        sb.table("apartment_votes").delete().eq("apartment_id", apt_id).execute()
    except Exception:
        pass
    return {"deleted": apt_id}
