## 2024-05-23 - Backend Supabase Client Re-instantiation
**Learning:** The FastAPI backend was re-instantiating the Supabase client (`create_client()`) on every single function call (often multiple times per request). This destroyed connection pooling (forcing new TLS handshakes) and added ~32ms of CPU overhead per request.
**Action:** Always memoize/cache Supabase (and other HTTP-based) clients globally or via `@lru_cache` in stateless web frameworks like FastAPI to preserve HTTP connection pooling.
