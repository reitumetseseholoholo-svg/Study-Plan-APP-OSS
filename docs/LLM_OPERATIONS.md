# LLM operations handbook

Single reference for operators and maintainers: budgets, routing, caches, rollback, and quality gates. Complements [LLM_IMPLEMENTATION_ROADMAP.md](LLM_IMPLEMENTATION_ROADMAP.md) and [LLM_TELEMETRY_SCHEMA.md](LLM_TELEMETRY_SCHEMA.md).

## Contract and rollback

| Item | Location |
|------|----------|
| Tutor prompt contract version | `AI_TUTOR_PROMPT_CONTRACT_VERSION` in `studyplan_ai_tutor.py` |
| Telemetry shape | `studyplan/ai/llm_telemetry.py`, `docs/LLM_TELEMETRY_SCHEMA.md` |
| Rollback | Revert prompt/RAG/routing changes and bump contract version if the **assembled tutor prompt shape** changes; re-run `pytest` and tutor quality reference mode (below). |

## Model routing (Phase 4)

| Mechanism | Details |
|-----------|---------|
| **Purpose-based defaults** | `_select_local_llm_model` / `_resolve_local_llm_default_for_purpose` use purpose strings: `tutor`, `coach`, `autopilot`, `gap_generation`, `section_c_generation`, `general`. |
| **Optional routing table** | JSON: `STUDYPLAN_LLM_MODEL_ROUTING_PATH` or `$STUDYPLAN_CONFIG_HOME/llm_model_routing.json`. Schema: see `studyplan/ai/llm_model_routing.example.json`. Only model names that **exist in the current Ollama list** are applied. |
| **Failover chain** | `_build_local_llm_model_failover_sequence` prepends configured `failover` entries (in order) after the selected model, then continues with ranked candidates. |
| **Env** | `STUDYPLAN_AI_TUTOR_MODEL_FAILOVER_MAX` — max failover attempts (1–5). |

### Auto-concise under load

| Env | Effect |
|-----|--------|
| `STUDYPLAN_AI_TUTOR_AUTO_CONCISE_UNDER_LOAD=1` | When latency SLO / queue pressure is bad, tutor turns use **concise** prompt style for that turn even if the concise toggle is off. |
| `STUDYPLAN_AI_TUTOR_SUPPRESS_LOAD_NOTICE=1` | Do not append the one-per-session **load notice** line to the tutor status bar. |
| **Preference** `ai_tutor_suppress_load_notice` | Same as the env suppress: checkbox **Suppress load notices** on the in-app tutor workbench (saved in preferences). Checked = never show the load notice (preference is checked before env). |

Adaptive context/RAG shrinking is unchanged: `_compute_ai_tutor_adaptive_limits` (load level + SLO).

### Streaming

Tutor turns use **streaming** generation (`_ollama_generate_text_stream`) with stall watchdog and cancel — no separate flag required (Phase 4.5 baseline).

## RAG and context (cross-links)

| Topic | Doc / code |
|-------|------------|
| RAG presets | `studyplan/ai/rag_presets.py`, `STUDYPLAN_AI_TUTOR_RAG_PRESET` |
| RAG char hard cap | `STUDYPLAN_AI_TUTOR_RAG_CHAR_HARD_CAP` |
| Module-scoped PDFs | `STUDYPLAN_AI_TUTOR_RAG_STRICT_MODULE_PDFS=1` |
| Context drop order | `studyplan/ai/context_policy.py` |
| Formatted context cache | `local_context_block` v2 keys in app |

## Quality assurance (Phase 5)

### PR / local checks

```bash
pytest tests/tutor_quality/test_tutor_quality_scorer.py tests/tutor_quality/test_tutor_quality_runner.py -q
python tools/run_tutor_quality_benchmark.py --mode reference --matrix tests/tutor_quality/matrix_v1.json \
  --expected tests/tutor_quality/expected_scores_v1.json --report /tmp/tutor_quality_report.json
```

Full `pytest` (as in CI) already includes `tests/tutor_quality/` when those paths change.

### Matrix and rubric

- **Matrix**: `tests/tutor_quality/matrix_v1.json`
- **Reference expected scores**: `tests/tutor_quality/expected_scores_v1.json`
- **Scorer**: `tests/tutor_quality/quality_scorer.py` — supports optional `expected.quality_checks.require_rag_style_citation` for RAG-style `[S#]` discipline in benchmarks.

**Case IDs (e.g. `f9_quality_rag_citation`)** — The `f9_`, `f7_`, `f8_`, `f6_` prefix is shorthand for the matrix **`module_id`** (`acca_f9` = ACCA Financial Management, etc.). The middle part describes the scenario (`explain_wacc`, `quality_rag_citation`, …). It is not a separate “test framework” namespace — just stable slugs for regression fixtures.

### Shadow / A/B (offline)

Compare two frozen response sets against the same rubric without changing the live app:

```bash
python tools/run_tutor_quality_shadow_compare.py \
  --matrix tests/tutor_quality/matrix_v1.json \
  --responses-a ./responses_variant_a.json \
  --responses-b ./responses_variant_b.json \
  --report ./shadow_compare_report.json
```

Each responses file is a JSON object: `"case_id": "full model response text"`. Generate them by exporting tutor transcripts or by running `run_tutor_quality_benchmark.py` in **ollama** mode twice and post-processing reports.

### Latency / model A/B (operational)

1. Point `llm_model_routing.json` (or the Ollama dropdown) at model **A**, run a fixed prompt set or perf harness; repeat for model **B**.
2. Use `scripts/llm_telemetry_aggregate.py` on saved telemetry to compare `latency_ms` / estimated tokens per purpose.
3. For strict apples-to-apples, keep prompts identical and only change `local_llm_model` or routing JSON between runs.

### Telemetry aggregation

```bash
python scripts/llm_telemetry_aggregate.py
```

Uses `STUDYPLAN_CONFIG_HOME` / preferences path as documented in the script.

## Nightly / extended (optional)

- **GitHub Actions**: workflow `tutor-quality-nightly.yml` runs weekly (and on demand) — `pytest tests/tutor_quality/` plus reference-mode `run_tutor_quality_benchmark.py` (no Ollama). Artifact: `tutor_quality_nightly_report.json`.
- **Live Ollama**: run `run_tutor_quality_benchmark.py --mode ollama` only on a machine with models installed; not part of default CI.
