# RAG, canonical structure mapping & module switching – improvement plan

Originally a brainstorm before implementation; **refreshed March 2026** to record what shipped vs what remains optional.

Scope: (1) PDF RAG, (2) canonical structure / reconfig, (3) module switching and data isolation.

---

## 1. Pyright – done

- **Excludes** in `pyproject.toml`: `studyplan/testing`, `tests`, `studyplan/ui_builder.py`, `studyplan/ui_mixin.py` so pyright does not require pytest or `gi.repository` in the checked set.
- **YAML import** in `studyplan/module_chapters.py`: `# type: ignore[reportMissingModuleSource]` so optional PyYAML does not produce a warning.
- **Result**: `uv run pyright` → 0 errors, 0 warnings (re-verify after large edits).

**Status:** Complete unless tests/UI are brought back into the pyright set.

---

## 2. PDF RAG system

### Current behaviour (brief)

- **Sources**: Preferences `ai_tutor_rag_pdfs`, env `STUDYPLAN_AI_TUTOR_RAG_PDFS`, and per-module `syllabus_meta.source_pdf` / `reference_pdfs`.
- **Loading / chunking**: `chunk_text_for_rag` in `studyplan_ai_tutor.py` supports `boundary="paragraph"` (default) or **`boundary="sentence"`**, plus `max_chunks` (default cap 1200). The GTK app classifies PDFs (e.g. syllabus tier) and uses **sentence boundaries for syllabus-like sources**, paragraph for others (`studyplan_app.py` where `tier == "syllabus"` sets `boundary`).
- **Cache**: By path + size + mtime (+ parser versioning where applicable); memory + optional SQLite. **No `module_id` in the RAG doc cache key** (still path-scoped).
- **Tutor retrieval**: Lexical ranking, top-k, neighbor window, char budget; named **presets** tune budgets and per-source caps (`studyplan/ai/rag_presets.py`, applied in `_build_ai_tutor_rag_prompt_context` in `studyplan_app.py`). Env vars cap candidates, hard char ceiling, etc.
- **Context dedupe**: `STUDYPLAN_TUTOR_CONTEXT_DEDUP` skips rebuilding identical tutor context when the fingerprint matches (not the same as embedding-based chunk dedupe).
- **Reconfig**: `reconfigure_from_rag` in `studyplan/module_reconfig/reconfig.py` uses pre-chunked **`chunks_by_path`** (no re-split), with **`retrieve_from_chunks_by_path`** and **`syllabus_paths`** boost. Tests: `studyplan/testing/test_module_reconfig.py`.

### Improvement inventory

| Area | Status | Notes |
|------|--------|--------|
| Sentence / paragraph chunk boundaries | **Done** | `chunk_text_for_rag(..., boundary=…)`; syllabus tier uses sentence in app. |
| Syllabus vs reference (chunking + reconfig priority) | **Done** | Reconfig prefers syllabus paths; tutor uses tiered chunk boundary. |
| Pre-chunked reconfig retrieval | **Done** | `retrieve_from_chunks_by_path`, syllabus boost. |
| Post-retrieval chunk dedupe (hash / embedding similarity on snippets) | **Open** | Only lightweight full-context dedup exists (`STUDYPLAN_TUTOR_CONTEXT_DEDUP`). |
| `module_id` in RAG cache namespace | **Deferred** | Still sensible only if per-module chunking diverges for the same file path. |
| Global session LRU / hard cap on total RAG chunks in memory | **Open** | Per-doc `max_chunks` and tutor budgets exist; no dedicated RAG-cache eviction layer as originally sketched. |

**Suggested order (remaining):** (1) Only if memory pressure appears: global RAG cache cap + LRU. (2) Optional: post-retrieval near-duplicate suppression for tutor/reconfig. (3) `module_id` namespace if chunking becomes module-specific.

---

## 3. Canonical structure mapping

### Current behaviour (brief)

