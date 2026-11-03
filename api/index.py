import os
import re
import hashlib
import hmac
from urllib.parse import urlsplit, urlunsplit
import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, Field, field_validator
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
APP_SECRET = os.environ.get("APP_SECRET", "helsinki-apartment-token-secret-key-2026")

USERS_DB = {
    "leo_admin": {
        "display_name": "Leo",
        "role": "Owner",
        "salt": "d981a4b14d3f572e811c7fa156bc29aa",
        "hash": "b2f02f928e3b1c678a6ffb9c7b94ad3526ae77fa9db41b90f423377dc76c48e8"
    },
    "ella_hel": {
        "display_name": "Ella",
        "role": "Member",
        "salt": "a4f5c9e10283bd78394e0192a8b372ef",
        "hash": "8cb635ef84bce18d960f76cf6b1cce8aef7ec6d426466f8510864380eb92f69e"
    }
}

def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000).hex()

def verify_user(username: str, password: str) -> dict:
    user = USERS_DB.get(username.strip().lower())
    if not user:
        return None
    computed_hash = hash_password(password, user["salt"])
    if hmac.compare_digest(computed_hash, user["hash"]):
        return {"username": username.strip().lower(), "display_name": user["display_name"], "role": user["role"]}
    return None

def create_auth_token(username: str, display_name: str) -> str:
    data = f"{username}:{display_name}"
    signature = hmac.new(APP_SECRET.encode("utf-8"), data.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{data}:{signature}"

def verify_token(token: str) -> dict:
    if not token:
        raise HTTPException(status_code=401, detail="Missing authorization token.")
    parts = token.split(":")
    if len(parts) != 3:
        raise HTTPException(status_code=401, detail="Malformed authorization token.")
    username, display_name, signature = parts
    expected_sig = hmac.new(APP_SECRET.encode("utf-8"), f"{username}:{display_name}".encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected_sig):
        raise HTTPException(status_code=401, detail="Invalid token signature.")
    return {"username": username, "display_name": display_name}

def get_current_user(authorization: str = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Bearer token.")
    raw_token = authorization.replace("Bearer ", "").strip()
    return verify_token(raw_token)

def get_supabase() -> Client:
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("Missing Supabase credentials in environment variables.")
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

def normalize_url(raw_url: str) -> str:
    cleaned = raw_url.strip()
    if not cleaned:
        raise ValueError("URL cannot be empty.")
    parts = urlsplit(cleaned)
    if not parts.scheme or not parts.netloc:
        raise ValueError("URL must start with http:// or https://")
    clean_path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), clean_path, "", ""))

class LoginPayload(BaseModel):
    username: str
    password: str

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

class VuokraoviScraper:
    def __init__(self):
        self.headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    def extract(self, url: str, fallback_area: str = "") -> dict:
        response = httpx.get(url, headers=self.headers, follow_redirects=True, timeout=10.0)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        raw_title = soup.title.string.strip() if soup.title and soup.title.string else ""
        title = raw_title.replace(" - Vuokraovi.com", "").strip() or "Vuokraovi Kohde"
        text = soup.get_text(" ", strip=True)
        area_match = re.search(r"kohteen:\s*([^,]+),\s*([^,]+),\s*Helsinki", text, re.IGNORECASE)
        asuinalue = fallback_area.strip() or (area_match.group(2).strip() if area_match else "")
        if not asuinalue:
            raise ValueError("Could not detect Asuinalue from listing. Please provide a Fallback Asuinalue.")
        price_match = re.search(r"(\d[\d\s\xa0]*(?:,\d+)?)\s*€\s*/\s*kk", text)
        price_str = re.sub(r"[\s\xa0]", "", price_match.group(1)).replace(",", ".") if price_match else "0"
        size_match = re.search(r"(\d+(?:,\d+)?)\s*m²", text)
        size_str = size_match.group(1).replace(",", ".") if size_match else "0"
        price_val = float(price_str)
        size_val = float(size_str)
        if price_val <= 0 or size_val <= 0:
            raise ValueError("Could not extract valid price or m² from link. Please use manual entry.")
        return {
            "url": url,
            "title": title,
            "asuinalue": asuinalue.title(),
            "price": price_val,
            "size_m2": size_val,
            "notes": "",
            "status": "Interested"
        }

app = FastAPI()
scraper = VuokraoviScraper()

@app.post("/api/auth/login")
def login(payload: LoginPayload):
    user = verify_user(payload.username, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    token = create_auth_token(user["username"], user["display_name"])
    return {
        "token": token,
        "user": user,
        "supabase_url": SUPABASE_URL,
        "supabase_anon_key": os.environ.get("SUPABASE_ANON_KEY", "")
    }

@app.get("/api/auth/me")
def get_me(authorization: str = Header(None)):
    user = get_current_user(authorization)
    return {
        "user": user,
        "supabase_url": SUPABASE_URL,
        "supabase_anon_key": os.environ.get("SUPABASE_ANON_KEY", "")
    }

@app.get("/api/apartments")
def list_apartments(sort_by: str = "price", desc: bool = False, authorization: str = Header(None)):
    get_current_user(authorization)
    sb = get_supabase()
    res = sb.table("apartments").select("*").order("asuinalue", desc=False).execute()
    rows = res.data or []
    grouped = {}
    for item in rows:
        price = float(item.get("price", 0))
        size = float(item.get("size_m2", 0))
        item["eur_per_m2"] = round(price / size, 2) if size > 0 else 0.0
        area = item.get("asuinalue", "Tuntematon")
        if not item.get("added_by"):
            item["added_by"] = "Leo"
        grouped.setdefault(area, []).append(item)
    sort_key = sort_by if sort_by in ("price", "size_m2", "eur_per_m2") else "price"
    for area in grouped:
        grouped[area].sort(key=lambda x: x.get(sort_key, 0), reverse=desc)
    return grouped

@app.post("/api/apartments/manual")
def add_manual(payload: ManualApartmentInput, authorization: str = Header(None)):
    user = get_current_user(authorization)
    sb = get_supabase()
    data = {
        "url": payload.url,
        "title": payload.title.strip(),
        "asuinalue": payload.asuinalue.strip().title(),
        "price": payload.price,
        "size_m2": payload.size_m2,
        "notes": payload.notes.strip(),
        "status": payload.status.strip(),
        "added_by": user["display_name"]
    }
    res = sb.table("apartments").upsert(data, on_conflict="url").execute()
    return {"status": "saved", "data": res.data}

@app.post("/api/apartments/scrape")
def add_scraped(payload: ScrapeApartmentInput, authorization: str = Header(None)):
    user = get_current_user(authorization)
    try:
        extracted = scraper.extract(payload.url, payload.fallback_asuinalue)
        extracted["added_by"] = user["display_name"]
        sb = get_supabase()
        res = sb.table("apartments").upsert(extracted, on_conflict="url").execute()
        return {"status": "saved", "data": res.data, "asuinalue": extracted["asuinalue"]}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@app.delete("/api/apartments/{apt_id}")
def remove_apartment(apt_id: int, authorization: str = Header(None)):
    get_current_user(authorization)
    sb = get_supabase()
    sb.table("apartments").delete().eq("id", apt_id).execute()
    return {"deleted": apt_id}