---
description: Add a new field to the Listing model (or sub-models) end-to-end
---

// turbo-all

## Context (DO NOT re-read source to confirm)
- `seller_info.*` → SELL only | `buyer_info.*` → BUY only | `Listing.*` → shared
- ES type map: `str(free)` → text | `str(enum)` → keyword | `int` → long | `float` → float | `bool` → boolean | `datetime` → date
- Serializer: `listing_to_es_doc()` in `src/infrastructure/serializers.py` — uses `model_dump()` by default; override only for custom format (e.g., geo_location)

## Steps

1. Read skill `.agent/skills/add_listing_field.md`
2. Edit `src/domain/models.py` — add field to correct sub-model or Listing
3. Edit `src/infrastructure/es_client.py` — add ES mapping in INDEX_MAPPING
4. Edit `src/infrastructure/serializers.py` — only if custom serialization needed
5. If user-facing: edit `src/commands/post.py` — add `@click.option`
6. Edit `src/tests/` — add test: field default + es_doc serialization
