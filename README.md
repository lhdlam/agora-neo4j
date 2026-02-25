<div align="center">

# Agora

**AI-powered classified ads agora service**

Hybrid Search · Semantic Matching · kNN Vector · BM25 · CLI-first

[![Python](https://img.shields.io/badge/Python-3.13%2B-3776ab?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Ruff](https://img.shields.io/badge/Linter-Ruff-ff7b00?style=flat-square)](https://docs.astral.sh/ruff)
[![Mypy](https://img.shields.io/badge/Types-Mypy%20strict-1f5c99?style=flat-square)](https://mypy.readthedocs.io)
[![Elasticsearch](https://img.shields.io/badge/Elasticsearch-8.x-005571?style=flat-square&logo=elasticsearch)](https://www.elastic.co)

</div>

---

## Overview

Agora is a command-line tool for posting, searching, and agora classified ads using AI-powered hybrid search. It combines traditional BM25 full-text search with kNN semantic vector search to surface the most relevant sell listings for any given buy request.

**Key capabilities:**

| Feature | Details |
|---------|---------|
| Semantic Matching | Text embedding via `fastembed` (ONNX runtime — no PyTorch required) |
| Hybrid Search | BM25 keyword + kNN vector combined in a single Elasticsearch query |
| Geo-radius Filtering | Search within a configurable radius from GPS coordinates |
| Event Bus | Optional Kafka integration (`KAFKA_ENABLED=false` by default) |
| Type Safety | Strict Mypy — zero errors on all production code |
| Input Validation | Email and phone format validation via Pydantic v2 |
| Monitoring | Prometheus metrics + Grafana dashboards included |

---

## Requirements

```
Python 3.13+          — runtime
Docker & Compose      — infrastructure (Elasticsearch, Kafka, Prometheus, Grafana)
~2 GB RAM             — Elasticsearch
~600 MB disk          — AI embedding model (downloaded on first run)
```

---

## Getting Started

### 1. Configure environment variables

```bash
cp .env.example .env
# Edit .env as needed (ES host, Kafka, model, credentials...)
```

### 2. Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
```

### 3. Install dependencies

```bash
make install
# Equivalent to: pip install -e ".[dev]" && pre-commit install
```

### 4. Pre-load AI Model (Recommended)

Agora uses an AI model (~600 MB) downloaded automatically on the first run. To ensure it is preserved across restarts (e.g., when running `docker compose down -v`), create an external volume and pre-load the model before starting the system:

```bash
# Build the worker image
make docker build # opts="--no-cache" to not use cache

# Create the external volume and pre-load the model
make docker ai-model-volume
```

### 5. Start the infrastructure

```bash
make docker up
```

### 6. Quick smoke test

```bash
# Import sample listings
agora import --file data/sample_listings.json

# Keyword search
agora search "iphone"

# Semantic search — no exact keyword required
agora search "Apple flagship smartphone"
# -> Still finds iPhone listings via vector similarity

# BUY -> SELL matching
agora match --query "need a high-performance gaming laptop" --budget 40000000
```

---

## CLI Reference

### `post sell` — Publish a sell listing

```bash
agora post sell \
  --title       "iPhone 14 Pro 256GB Deep Purple" \
  --description "Like new, 6 months warranty remaining" \
  --price       25000000 \
  --currency    VND \
  --category    dien-tu \
  --location    "Hanoi" \
  --city        "Hanoi" \
  --lat 21.0285 --lon 105.8542 \
  --tags        iphone,apple,smartphone \
  --brand       Apple \
  --model       "iPhone 14 Pro" \
  --storage     256GB \
  --condition   like-new \
  --warranty    6 \
  --negotiable \
  --contact-name  "An Nguyen" \
  --contact-phone "0901234567"
```

### `post buy` — Publish a buy request (wanted)

```bash
agora post buy \
  --title       "Looking for iPhone 14 Pro" \
  --description "Urgently needed, prefer remaining warranty" \
  --budget-max  27000000 \
  --currency    VND \
  --category    dien-tu \
  --city        "Hanoi" \
  --lat 21.0285 --lon 105.8542 \
  --desired-brand Apple \
  --desired-model "iPhone 14 Pro" \
  --urgency     asap \
  --contact-phone "0912345678"
```

### `import` — Batch import from file

```bash
# JSON (array or single object)
agora import --file data/sample_listings.json

# CSV
agora import --file data/listings.csv --format csv
```

### `search` — Hybrid search (BM25 + kNN)

```bash
# Basic search
agora search "iphone 14"

# Filter by price and listing type
agora search "iphone 14" --type sell --max-price 30000000

# Filter by category and geo-radius
agora search "honda sh" \
  --category xe-may \
  --lat 21.0285 --lon 105.8542 --radius 10km \
  --limit 20
```

### `match` — Match BUY requests to SELL listings

```bash
# Free-text query
agora match \
  --query  "looking for iphone 14 pro" \
  --budget 26000000 \
  --top    10

# From an existing BUY listing in Elasticsearch
agora match --buy-id <uuid>

# With geo-radius constraint
agora match \
  --query  "need a good Honda scooter" \
  --budget 40000000 \
  --lat 21.0285 --lon 105.8542 --radius 15km
```

### `delete` — Remove a listing

```bash
agora delete --id <uuid>
```

### Global flags

```bash
agora --help              # list all commands
agora --version           # print current version
agora --debug <command>   # enable full stack traces
```

---

## Development

```bash
make help          # list all available targets

# ── Infrastructure ──
make docker up            # start all services (ES + Kibana + Kafka + Prometheus + Grafana)
make docker down          # stop all services
make docker purge         # stop all services and remove all data volumes
make docker logs          # tail logs from all containers
make docker build         # build all images (opts="--no-cache" to not use cache)
make docker restart       # restart all services (svc: worker, kafka, es, kibana, prometheus, grafana)

# ── Python ──
make install       # pip install -e ".[dev]" + register pre-commit hooks
make uninstall     # remove all packages from .venv + deregister hooks

make lint          # ruff check (read-only)
make lint fix=1    # ruff check --fix
make format        # ruff format
make format check=1  # check formatting without modifying files (CI mode)

make mypy          # mypy strict on src/
make test cov=1    # pytest + coverage report
make test          # pytest without coverage

make check         # format check=1 + lint + mypy + test  (CI pipeline)
make clean         # remove __pycache__, .mypy_cache, .ruff_cache, .pytest_cache
```

Pre-commit hooks run `ruff lint → ruff format → mypy` automatically before every commit.

---

**Request flow:**

```
CLI input
  └─> commands/*   (argument parsing + validation)
        └─> services/*   (business logic)
              └─> infrastructure/*   (Elasticsearch · embedder · Kafka)
```

**Elasticsearch index — `listings`:**

```
dense_vector(768, cosine)   — kNN semantic search
text (title, description)   — BM25 full-text search
geo_point (geo_location)    — geo-radius filter
keyword / numeric           — exact filters (status, type, price, category...)
nested (contact)            — contact information
```

---

## Infrastructure Services

| Service | Compose file | URL | Description |
|---------|-------------|-----|-------------|
| Elasticsearch | `docker-compose.elasticsearch.yml` | http://localhost:9200 | Primary store + kNN index |
| Kibana | `docker-compose.elasticsearch.yml` | http://localhost:5601 | Elasticsearch visualization |
| Kafka | `docker-compose.kafka.yml` | localhost:9092 | Event bus (KRaft mode, optional) |
| Prometheus | `docker-compose.monitoring.yml` | http://localhost:9090 | Metrics collection |
| Grafana | `docker-compose.monitoring.yml` | http://localhost:3000 | Dashboards |
| ES Exporter | `docker-compose.monitoring.yml` | http://localhost:9114 | ES metrics → Prometheus |

Default dev credentials: `ELASTIC_PASSWORD=changeme` · `GRAFANA_USER=admin` · `GRAFANA_PASSWORD=admin`
Override in `.env` before starting the stack.

---

## Categories

| Value | Description |
|-------|-------------|
| `dien-tu` | Electronics — phones, laptops, computers |
| `xe-may` | Motorbikes, electric bikes |
| `oto` | Cars |
| `nha-dat` | Real estate |
| `do-go-noi-that` | Furniture |
| `thoi-trang` | Fashion and apparel |
| `the-thao` | Sports equipment |
| `sach` | Books |
| `thuc-pham` | Food |
| `khac` | Other |

---

## Configuration Reference

```dotenv
# Elasticsearch
ES_HOST=localhost
ES_PORT=9200
ES_SCHEME=http          # "https" for production / Elastic Cloud
ES_INDEX=listings
ES_USER=elastic         # required by ES 8.x
ES_PASSWORD=changeme    # override via ECS secrets in production

# Embedding model
EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-mpnet-base-v2
EMBEDDING_DIMS=768        # must match the model output and ES mapping

# Kafka (disabled by default)
KAFKA_ENABLED=false
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
KAFKA_TOPIC_LISTING=listing.events

# Matching
MATCH_TOP_K=10
MATCH_NUM_CANDIDATES=50

# Infrastructure credentials (dev defaults — change in production)
ELASTIC_PASSWORD=changeme   # docker-compose only
GRAFANA_USER=admin
GRAFANA_PASSWORD=admin
```

---

## Testing

```bash
make test cov=1    # pytest with coverage
make test          # pytest without coverage
```

Test coverage spans `domain/` (embed_text, models) and `services/` (listing_service, search_service, match_service).

---

<div align="center">

Built with **Python 3.13** · **Elasticsearch 8** · **fastembed** · **Pydantic v2** · **Click** · **Rich**

</div>
