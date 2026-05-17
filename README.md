# HTTP Metadata Inventory Service

A production-grade FastAPI service that collects and stores HTTP headers, cookies, and page source for any given URL. Supports synchronous collection (POST) and asynchronous background collection with immediate acknowledgement (GET).

---

## Quick Start

```bash
# 1. Clone the repository
git clone <your-repo-url>
cd http-metadata-inventory

# 2. Copy environment config
cp .env.example .env

# 3. Start the service (API + MongoDB)
docker-compose up --build
```

The API is now running at **http://localhost:8000**
Interactive docs (Swagger UI) at **http://localhost:8000/docs**

---

## API Reference

### `POST /api/v1/metadata`

Fetches and stores metadata for a URL **synchronously**. Always performs a fresh fetch; existing records are overwritten.

**Request body:**
```json
{ "url": "https://example.com" }
```

**Success response — `200 OK`:**
```json
{
  "url": "https://example.com",
  "status": "complete",
  "headers": { "content-type": "text/html", "server": "nginx" },
  "cookies": { "session": "abc123" },
  "page_source": "<html>...</html>",
  "fetched_at": "2025-01-01T12:00:00Z",
  "created_at": "2025-01-01T12:00:00Z"
}
```

| Status | Meaning |
|--------|---------|
| `200` | Metadata collected and stored |
| `422` | URL missing or malformed |
| `502` | Target URL unreachable or returned an error |

---

### `GET /api/v1/metadata?url=<url>`

Retrieves metadata for a URL. If not yet fetched, queues a background fetch and returns immediately.

**Cache hit — `200 OK`:**
```json
{
  "url": "https://example.com",
  "status": "complete",
  "headers": { ... },
  "cookies": { ... },
  "page_source": "<html>...</html>",
  "fetched_at": "2025-01-01T12:00:00Z",
  "created_at": "2025-01-01T12:00:00Z"
}
```

**Cache miss — `202 Accepted`:**
```json
{
  "message": "Metadata not yet available. A background fetch has been queued. Retry this request in a few seconds.",
  "url": "https://example.com",
  "status": "pending"
}
```

| Status | Meaning |
|--------|---------|
| `200` | Record found and returned |
| `202` | Cache miss; background fetch queued — retry shortly |
| `422` | URL missing or malformed |

---

### `GET /health`

```json
{ "status": "ok", "service": "metadata-inventory" }
```

---

## Running Tests

```bash
# Inside the running container
docker-compose exec api pytest

# With coverage report
docker-compose exec api pytest --cov=app --cov-report=term-missing

# Unit tests only (no services needed)
docker-compose exec api pytest tests/unit/ -v

# Integration tests (API layer)
docker-compose exec api pytest tests/integration/ -v
```

Or locally (with a virtual environment):
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest
```

---

## Architecture

```
Client
  │
  ├── POST /api/v1/metadata ──► MetadataService.create()
  │                                   │
  │                             HTTPFetcher.fetch()   ← httpx.AsyncClient
  │                                   │
  │                             MongoRepository.upsert()   ← Motor
  │                                   │
  │                             ◄── 200 OK (full record)
  │
  └── GET /api/v1/metadata
        │
        ├── Cache HIT ──► MongoRepository.find() ──► 200 OK
        │
        └── Cache MISS
              │
              ├── MongoRepository.upsert({status: pending})
              ├── asyncio.create_task(fetch_and_store)   ← fire-and-forget
              └── ◄── 202 Accepted (immediate)
```

### Key design decisions

**`asyncio.create_task` for background work (not `BackgroundTasks`)**

FastAPI's `BackgroundTasks` run after the response but remain coupled to the request lifecycle via Starlette middleware. `asyncio.create_task()` schedules a coroutine directly on the event loop — completely decoupled from the HTTP request that spawned it. The endpoint returns the moment `create_task` is called.

**Motor async MongoDB driver (not PyMongo)**

PyMongo is synchronous. Calling it from an `async` FastAPI handler blocks the entire event loop, serialising all concurrent requests. Motor is the async-native wrapper that returns coroutines and integrates cleanly with asyncio.

**SHA-256 URL hash as the lookup key**

Every URL is hashed to a 64-character hex string on write, with a unique index in MongoDB. This gives O(1) lookups without string-scanning the collection and prevents duplicate records without race conditions on upsert.

**Shared httpx.AsyncClient (lifespan)**

A single `httpx.AsyncClient` is created at startup and shared via `app.state`. Creating a new client per request would exhaust OS connection pools under load. The shared client maintains a connection pool across all outbound requests.

**Document status state machine**

```
pending  →  complete   (background fetch succeeded)
pending  →  failed     (background fetch errored)
```

This means a GET for a pending URL always gets an honest response and can retry until status becomes `complete`.

### Project layout

```
app/
├── api/v1/metadata.py       # HTTP transport — routes only, no logic
├── services/
│   └── metadata_service.py  # Business logic — orchestrates fetch + store
├── workers/
│   └── background_worker.py # asyncio.create_task dispatcher
├── infrastructure/
│   ├── http_fetcher.py      # httpx wrapper — outbound HTTP
│   └── mongo_repository.py  # Motor wrapper — database I/O
├── models/
│   ├── domain.py            # MetadataRecord — canonical data model
│   └── schemas.py           # API request/response schemas
├── core/
│   ├── config.py            # pydantic-settings — typed env vars
│   └── dependencies.py      # FastAPI dependency injection wiring
└── main.py                  # App factory + lifespan
```

### Extending to a distributed architecture

The `BackgroundWorker` abstraction is the single seam for future distributed work. To migrate from asyncio tasks to a Celery + Redis queue:

1. Replace `BackgroundWorker.dispatch()` to push a job onto a Celery queue
2. Add a `celery_worker` service to `docker-compose.yml`
3. No changes needed in the service layer, router, or repository

The repository, service, and API layers are unaffected — separation of concerns makes this a one-file change.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `MONGO_URI` | `mongodb://mongo:27017` | MongoDB connection string |
| `MONGO_DB_NAME` | `metadata_inventory` | Database name |
| `MONGO_COLLECTION_NAME` | `metadata` | Collection name |
| `HTTP_TIMEOUT_SECONDS` | `15.0` | Outbound HTTP request timeout |
| `HTTP_MAX_RETRIES` | `2` | Max retry attempts on failure |
| `APP_ENV` | `development` | Environment tag |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

---

## Tech Stack

| Component | Technology | Reason |
|---|---|---|
| Language | Python 3.11 | Required |
| Framework | FastAPI | Required |
| Database | MongoDB 7 via Motor | Async-native driver |
| HTTP client | httpx.AsyncClient | Non-blocking, shared session |
| Config | pydantic-settings | Type-safe, `.env` support |
| Background work | asyncio.create_task | True fire-and-forget, no self-HTTP |
| Containerisation | Docker Compose | Required |
| Testing | pytest + pytest-asyncio | Required |
