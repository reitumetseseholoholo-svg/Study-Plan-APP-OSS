# Standardized chapter updates for modules

Chapter additions and edits are done via a **single source of truth** (chapter list) and applied to module JSON so that `chapters`, `chapter_flow`, and `importance_weights` stay consistent.

## 1. Chapter spec format

**Plain list (all chapters get default weight 10):**

```json
[
  "Chapter 1: Title One",
  "Chapter 2: Title Two"
]
```

**List with optional weights (5–40):**

```json
[
  { "title": "Chapter 1: Title One", "weight": 12 },
  { "title": "Chapter 2: Title Two" }
]
```

Supported file types: `.json` (array above), `.yaml` / `.yml` (same structure; requires PyYAML).

## 2. Apply to a module

From the repo root:

```bash
# Preview (print updated JSON to stdout)
python scripts/update_module_chapters.py modules/acca_f8.json modules/acca_f8_chapters.json

# Write back to the module file
python scripts/update_module_chapters.py modules/acca_f8.json modules/acca_f8_chapters.json --in-place
```

**Stdin:** pass `-` as the chapter spec and pipe a JSON array:

```bash
echo '["Chapter 1: Foo", "Chapter 2: Bar"]' | python scripts/update_module_chapters.py modules/acca_f8.json - --in-place
```

## 3. Behaviour

- **chapters:** Replaced by the spec list (order preserved; duplicates and empty titles dropped).
- **chapter_flow:** Rebuilt linearly: each chapter points to the next; the last points to `[]`.
- **importance_weights:** From spec (explicit or default 10). If the module already has weights for a chapter, those are kept unless you use a spec with explicit weights.
- **questions**, **semantic_aliases**, **title**, and other keys are left unchanged.

## 4. Programmatic use

```python
from studyplan.module_chapters import (
    apply_chapters_to_config,
    normalize_chapter_spec,
    build_linear_chapter_flow,
)

# From list of titles
spec = ["Chapter 1: Foo", "Chapter 2: Bar"]
config = apply_chapters_to_config(existing_config, spec)

# From list of dicts with optional weight
spec = [{"title": "Chapter 1: Foo", "weight": 15}, {"title": "Chapter 2: Bar"}]
chapters, weights = normalize_chapter_spec(spec)
flow = build_linear_chapter_flow(chapters)
```

## 5. Example: AA (F8)

`modules/acca_f8_chapters.json` is the canonical chapter list for AA. To refresh `modules/acca_f8.json` after editing the list:

```bash
python scripts/update_module_chapters.py modules/acca_f8.json modules/acca_f8_chapters.json --in-place
```
