---
name: add_listing_field
description: >
  Add a new attribute to the Listing (or sub-models SellerInfo / BuyerInfo / Contact)
  and propagate the change through the ES mapping, indexer, service, and tests.
  Use this skill whenever a task involves extending the data model.
---

# Skill: Add a New Field to Listing

## When to use
- Adding a new attribute to `Listing`, `SellerInfo`, `BuyerInfo`, `Contact`, or `GeoLocation`.
- Adding a new enum value to `Category`, `Condition`, `Urgency`, `ContactMethod`, or `ListingStatus`.

## Quick Decision Tree
- Field chỉ cho SELL? → thêm vào `SellerInfo`
- Field chỉ cho BUY? → thêm vào `BuyerInfo`
- Field cho cả hai types? → thêm vào `Listing` body
- Cần ES mapping? → LUÔN cần (trừ khi field bị exclude khỏi doc)
- Cần custom serializer? → CHỄ khi format khác `model_dump()` mặc định (xem ví dụ `geo_location`)

## Step-by-step

> Before starting, query Neo4j to understand the current model structure:
> ```cypher
> MATCH (m:Component)-[:DEFINED_IN]->(c:Component {name: "src.domain.models.Listing"})
> RETURN m.name, m.signature, m.docstring ORDER BY m.line_number
> ```

### Step 1 — Add the field to the Pydantic model

File: `src/domain/models.py`

```python
# inside SellerInfo (for sell-only fields):
new_field: FieldType | None = None   # or with default

# inside BuyerInfo (for buy-only fields):
new_field: FieldType | None = None

# inside Listing (for shared fields):
new_field: FieldType | None = None   # always optional unless truly required everywhere
```

Rules:
- Always use `from __future__ import annotations` (already at top of file).
- Use `StrEnum` for new enums, not `str + Enum` combo.
- Add docstring to new enum or sub-model if its purpose is not obvious.
- Prefer `X | None = None` over `Optional[X]` (Python 3.10+ union syntax).
- To see existing enums/fields, query Neo4j: `MATCH (c:Component {name: "src.domain.models.Listing"}) RETURN c.docstring`

### Step 2 — Update the Elasticsearch index mapping

File: `src/infrastructure/es_client.py` → `INDEX_MAPPING`

Choose the correct ES type:

| Python type | ES mapping type |
|-------------|-----------------|
| `str` (free text) | `{"type": "text", "analyzer": "standard"}` |
| `str` (enum/id) | `{"type": "keyword"}` |
| `int` | `{"type": "long"}` |
| `float` | `{"type": "float"}` |
| `bool` | `{"type": "boolean"}` |
| `datetime` | `{"type": "date"}` |
| `GeoLocation` | `{"type": "geo_point"}` |

Add inside the correct nested object:
- `"seller_info" → "properties"` for SellerInfo fields.
- `"buyer_info" → "properties"` for BuyerInfo fields.
- `"contact" → "properties"` for Contact fields.
- Top-level `"properties"` for Listing fields.

> ⚠️ Do NOT change `EMBEDDING_DIMS` here unless the embedding model changes.

### Step 3 — Re-create the index (dev only)

The `INDEX_MAPPING` is applied at index creation time. To pick up mapping changes in dev:

```bash
# In the agora CLI (if a reset command exists):
agora index reset

# Or via ESClient API in a one-off script:
get_es_client().delete_index()
get_es_client().ensure_index()
```

> In production, use Elasticsearch index aliases + reindex API.

### Step 4 — Verify serialization in `listing_to_es_doc()`

File: `src/infrastructure/serializers.py` → `listing_to_es_doc(listing)`

The function uses `listing.model_dump(mode="json", exclude={"embedding"})` which auto-serializes nested Pydantic models. **No changes needed** unless:
- The new field needs a custom serialization format (e.g., like `geo_location`).
- The new field must be excluded from the ES document.

```python
# Example: custom-serialized field in listing_to_es_doc()
if listing.new_field is not None:
    doc["new_field"] = listing.new_field.custom_format()
```

> ⚠️ `listing.to_es_doc()` was **removed** from the domain model. Always use `listing_to_es_doc(listing)` from `src.infrastructure.serializers`.

### Step 5 — Expose through CLI (if user-facing)

If the field should be settable via `agora post sell` or `agora post buy`, update the relevant command:

- `src/commands/post_sell.py` → add a new `@click.option`
- `src/commands/post_buy.py` → add a new `@click.option`

Pattern for a new CLI option:
```python
@click.option("--new-field", type=str, default=None, help="Description of field.")
```

Then pass it into `SellerInfo(new_field=new_field, ...)` or `BuyerInfo(...)`.

### Step 6 — Write tests

File: `src/tests/test_models.py` (or create `test_<model>.py`)

Cover at minimum:
1. Field accepts valid values.
2. Field defaults correctly when omitted.
3. Validator raises `ValidationError` for invalid input (if field has a validator).
4. `to_es_doc()` serializes the field correctly.

```python
def test_new_field_default():
    listing = Listing(type="sell", title="Test", category="khac")
    assert listing.new_field is None   # or the default value

def test_new_field_in_es_doc():
    listing = Listing(type="sell", title="Test", category="khac", new_field="value")
    doc = listing.to_es_doc()
    assert doc["new_field"] == "value"
```

### Step 7 — Run full checks

// turbo
```bash
make lint fix=1
```

// turbo
```bash
make format
```

Fix any errors before completing the task:
- `ANN` violations → add type annotations.
- `I001` (isort) → reorder imports.
- mypy errors → fix type issues.

---

> To see all existing enums and their values, query Neo4j:
> ```cypher
> MATCH (c:Component)-[:BELONGS_TO_LAYER]->(l:Layer {name: "domain"})
> WHERE c.kind = "class"
> RETURN c.name, c.docstring
> ORDER BY c.name
> ```