- **Source of truth**: Module JSON under `modules/` or `MODULES_DIR` — `chapters`, `syllabus_structure`, `syllabus_meta`, weights, `aliases`, `capabilities`.
- **Reconfig**: RAG → batched LLM extraction → merge → **`validate_module_config`** (`validate_syllabus_structure` + **`validate_capabilities_and_aliases`**) → **`compute_reconfig_confidence`** → apply or review.
- **Stable outcome ids**: **`_stable_outcome_id`** reuses ids when normalized outcome text matches the existing config; otherwise assigns stable slugs (`studyplan/module_reconfig/reconfig.py`).
- **Confidence**: **`compute_reconfig_confidence`** factors in chapter coverage, outcomes per chapter, **chapter alignment** (structure keys vs `chapters` list), **outcome id stability** vs previous config, plus capabilities/aliases presence; stores **`outcome_id_stability_ratio`** on `syllabus_meta`. Non-empty **`validation_errors`** forces confidence **0.0**.
- **Schema**: `module_schema.json` — stricter **`capabilities`** (uppercase letter keys) and **`aliases`** (alias string → canonical chapter string); aligns with engine normalization.

### Improvement inventory

| Area | Status | Notes |
|------|--------|--------|
| Stable / reusable outcome ids | **Done** | `_stable_outcome_id`, tests in `test_module_reconfig.py`. |
| Extended confidence (alignment + stability + validation gate) | **Done** | `compute_reconfig_confidence`. |
| Stricter capabilities / aliases (schema + validation) | **Done** | `module_schema.json`, `validate_capabilities_and_aliases`, `validate_module_config`. |
| Post-LLM chapter ↔ outcome repair (similarity / reassignment) | **Open** | No automatic move/flag pass after extraction. |
| Canonical chapter list from RAG (extra LLM pass + diff/merge) | **Open** | Not implemented. |
| Token / batch logging | **Partial** | Truncation and budgets exist; optional richer debug logging still possible. |

**Suggested order (remaining):** (1) Optional post-LLM alignment pass if wrong-chapter outcomes show up in the wild. (2) Optional “canonical chapters” extraction pass for messy imports. (3) Optional telemetry for batch sizes / truncation hits.

---

## 4. Module switching – no cross-module data corruption

### Current behaviour (brief)

- **Switch flow**: Switch module → preferences updated → **restart required** → new engine with new paths.
- **Paths**: `CONFIG_HOME / sanitize(module_id) / data.json` and `questions.json`. Legacy **`acca_f9`** may use root files if module dir files are absent (migration).
- **Caches**: RAG doc cache path-scoped; no `module_id` in key. Document assumption: long-lived caches must stay path- or module-safe if extended.

### Hardening inventory

| Risk / item | Status | Notes |
|-------------|--------|--------|
| Single engine, paths from `module_id` in `__init__` | **OK** | No path swap without new engine. |
| Preferences before engine: matching `module_id` | **Done** | After `StudyPlanEngine` construction, **`studyplan_app.py`** raises **`RuntimeError`** if `engine.module_id` ≠ GUI `module_id` (module isolation guard). |
| Save on shutdown uses engine paths | **OK** | Deferred restart keeps old engine → saves old module (intended). |
| `_assert_data_paths_under_module` helper | **Open** | Not present; could live in engine `__init__` or tests only. |
| Dedicated test: acca_f9 paths under module dir when dir exists | **Open** | Worth adding if not already covered elsewhere. |

**Suggested order (remaining):** (1) Optional `_assert_data_paths_under_module` in tests or debug builds. (2) Optional targeted test for legacy path resolution.

---

## 5. Summary

| Track | Done | Still optional / deferred |
|-------|------|-----------------------------|
| **Pyright** | Excludes + YAML ignore | Re-expand scope only if desired. |
| **RAG** | Syllabus-aware chunking & reconfig retrieval, pre-chunked reconfig, presets & char caps, per-doc `max_chunks` | Global RAG LRU; snippet-level dedupe; `module_id` cache namespace if chunking splits per module. |
| **Canonical mapping** | Stable ids, confidence + validation gate, schema + `validate_module_config` | Post-LLM chapter repair; canonical-chapter LLM pass; richer batch logging. |
| **Module switch** | Runtime guard `engine.module_id == app.module_id` | Path assertion helper; explicit legacy path test. |

This file is the **status ledger** for the above themes; prefer **`FEATURES.md`** / **`DEVELOPER_DOC.md`** for user-facing and general architecture detail.
