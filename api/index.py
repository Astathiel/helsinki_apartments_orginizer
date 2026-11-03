import os
import re
from urllib.parse import urlsplit, urlunsplit
import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Header
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
        if SUPABASE_JWT_SECRET:
            payload = jwt.decode(token, SUPABASE_JWT_SECRET, algorithms=["HS256"], audience="authenticated")
        else:
            payload = jwt.decode(token, options={"verify_signature": False})
        meta = payload.get("user_metadata", {})
        display_name = meta.get("display_name") or payload.get("email", "").split("@")[0].capitalize() or "Leo"
        return {"id": payload.get("sub"), "email": payload.get("email"), "display_name": display_name}
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Invalid session token: {str(exc)}")

def normalize_url(raw_url: str) -> str:
    cleaned = raw_url.strip()
    if not cleaned:
        raise ValueError("URL cannot be empty.")
    parts = urlsplit(cleaned)
    if not parts.scheme or not parts.netloc:
        raise ValueError("URL must start with http:// or https://")
    clean_path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), clean_path, "", ""))

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

@app.get("/apartments")
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

@app.post("/apartments/manual")
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

@app.post("/apartments/scrape")
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

@app.delete("/apartments/{apt_id}")
@app.delete("/api/apartments/{apt_id}")
def remove_apartment(apt_id: int, authorization: str = Header(None)):
    get_current_user(authorization)
    sb = get_supabase()
    sb.table("apartments").delete().eq("id", apt_id).execute()
    return {"deleted": apt_id}