# LLM Telemetry Schema

This document describes the purpose labels, turn result fields, and SLO schema used for LLM telemetry across the AI tutor, coach, autopilot, and generation pipelines.

## Purpose Labels

Defined in `studyplan/ai/llm_telemetry.py`. All purpose strings are normalised to lowercase alphanumeric + underscore and must match `^[a-z][a-z0-9_]{0,47}$`.

| Constant | Value | Used by |
|---|---|---|
| `PURPOSE_TUTOR_EMBEDDED` | `tutor_embedded` | AI tutor workspace (embedded chat panel) |
| `PURPOSE_TUTOR_POPUP` | `tutor_popup` | AI tutor popup dialog |
| `PURPOSE_COACH` | `coach_turn` | Coach recommendation and analysis |
| `PURPOSE_AUTOPILOT` | `autopilot_decide` | Autopilot action-plan requests |
| `PURPOSE_GAP_GEN` | `gap_gen` | AI MCQ question generation for outcome gaps |
| `PURPOSE_SECTION_C` | `section_c_gen` | Section C case/scenario generation |
| `PURPOSE_SYLLABUS` | `syllabus_ai` | Syllabus PDF parsing with LLM assistance |
| `PURPOSE_UNKNOWN` | `unknown` | Fallback when purpose cannot be determined |

Additional routing-level purposes used in `model_routing.py`:

| Purpose string | Description |
|---|---|
| `deep_reason` | Deep reasoning / chain-of-thought requests |
| `section_c_evaluation` | Section C answer evaluation/grading |
| `section_c_judgment` | Section C judgment with extended thinking |
| `section_c_loop_diff` | Section C answer diff and recheck loop |
| `general` | Unclassified requests |

## Turn Result Fields

`TutorTurnResult` (from `studyplan/contracts.py`) is returned by all AI turn calls:

| Field | Type | Description |
|---|---|---|
| `text` | `str` | Sanitised response text shown to the user |
| `model` | `str` | Model identifier that produced the response |
| `latency_ms` | `int` | Wall-clock milliseconds for the full turn |
| `error_code` | `str` | Empty string on success; error label on failure (e.g. `timeout`, `parse_error`, `cancelled`) |
| `telemetry` | `dict[str, Any]` | Freeform metadata: `purpose`, `prompt_chars`, `response_chars`, `rag_snippets`, `model_source`, `backend`, `stream_stall_count`, `pedagogical_mode`, etc. |

## Model Performance Fields

`ModelPerfStats` (from `studyplan/contracts.py`) tracks per-model aggregate stats:

| Field | Type | Description |
|---|---|---|
| `model` | `str` | Model identifier |
| `samples` | `int` | Total turn attempts |
| `success` | `int` | Successful completions |
| `errors` | `int` | Error count |
| `cancelled` | `int` | Cancelled count |
| `latency_ms_sum` | `float` | Cumulative latency for computing mean |
| `response_tokens_sum` | `float` | Cumulative response tokens (if available from backend) |
| `coverage_target_sum` | `int` | Number of coverage targets evaluated |
| `coverage_hit_sum` | `int` | Number of coverage targets met |

## Telemetry Payload Fields

The following fields appear in the telemetry payload (the `telemetry` dict inside `TutorTurnResult`):

| Key | Type | Description | Present in |
|-----|------|-------------|------------|
| `pedagogical_mode` | `str` | Pedagogical mode of the turn (`teach`, `practice`, `revision`, `exam_technique`, `freeform`) — derived from UI flags + mode hint during prompt assembly | embedded, popup |
| `generation_ms` | `int` | Wall-clock ms from LLM inference start to completion (includes prompt processing + streaming) | embedded, popup |
| `stream_ms` | `int` | Wall-clock ms from first token arrival to stream completion (time spent streaming tokens) | embedded, popup |
| `model_first_token_ms` | `int` | Time from LLM inference start to first token arrival (prompt processing / time-to-first-token) | embedded, popup |
| `rag_snippets` | `int` | Number of RAG snippets used in the turn | embedded, popup |
| `rag_sources` | `int` | Number of distinct source PDFs the snippets were drawn from | embedded, popup |

**Semantic guarantee**: In both paths, `generation_ms >= stream_ms` must hold. The embedded path computes both from `latency_ms - prompt_build_ms - rag_ms` and `first_token_ms`; the popup path computes them from separate `generation_started_at` and `stream_started_at` guard-state timestamps. Violations of `generation_ms >= stream_ms` indicate a telemetry construction bug.

## SLO Profile

`SloProfile` (from `studyplan/contracts.py`) summarises latency SLOs:

| Field | Type | Description |
|---|---|---|
| `status` | `str` | `ok`, `warn`, or `breach` |
| `samples` | `int` | Sample count used to compute SLO |
| `p50_latency_ms` | `float` | 50th-percentile latency |
| `p90_latency_ms` | `float` | 90th-percentile latency |
| `p95_latency_ms` | `float` | 95th-percentile latency |
| `latency_spread_ratio` | `float` | p90 / p50 — values > 3.0 indicate high variance |

SLO thresholds (from `studyplan_app_kpi_routing.py`):

| Constant | Value |
|---|---|
| `AI_TUTOR_LATENCY_SLO_MIN_SAMPLES` | 10 |
| `AI_TUTOR_LATENCY_SLO_P50_MS` | 8000 |
| `AI_TUTOR_LATENCY_SLO_P90_MS` | 20000 |
| `AI_TUTOR_LATENCY_SLO_SPREAD_RATIO` | 3.0 |

## Golden Prompt Fixture

`tests/fixtures/golden_tutor_prompts.json` captures deterministic prompt outputs for regression testing.

**Contract rules:**
- Golden fixture changes must be deterministic and reviewable — no non-deterministic content
- The fixture is updated only when prompt structure intentionally changes; explain the change in the PR
- Prompt-quality regressions are checked with the tutor-quality tooling in `tests/tutor_quality/`

## Adding New Telemetry Fields

1. Define a new `PURPOSE_*` constant in `studyplan/ai/llm_telemetry.py` if a new purpose is needed
2. Add it to the routing aliases in `studyplan/ai/model_routing.py` if it requires a separate model routing entry
3. Document it in this file under the appropriate section
4. For structured telemetry fields added to `TutorTurnResult.telemetry`, document the key, type, and semantics here
