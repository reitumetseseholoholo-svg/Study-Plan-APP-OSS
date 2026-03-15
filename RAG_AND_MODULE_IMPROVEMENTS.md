# RAG, canonical structure mapping & module switching – improvement plan

Brainstormed editing plans before implementation. Covers: (1) PDF RAG system, (2) canonical structure mapping (robust / resource-efficient / accurate), (3) module switching and data isolation.

---

## 1. Pyright – done

- **Excludes added** in `pyproject.toml`: `studyplan/testing`, `tests`, `studyplan/ui_builder.py`, `studyplan/ui_mixin.py` so pyright does not require pytest or `gi.repository` in the checked set.
- **YAML import** in `studyplan/module_chapters.py`: `# type: ignore[reportMissingModuleSource]` so optional PyYAML does not produce a warning.
- **Result**: `uv run pyright` → 0 errors, 0 warnings.

---

## 2. PDF RAG system – improvement ideas

### Current behaviour (brief)

- **Sources**: Preferences `ai_tutor_rag_pdfs`, env `STUDYPLAN_AI_TUTOR_RAG_PDFS`, and per-module `syllabus_meta.source_pdf` / `reference_pdfs`.
- **Loading**: `_load_ai_tutor_rag_doc(path)` → extract PDF text, chunk with `chunk_text_for_rag(900, 120, 1200)`, cache by path/size/mtime (memory + optional SQLite).
- **Retrieval**: Lexical ranking (`lexical_rank_rag_chunks`), top-k, neighbor window, char budget; used for tutor context and for reconfig (`retrieve_from_chunks_by_path` in `module_reconfig`).
- **Reconfig**: `reconfigure_from_rag` uses pre-chunked `chunks_by_path` (no re-split), syllabus_paths preference, batched LLM extraction for outcomes/capabilities/aliases, syllabus_meta, unmapped_chapters. *Done: reuse pre-chunked chunks; prefer syllabus PDFs in retrieval.*

### Improvement directions (editing plans)

| Area | Current limitation | Proposed change | Effort / risk |
|------|--------------------|-----------------|----------------|
| **Chunking** | Fixed 900/120 chars; no semantic boundaries | Optional sentence/paragraph boundaries; keep 900 as default; add `max_chunks` per-doc cap by size | Low. Add a `boundary="sentence"` option to `chunk_text_for_rag` and use it for syllabus-like PDFs. |
| **Syllabus vs general** | Same pipeline for all PDFs | Tag RAG docs as `syllabus` vs `reference`; syllabus gets stricter chunking and priority in reconfig retrieval | Low. Add `syllabus_meta.source_pdf` / `reference_pdfs` awareness in `_get_rag_pdf_paths_for_reconfig` and in reconfig to prefer syllabus chunks. |
| **Retrieval for reconfig** | ~~re-splits full text~~ | **Done.** Reuse pre-chunked `chunks_by_path` in reconfig; score by chunk text overlap; syllabus_paths boost. |
| **Dedupe / quality** | Chunks can overlap heavily; no dedupe of near-duplicate snippets | After retrieval, optional dedupe by normalized hash or embedding similarity; cap total chars | Medium. Add a small post-retrieval step in `studyplan_ai_tutor` and/or `module_reconfig` with a char budget. |
| **Cache key** | Path + size + mtime + parser_version | Add optional `module_id` to cache namespace so different modules can have different “views” of same file (e.g. different chunking) only if we introduce module-specific chunking later | Low. Defer until we have per-module chunking. |
| **Resource cap** | Max PDFs, max bytes per file; chunks unbounded in memory | Per-app session cap on total RAG chunk count or total chars; evict LRU when over cap | Medium. Add a global RAG cache size limit and eviction in the cache layer. |

**Suggested order**: (1) Prefer syllabus PDFs in reconfig retrieval. (2) Use pre-chunked `chunks_by_path` in reconfig (no re-split). (3) Optional sentence-boundary chunking for syllabus. (4) LRU/cap for RAG cache if memory becomes an issue.

---

## 3. Canonical structure mapping – robust, resource-efficient, accurate

### Current behaviour (brief)

- **Source of truth**: Module config (`modules/<id>.json` or `MODULES_DIR/<id>.json`) holds `chapters`, `syllabus_structure`, `syllabus_meta`, `importance_weights`, `aliases`, `capabilities`.
- **Reconfig**: RAG → LLM extraction (batched) → merge into proposed config → validate `syllabus_structure` (outcome id/text/level) → confidence score → apply or hold for review.
- **Validation**: `validate_syllabus_structure` in `module_reconfig`; schema in `module_schema.json` (no `questions` key anymore).

### Improvement directions (editing plans)

