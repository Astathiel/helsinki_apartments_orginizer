import re
import sqlite3
from urllib.parse import urlsplit, urlunsplit
import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

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
    def validate_and_clean_url(cls, value: str) -> str:
        return normalize_url(value)

    @field_validator("title", "asuinalue")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Field cannot be empty or whitespace only.")
        return stripped

class ScrapeApartmentInput(BaseModel):
    url: str = Field(..., min_length=8)
    fallback_asuinalue: str = ""

    @field_validator("url")
    @classmethod
    def validate_and_clean_url(cls, value: str) -> str:
        return normalize_url(value)

class VuokraoviScraper:
    def __init__(self):
        self.headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    def extract(self, url: str, fallback_area: str = "") -> ManualApartmentInput:
        response = httpx.get(url, headers=self.headers, follow_redirects=True, timeout=10.0)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        raw_title = soup.title.string.strip() if soup.title and soup.title.string else ""
        title = raw_title.replace(" - Vuokraovi.com", "").strip() or "Vuokraovi Kohde"
        text = soup.get_text(" ", strip=True)
        area_match = re.search(r"kohteen:\s*([^,]+),\s*([^,]+),\s*Helsinki", text, re.IGNORECASE)
        asuinalue = fallback_area.strip() or (area_match.group(2).strip() if area_match else "")
        if not asuinalue:
            raise ValueError("Could not detect Asuinalue from page. Please type a Fallback Asuinalue.")
        price_match = re.search(r"(\d[\d\s\xa0]*(?:,\d+)?)\s*€\s*/\s*kk", text)
        price_str = re.sub(r"[\s\xa0]", "", price_match.group(1)).replace(",", ".") if price_match else "0"
        size_match = re.search(r"(\d+(?:,\d+)?)\s*m²", text)
        size_str = size_match.group(1).replace(",", ".") if size_match else "0"
        price_val = float(price_str)
        size_val = float(size_str)
        if price_val <= 0 or size_val <= 0:
            raise ValueError("Could not extract valid price or m² from link. Use Option A.")
        return ManualApartmentInput(
            url=url,
            title=title,
            asuinalue=asuinalue.title(),
            price=price_val,
            size_m2=size_val,
            notes="",
            status="Interested"
        )

class ApartmentRepository:
    def __init__(self, db_path: str = "apartments.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS apartments ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "url TEXT NOT NULL, "
                "title TEXT NOT NULL, "
                "asuinalue TEXT NOT NULL, "
                "price REAL NOT NULL CHECK(price > 0), "
                "size_m2 REAL NOT NULL CHECK(size_m2 > 0), "
                "notes TEXT DEFAULT '', "
                "status TEXT DEFAULT 'Interested')"
            )
            try:
                conn.execute("ALTER TABLE apartments ADD COLUMN notes TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE apartments ADD COLUMN status TEXT DEFAULT 'Interested'")
            except sqlite3.OperationalError:
                pass
            conn.execute(
                "DELETE FROM apartments WHERE price <= 0 OR size_m2 <= 0 "
                "OR TRIM(url) = '' OR TRIM(asuinalue) = ''"
            )
            conn.execute(
                "DELETE FROM apartments WHERE id NOT IN ("
                "SELECT MAX(id) FROM apartments GROUP BY url)"
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_apartments_url ON apartments(url)"
            )

    def add(self, item: ManualApartmentInput) -> dict:
        normalized_area = item.asuinalue.strip().title()
        with sqlite3.connect(self.db_path) as conn:
            existing = conn.execute(
                "SELECT id FROM apartments WHERE url = ?", (item.url,)
            ).fetchone()
            conn.execute(
                "INSERT INTO apartments (url, title, asuinalue, price, size_m2, notes, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(url) DO UPDATE SET "
                "title = excluded.title, "
                "asuinalue = excluded.asuinalue, "
                "price = excluded.price, "
                "size_m2 = excluded.size_m2, "
                "notes = excluded.notes, "
                "status = excluded.status",
                (item.url, item.title.strip(), normalized_area, item.price, item.size_m2, item.notes.strip(), item.status.strip())
            )
            row = conn.execute(
                "SELECT id FROM apartments WHERE url = ?", (item.url,)
            ).fetchone()
            status_flag = "updated" if existing else "created"
            return {"id": row[0], "asuinalue": normalized_area, "status": status_flag}

    def delete(self, apt_id: int) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM apartments WHERE id = ?", (apt_id,))

    def get_grouped(self, sort_by: str = "price", descending: bool = False) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM apartments ORDER BY asuinalue ASC").fetchall()
        grouped = {}
        for row in rows:
            item = dict(row)
            item["eur_per_m2"] = round(item["price"] / item["size_m2"], 2) if item["size_m2"] > 0 else 0.0
            area = item["asuinalue"]
            grouped.setdefault(area, []).append(item)
        sort_key = sort_by if sort_by in ("price", "size_m2", "eur_per_m2") else "price"
        for area in grouped:
            grouped[area].sort(key=lambda x: x[sort_key], reverse=descending)
        return grouped

app = FastAPI()
repo = ApartmentRepository()
scraper = VuokraoviScraper()

@app.get("/")
def serve_ui():
    return FileResponse("index.html")

@app.get("/api/apartments")
def list_apartments(sort_by: str = "price", desc: bool = False):
    return repo.get_grouped(sort_by=sort_by, descending=desc)

@app.post("/api/apartments/manual")
def add_manual(payload: ManualApartmentInput):
    return repo.add(payload)

@app.post("/api/apartments/scrape")
def add_scraped(payload: ScrapeApartmentInput):
    try:
        extracted = scraper.extract(payload.url, payload.fallback_asuinalue)
        return repo.add(extracted)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@app.delete("/api/apartments/{apt_id}")
def remove_apartment(apt_id: int):
    repo.delete(apt_id)
    return {"deleted": apt_id}