## 2024-11-04 - Unvalidated URL Extraction in VuokraoviScraper
**Vulnerability:** Server-Side Request Forgery (SSRF) allowed the API to fetch data from arbitrary domains because the `url` parameter was not checked against an allowlist before `httpx.get` execution.
**Learning:** Even though the function expects a Vuokraovi URL (as implied by the `ScrapeApartmentInput` validation which simply checked for a valid URL but no domain), attackers could supply malicious URLs leading to SSRF.
**Prevention:** Implement explicit domain validation (`parsed_url.netloc in ["www.vuokraovi.com", "vuokraovi.com"]`) directly before outbound HTTP requests.
