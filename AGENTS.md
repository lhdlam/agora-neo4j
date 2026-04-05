# AGENTS.md — Agora Project AI Rules

> This file is read by every AI agent working on this codebase.
> Follow all rules here **exactly**. Do not ask for clarification on items already specified here.

---

## 0. Code Navigation — Use Neo4j, Not File Scanning

**The entire `src/` codebase is pre-indexed in a Neo4j knowledge graph.**
Before opening any source file, query Neo4j first. Only open a file if you need to **write to it**.

### Neo4j connection
- **Bolt:** `bolt://localhost:7687` | **User:** `neo4j` | **Password:** `password`
- Use the **Neo4j MCP** (`mcp_neo4j_read-cypher`) for all read queries.

### Graph schema

| Node label | Key properties |
|------------|----------------|
| `Component` | `name` (FQN), `kind` (module/class/function/method), `layer`, `module`, `source_file`, `line_number`, `signature`, `docstring` |
| `Layer` | `name`, `description` |

| Relationship | Meaning |
|--------------|---------|
| `DEFINED_IN` | method/function → class/module |
| `BELONGS_TO_LAYER` | component → layer |
| `CALLS` | caller → callee (pyan3 call graph) |
| `IMPORTS` | module → module |
| `INHERITS` | class → base class |

### Essential Cypher queries (copy-paste ready)

**Look up a method/function signature and docstring:**
```cypher
MATCH (c:Component {name: "src.services.listing_service.ListingService.post"})
RETURN c.signature, c.docstring, c.source_file, c.line_number
```

**Find all methods of a class:**
```cypher
MATCH (m:Component)-[:DEFINED_IN]->(c:Component {name: "src.services.listing_service.ListingService"})
RETURN m.name, m.signature, m.docstring
ORDER BY m.line_number
```

**Find what a method calls:**
```cypher
MATCH (caller:Component {name: "src.services.listing_service.ListingService.post"})-[:CALLS]->(callee)
RETURN callee.name, callee.kind, callee.layer
```

**Find all components in a layer:**
```cypher
MATCH (c:Component)-[:BELONGS_TO_LAYER]->(l:Layer {name: "services"})
WHERE c.kind IN ["class", "function"]
RETURN c.name, c.kind, c.docstring
ORDER BY c.name
```

**Find which classes implement a Port:**
```cypher
MATCH (impl:Component)-[:INHERITS]->(port:Component)
WHERE port.name CONTAINS "Port"
RETURN impl.name AS implementor, port.name AS port
```

**Find callers of a method (reverse CALLS):**
```cypher
MATCH (caller)-[:CALLS]->(target:Component {name: "src.infrastructure.es_client.ESClient.index_doc"})
RETURN caller.name, caller.layer
```

**Fuzzy name search:**
```cypher
MATCH (c:Component)
WHERE c.name CONTAINS "listing_service"
RETURN c.name, c.kind, c.signature
ORDER BY c.kind
```

### When to open a source file
Only open a file when you are about to **write or edit** it. Never open files to gather information — that's what Neo4j is for.

---

## 1. Project Snapshot

| Item | Value |
|------|-------|
| **Name** | Agora — AI-powered classified ads service |
| **Language** | Python 3.13+ |
| **Entry point** | `agora` CLI → `src/cli.py` |
| **Package** | `agora-market` (installed via `pip install -e ".[dev]"`) |
| **Python env** | `.venv/` in project root |

### Architecture layers (top-down)

```
commands  →  services  →  infrastructure  →  domain
                  ↑               ↑
                ports          (satisfies ports)
```

No layer may import from a layer above it.

---

## 2. Tech Stack (do not change without discussion)

| Component | Library / Version |
|-----------|-------------------|
| Validation | `pydantic>=2.12.5` |
| Settings | `pydantic-settings>=2.13.1` |
| CLI | `click>=8.3.1` |
| Output | `rich>=14.3.3` |
| Search | `elasticsearch==8.13.0` |
| Embedding | `fastembed==0.8.0` (ONNX, no PyTorch) |
| Embedding model | `sentence-transformers/paraphrase-multilingual-mpnet-base-v2` (768-dim) |
| Events | `kafka-python-ng>=2.2.3` (`KAFKA_ENABLED=false` by default) |
| Linter | `ruff>=0.9.0` |
| Types | `mypy>=1.15.0` (strict) |
| Tests | `pytest>=8.0.0` + `pytest-cov>=6.0.0` |
| Code graph | `neo4j` + `pyan3` (see `src/neo4j_graph.py`) |

---

## 3. Code Quality — Non-negotiable Rules

### 3.1 Type annotations
- Every function/method **must** have full type annotations (mypy strict).
- Use `from __future__ import annotations` at the top of every file.
- No bare `Any` — use specific types or `TypeVar`/`Generic` where possible.
- Exception: `tests/**` — no annotations required.

### 3.2 Linting (ruff)
- Target: zero ruff warnings on `src/` and `tests/`.
- Enabled rule sets: `E, W, F, I, B, C4, UP, SIM, PTH, ANN, RET, TRY, LOG, G, PIE, T20`.
- No `print()` in `src/` — use `logging.getLogger(__name__)` or `rich.Console`.
- No bare `except:` — always catch specific exceptions.

### 3.3 Style
- Line length: **100 characters**.
- Quote style: **double quotes**.
- Imports: isort order (stdlib → third-party → first-party `src`).
- Use `pathlib.Path` instead of `os.path`.

