## 2024-05-19 - [Server-Side Request Forgery Mitigation]
**Vulnerability:** Server-Side Request Forgery (SSRF) allowed the server to fetch arbitrary URLs on behalf of users in `ScrapeApartmentInput`.
**Learning:** Pydantic validators on URL fields were previously missing strict domain restrictions, allowing the `httpx.get()` in the scraper to fetch from any external (or internal) domain.
**Prevention:** Use `urllib.parse.urlsplit` to strictly validate `netloc.lower()` against explicitly allowed target domains ("vuokraovi.com", "www.vuokraovi.com") before processing requests to prevent unconstrained server-side fetching.