| Area | Current limitation | Proposed change | Effort / risk |
|------|--------------------|-----------------|----------------|
| **Chapter ↔ outcomes** | LLM can assign outcomes to wrong chapter | After extraction, validate each outcome’s chapter by string similarity or keyword match to chapter title; move or flag mismatches | Medium. Add a post-LLM step in `reconfig.py`: for each outcome, score chapters and reassign if clearly wrong. |
| **Idempotency / stability** | Outcome ids can change between runs (e.g. “a”, “b” vs “1”, “2”) | Normalize outcome ids: e.g. `chapter_slug + "_" + index` or hash of normalized text; reuse existing ids when text matches | Medium. In `reconfigure_from_rag`, before merge, compute stable ids from chapter + index or from existing config by text match. |
| **Canonical chapter list** | Chapters come from config; RAG might use different headings | One small LLM pass: “From the syllabus excerpts, list the exact chapter/section titles in order.” Align config `chapters` to this list (merge/rename) | Medium. Add “canonical chapters from RAG” step; diff with current `chapters` and propose renames/splits. |
| **Confidence** | `compute_reconfig_confidence` uses coverage, outcome count, capabilities, aliases | Add: (a) outcome id stability vs previous config, (b) chapter alignment score, (c) penalty for validation warnings | Low. Extend `compute_reconfig_confidence` with 1–2 extra terms. |
| **Schema** | Strict learning_outcomes; capabilities/aliases less so | Add JSON Schema for `capabilities` (object: letter → title) and `aliases` (object: canonical → list of strings) in `module_schema.json`; validate in `validate_syllabus_structure` or a new `validate_module_config` | Low. Extend schema and validation. |
| **Resource use** | Batched LLM calls; no token budget per batch | Set a hard `max_input_chars` and `max_tokens` per batch; truncate retrieved text to budget; log token usage in debug | Low. Already partially there; add explicit truncation and optional logging. |

**Suggested order**: (1) Stable outcome ids (and optional chapter validation). (2) Extended confidence (stability + alignment). (3) Canonical chapter list from RAG. (4) Stricter schema for capabilities/aliases.

---

## 4. Module switching – no cross-module data corruption

### Current behaviour (brief)

- **Switch flow**: User picks “Switch Module” → selects module → `self.module_id` / `self.module_title` updated → `save_preferences()` → message “Restart required”.
- **On startup**: `StudyPlanGUI` reads preferences (e.g. `module_id`) → creates **one** `StudyPlanEngine(exam_date=…, module_id=…, module_title=…)` → engine sets `self.DATA_FILE`, `self.QUESTIONS_FILE` via `_resolve_module_paths(self.module_id)` → `load_data()` / `load_questions()` use those paths.
- **Paths**: `CONFIG_HOME / sanitize(module_id) / data.json` and `…/ questions.json`. Legacy: `acca_f9` can fall back to root `data.json`/`questions.json` if module dir files don’t exist.
- **Caches**: RAG doc cache key is path+size+mtime (no module_id). Perf cache is app-scoped (keys like `rag_doc:…`, `coach_pick:snapshot`). No engine instance is reused after switch without restart.

### Risk points and hardening (editing plans)

| Risk | Mitigation | Effort |
|------|-------------|--------|
| **Wrong path at runtime** | Engine is created once with `module_id`; paths are set in `__init__` from `_resolve_module_paths(module_id)`. No path update without new engine. After switch we require restart, so no “switch without new engine” path. | None. Already safe. |
| **Preferences vs engine** | If preferences are loaded after engine is built, engine could have default module_id. Code creates engine with `self.module_id` / `self.module_title` that were set from preferences earlier in `do_activate`. Ensure order: load preferences → set `self.module_id` → then create `StudyPlanEngine(module_id=self.module_id, …)`. | Low. Audit startup order in `do_activate`; add a single assertion or log that `engine.module_id == self.module_id`. |
| **Save on shutdown** | If app saves data on exit, it must save using the **current** engine’s `DATA_FILE`/`QUESTIONS_FILE`. If user switched module but deferred restart, engine still has old module_id and old paths – so we’d save to the old module’s dir. That’s correct. Only after restart does engine have new module_id. | None. |
| **Shared caches** | RAG cache is keyed by file path; tutor context is built each time from current `module_id`. No cache key includes module_id today. If we ever keyed something by “current module” in a long-lived cache, we’d need to invalidate on switch. | Low. Document that RAG/perf caches are module-agnostic (path-scoped); if we add module-scoped caches later, clear or namespace them by module_id. |
| **Legacy acca_f9 fallback** | `_resolve_module_paths` for `acca_f9` can return root `data.json`/`questions.json` if module dir doesn’t exist. That’s intentional for migration. Ensure we never write to root when `module_id` is acca_f9 and module dir exists. | Low. Code already prefers module dir when both exist. Add a test: with module dir present, paths must be under module dir. |
| **Explicit isolation check** | No runtime check that “all reads/writes for this engine use this module’s dir”. | Medium. Add a helper: `def _assert_data_paths_under_module(self) -> None` that checks `self.DATA_FILE.startswith(module_dir)` and same for `QUESTIONS_FILE`; call once after `_resolve_module_paths` in `__init__` (or in tests only). |

**Suggested order**: (1) Audit startup: preferences → `module_id` → engine creation order. (2) Add assertion or log that `engine.module_id == self.module_id` after creation. (3) Optional: `_assert_data_paths_under_module` in dev/tests. (4) Document RAG/cache as path-scoped, not module-scoped.

---

## 5. Summary – what to do next

- **Pyright**: Done; no further changes unless we re-include tests/ui in typecheck.
- **RAG**: Prioritise “prefer syllabus in reconfig” and “use pre-chunked chunks in reconfig”; then optional sentence chunking and cache caps.
- **Canonical structure**: Prioritise stable outcome ids and confidence extensions; then optional chapter alignment and stricter schema.
- **Module switching**: Confirm startup order and add a single consistency check; optionally add path assertion in tests.