### 3.4 Testing
- Tests live in `src/tests/`.
- Minimum coverage: **98%** on `src/`.
- Test files: `test_*.py`; classes: `Test*`; functions: `test_*`.
- Use `pytest.raises`, `unittest.mock.patch`, or `MagicMock` — no third-party mocking libs.

---

## 4. Domain Rules

### Listing model invariants
- `type` ∈ `{sell, buy}` — never mix logic for the two types.
- `seller_info` only for `type=sell`; `buyer_info` only for `type=buy`.
- `embedding` is generated **by the infrastructure layer** before indexing — never set manually in commands or services.
- `status` defaults to `active`; only the service layer changes it.

### Elasticsearch index
- Index name: `ES_INDEX` from settings (default `listings`).
- Embedding field: `dense_vector`, 768 dims, cosine similarity.
- Always go through `ESClient` singleton — never instantiate `Elasticsearch` directly.

### Matching thresholds (from `settings`)
```
MATCH_MIN_COSINE_SCORE    = 0.65
MATCH_BONUS_SAME_CATEGORY = 0.07
MATCH_BONUS_SAME_CITY     = 0.03
```

---

## 5. Workflow Rules

### Before writing any code
1. **Query Neo4j** to understand the components you need to touch (see Section 0).
2. Read the relevant skill file in `.agent/skills/` for copy-paste patterns.
3. Follow the layered architecture — no upward imports.

### Dependency Injection pattern
- Services receive ports via constructor (`__init__(self, store, embedder, event_bus)`).
- **Production wiring:** use `make_<svc>_service()` from `src/services/factories.py` in command modules.
- **Tests:** inject fakes (`FakeStore`, `FakeEmbedder`, `FakeEventBus`) directly into the service constructor.
- **Never** call `get_es_client()` / `get_embedder()` inside service or command code — only in `factories.py`.

### Adding a new feature (standard pattern)
```
1. Query Neo4j to understand affected components
2. Read the relevant skill file in .agent/skills/
3. Add/extend model in src/domain/ (if needed)
4. Add Port in src/ports/ (if adding new infra capability)
5. Add setting in src/config.py (if needed)
6. Add infrastructure adapter method (if needed)
7. Add/extend service in src/services/ with constructor DI
8. Add factory in src/services/factories.py
9. Create src/commands/<cmd>.py using factory
10. Register in src/commands/__init__.py → register()
11. Add tests in src/tests/ using FakeStore/FakeEmbedder pattern
12. Run: make check  (must pass fully)
13. Re-run `neo4j-graph` to keep the graph in sync
```

### Makefile targets (use these, do not invent manual commands)
```bash
make install        # pip install -e ".[dev]" + pre-commit hooks
make lint           # ruff check (read-only)
make lint fix=1     # ruff check --fix
make format         # ruff format
make format check=1 # ruff format --check (CI)
make mypy           # mypy strict on src/
make test cov=1     # pytest + coverage
make test           # pytest no coverage
make check          # format check=1 + lint + mypy + test (full CI)
make clean          # remove caches
```

---

## 6. Infrastructure Rules

### Elasticsearch
- Dev stack: `infrastructure/docker-compose.yml` (`docker-compose up -d`).
- Default URL: `http://localhost:9200`, auth: `ELASTIC_PASSWORD=changeme`.
- **Never hard-code** host/port — always read from `settings`.

### Kafka
- Publish events **after** successful ES indexing.
- Do not let Kafka failures block the happy path (log and continue).

### Embedder
- Use `get_embedder()` singleton — never instantiate `TextEmbedder` directly in services.
- Embedding is synchronous; downloads model on first call (~600 MB).

---

## 7. Environment & Configuration

Copy `.env.example` → `.env` before running.

---

## 8. What NOT to do

- ❌ Do not open source files to gather information — query Neo4j instead.
- ❌ Do not use `print()` in `src/` — use `logging.getLogger(__name__)` or `rich.Console`.
- ❌ Do not import from a higher layer (e.g., `infrastructure` importing from `commands`).
- ❌ Do not instantiate `Elasticsearch` or `TextEmbedder` directly in service/command code.
- ❌ Do not call `get_es_client()` or `get_embedder()` inside services — use constructor-injected ports.
- ❌ Do not hardcode secrets, hostnames, or thresholds — put them in `Settings`.
- ❌ Do not skip type annotations on production code.
- ❌ Do not add `# noqa` or `# type: ignore` without a comment explaining why.
- ❌ Do not change `EMBEDDING_DIMS` without updating the ES index mapping.
- ❌ Do not mix SELL-only and BUY-only attributes in the shared `Listing` model body.
- ❌ Do not call `listing.to_es_doc()` — method removed; use `listing_to_es_doc(listing)` from `src.infrastructure.serializers`.
- ❌ Do not patch `src.commands.commands.ListingService` in tests — patch the specific command module (e.g., `src.commands.post.make_listing_service`).

---

## 9. Skills available for this project

| Skill | File | When to use |
|-------|------|-------------|
| Add a new field to Listing | `.agent/skills/add_listing_field.md` | Adding model attributes |
| Add a new CLI command | `.agent/skills/add_cli_command.md` | New `agora <cmd>` subcommands |
| Add/fix tests | `.agent/skills/write_tests.md` | Writing or fixing pytest tests |
| Add infrastructure method | `.agent/skills/add_infra_method.md` | New ES, embedder, or Kafka operations |
| Debug a failing check | `.agent/skills/debug_check.md` | When `make check` fails |

---

*Last updated: 2026-04-05 — Replaced file-scan navigation with Neo4j MCP as primary code discovery tool.*
