# Domain Reasoning Architecture

> **Status:** Phases 1–4 implemented (see [Current Implementation Status](#current-implementation-status)).  
> This document is the original architectural proposal. The section below summarises what has been built and how it differs from the original plan.

## Current Implementation Status

The core reasoning engine (`studyplan/domain_reasoning/`) has been implemented end-to-end for the FM (Financial Management) domain:

| Phase | Description | Status |
|---|---|---|---|
| 1 | Parameter key detection via candidate-function probing | ✅ Done |
| 2 | Multi-path fallback (alternative providers per output slot) | ✅ Done |
| 3 | Input gap analysis (greedy fixed-point provider insertion) | ✅ Done |
| 4 | Weighted confidence (`avg_quality × success_rate`) | ✅ Done |
| 2a | **Contract enrichment** — `concept_ids`, `template_ref`, `template_inputs` on `TutorPracticeItem`; `concept_ids`, `template_ref`, `failed_steps`, `error_patterns`, `diagnostic_confidence` on `TutorAssessmentResult`; `weak_concept_ids_top`, `concept_error_patterns` on `TutorLearnerProfileSnapshot` | ✅ Done |
| 4a | **Practice loop integration** — `_assess_domain_item()` in `DeterministicTutorAssessmentService`; concept error pattern tracking in `InMemoryTutorLearnerModelStore.note_assessment()` | ✅ Done |
| 5a | **Tutor context surface** — `weak_concept_ids_top`, `failed_steps`, `diagnostic_confidence` surfaced in `_build_ai_tutor_learner_profile_brief()` | ✅ Done |
| 6a | **Autopilot concept awareness** — `weak_concept_ids_top` + `concept_error_summary` injected into autopilot snapshot, context block, action evidence, and fallback reasoning | ✅ Done |
| 5–7 | Full coach/autopilot upgrade, authoring tooling | 📋 Partial (see 6a) |

### Key deviations from the proposal

- **Solver strategy**: The proposal recommended starting with `FM.npv` then `FM.wacc` then `F7.goodwill`. Implementation covers all 10 FM concepts (NPV, WACC, CAPM, IRR, payback, ARR, CCC, EOQ, gearing, cost_of_equity_dvm). F7/FR consolidation has not been started.
- **Template interface**: Uses `FormulaTemplate` base class with `solve(**inputs)` (positional args from domain templates), not the `ConceptTemplate` protocol with `input_schema`/`output_schema`. Candidate-function probing detects parameter keys dynamically; `inspect.signature` is NOT used because domain templates override `solve()` with positional args whose param names differ from input dict keys.
- **No concept metadata in module JSON**: The original proposal required explicit `concepts` arrays in module JSON. Instead, `BUILTIN_CONCEPTS` in `concepts.py` hardcodes the FM concept definitions. The module JSON extension path remains future work.
- **Packaging**: The original proposal envisioned `concepts.py`, `dependencies.py`, `templates.py`, `evaluator.py`, `diagnostics.py`, `planner.py`. The actual implementation has `concepts.py`, `templates.py`, `evaluator.py`, `diagnostics.py`, `reasoning_engine.py` (which subsumes the planned `planner.py` and `dependencies.py` roles).
- **Phase 2/4/5 integration**: The original proposal was still in "planned" status for phases 2, 4, and 5. These have now been implemented: contract fields, practice loop assessment integration, and tutor context surfacing. The `DeterministicTutorAssessmentService._assess_domain_item()` method and `InMemoryTutorLearnerModelStore` concept error pattern tracking complete the feedback loop from domain solver → assessment → learner profile → tutor context.
- **220 test functions** across 3 files (`test_reasoning_engine.py`, `test_domain_reasoning.py`, `test_numerical_solver.py`) — 17 custom tests for fallback, gap analysis, and weighted confidence specifically; plus 10 new tests for domain-aware assessment integration.

### Known limitations

- `_plug_input_gaps` does NOT resolve transitive dependencies of newly inserted concepts; relies on multi-path fallback at execution time.
- Only `cost_equity` has multiple providers (`fm.cost_of_equity_dvm` ↔ `fm.capm`); all other output slots have exactly one provider.
- WACC template applies `(1-tax)` to `cost_debt` internally; `cost_of_debt` solver returns after-tax value — double-tax is existing behaviour, not a regression.
- Input source quality weights are heuristics tuned to pass existing test assertions, not calibrated against real student data.
- Domain-aware assessment only fires when the practice item has an explicit `template_ref` AND `domain_reasoner` is configured — no automatic concept detection from question text during practice.
- Learner answers are compared by final numeric value only; step-by-step learner working is not yet compared against truth steps.
- Coach urgency (`engine.get_daily_plan`) does not yet consume `weak_concept_ids_top` or `concept_error_patterns` — still operates at chapter-level competence only. Autopilot snapshot, evidence builder, fallback action, and context block now include concept diagnostics.

## Purpose

This document proposes a codebase-specific path for evolving StudyPlan from a strong adaptive planner/tutor into a domain-aware reasoning tutor without breaking the current local-first architecture.

The intent is not to replace the existing engine, tutor loop, or cognitive runtime. The intent is to add a deterministic domain semantics layer that plugs into the current engine, learner model, tutor context builders, and autopilot policy.

## Current Position

The repo already has the right high-level foundations:

- `studyplan_engine.py` owns syllabus structure, persistence, scheduling, semantic routing, question outcome resolution, and concept graph build.
- `studyplan_ai_tutor.py` and `studyplan_app.py` own prompt construction, runtime orchestration, and GUI-facing tutor/autopilot behavior.
- `studyplan/` already contains GTK-free services, contracts, loop controllers, learner modeling, and assessment machinery.
- The engine already builds a canonical concept graph and `outcome_concept_links`.
- The practice loop and learner profile already track error tags and misconception tags.
- The autopilot already consumes structured snapshots and uses constrained action allowlists.

This means the missing capability is not “add more AI.” It is “make domain knowledge executable and diagnosable.”

## Problem Statement

The system is currently stronger at:

- deciding what the learner should study next
- detecting weak topics
- managing timing, memory, and study flow
- grounding tutor behavior in app state

The system is currently weaker at:

- executing domain procedures deterministically
- validating intermediate working, not just final outputs
- classifying domain-specific failure modes with high precision
- propagating concept-level diagnostics through tutor, coach, and autopilot

In short:

- current concept knowledge is mostly structural
- missing concept knowledge is operational

## Design Principle

Keep responsibility boundaries explicit:

- deterministic domain layer owns domain truth
- learner model owns belief about learner state
- tutor/LLM layer owns explanation and interaction
- coach/autopilot own constrained action selection

The LLM should consume structured diagnostic state. It should not be the source of truth for accounting or finance procedures when deterministic evaluation is feasible.

## Architectural Goal

Add a GTK-free domain reasoning package that can:

- define explicit concepts and dependencies
- attach executable templates to concepts
- compute authoritative reference solutions for supported procedural domains
- compare learner working against deterministic truth
- emit structured error patterns and failed steps
- surface those diagnostics upward to tutor, learner profile, coach, and autopilot

## Implemented Package

The package exists at `studyplan/domain_reasoning/` with the following structure:

```text
studyplan/domain_reasoning/
  __init__.py
  concepts.py            # BUILTIN_CONCEPTS, concept definitions, output slot groups
  templates.py           # FormulaTemplate base class for executable solvers
  evaluator.py           # Step-by-step learner answer comparison
  diagnostics.py         # Structured error pattern emission
  reasoning_engine.py    # Plan compilation, execution, fallback, gap analysis, confidence
  domains/
    __init__.py
    acca_fm/
      __init__.py
      npv.py
      wacc.py
      capm.py
      irr.py
      payback.py
      arr.py
      ccc.py
      eoq.py
      gearing.py
```

The intended `dependencies.py` and `planner.py` modules were not created as separate files — their logic is folded into `reasoning_engine.py` (plan compilation, dependency resolution, execution orchestration).

The package remains:

- GTK-free
- deterministic-first
- unit-testable in isolation
- importable from engine/services/tutor code

## Why A New Package

Do not put solver logic in:

- `studyplan_app.py`
- `studyplan_ai_tutor.py`
- ad hoc branches inside `studyplan_engine.py`

Those files already own substantial orchestration and runtime complexity.

If domain execution logic is added directly there, the codebase will lose one of its current strengths: clear separation between domain/runtime logic and UI orchestration.

## Core Data Model

### 1. Explicit Concept Metadata

The current synthesized concept graph is useful, but it should become the fallback path, not the only path.

Extend module data with explicit concept entries when available.

Example:

```json
{
  "concepts": [
    {
      "id": "f7.goodwill.basic",
      "label": "Goodwill calculation",
      "chapter_refs": ["B. Groups"],
      "outcome_ids": ["B3a", "B3b"],
      "dependencies": [
        "f7.nci.measurement",
        "f7.net_assets.fv",
        "f7.acquisition_date.split"
      ],
      "diagnostic_tags": [
        "omit_nci",
        "wrong_fv",
        "pre_post_mix"
      ],
      "template_ref": "acca_f7.consolidation.goodwill_v1",
      "centrality": 0.84
    }
  ]
}
```

New explicit fields:

- `id`: stable concept identifier
- `label`: human-readable name
- `chapter_refs`: links into current chapter taxonomy
- `outcome_ids`: direct mapping to syllabus outcomes
- `dependencies`: prerequisite concept IDs
- `diagnostic_tags`: supported error classes
- `template_ref`: executable template binding
- `centrality`: authored or derived graph importance score

### 2. Typed Dependency Edges

The current graph should evolve from simple containment into typed relations.

Useful relation types:

- `contains`
- `depends_on`
- `variant_of`
- `confused_with`
- `formula_of`
- `step_precedes`
- `assessed_by`

These do not all need to be implemented at once. The first high-value additions are:

- `depends_on`
- `confused_with`
- `step_precedes`

### 3. Executable Template Metadata

Each supported procedural concept should point to an executable template.

Example:

```json
{
  "template_ref": "acca_f7.consolidation.goodwill_v1"
}
```

The template definition itself should live in code, not raw module JSON, so it can be tested and versioned safely.

## Core Runtime Interfaces

### Concept Template

Suggested protocol:

```python
class ConceptTemplate(Protocol):
    concept_id: str
    template_version: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]

    def solve(self, inputs: dict[str, Any]) -> dict[str, Any]: ...
    def evaluate_steps(
        self,
        learner_steps: list[dict[str, Any]],
        truth: dict[str, Any],
    ) -> list[dict[str, Any]]: ...
    def classify_errors(
        self,
        learner_steps: list[dict[str, Any]],
        truth: dict[str, Any],
    ) -> list[str]: ...
```

### Evaluation Result

Suggested deterministic output shape:

```python
{
    "concept_ids": ["f7.goodwill.basic"],
    "primary_concept_id": "f7.goodwill.basic",
    "truth": {...},
    "failed_steps": ["identify_nci", "revalue_net_assets"],
    "error_patterns": ["omit_nci", "pre_post_mix"],
    "diagnostic_confidence": 0.88,
}
```

This should feed the existing assessment and learner profile structures rather than inventing a completely separate reporting model.

## Integration With Existing Code

### 1. Engine Integration

Relevant current areas:

- `build_canonical_concept_graph()`
- `resolve_question_outcomes()`
- `resolve_question_concepts()`
- outcome coverage and semantic routing logic

Planned change:

- If explicit module concept metadata exists, use it as the primary source for concept nodes and dependency edges.
- If not, fall back to the current synthesized graph from syllabus structure and subtopics.
- Preserve current output shape so existing callers keep working.

This means:

- no rewrite of current graph consumers
- better fidelity for authored modules
- backward compatibility for current modules

### 2. Contract Integration

Existing assessment outputs already carry fields like:

- `error_tags`
- `misconception_tags`
- marks and outcome

These should be enriched rather than replaced.

Candidate additions to `TutorAssessmentResult` and related structures:

- `concept_ids`
- `primary_concept_id`
- `error_patterns`
- `failed_steps`
- `diagnostic_confidence`
- `template_ref`

These fields allow deterministic reasoning to pass through the existing loop cleanly.

### 3. Learner Profile Integration

Current learner profile state already tracks top misconception tags and weak capabilities.

Add concept-aware aggregates:

- `weak_concept_ids_top`
- `error_pattern_counts`
- `concept_attempt_stats`
- `concept_transfer_scores`
- `blocked_dependency_concepts_top`

This is the minimum structure required for concept-aware tutor grounding and action policy.

### 4. Practice Loop Integration

The practice loop is the right place to inject deterministic diagnosis.

Desired flow:

1. Build practice item.
2. Map item to concept IDs and template refs.
3. On submission, if deterministic evaluation is supported:
   - solve reference truth
   - compare learner steps/output
   - emit concept-level diagnostics
4. Merge that result into:
   - assessment output
   - learner profile update
   - tutor follow-up context

Fallback:

- if no deterministic template exists, keep current heuristic/LLM-backed assessment behavior

This allows gradual rollout.

### 5. Tutor Context Integration

The tutor should receive structured concept diagnostics directly.

For supported domains, prompt context should include:

- `weak_concepts`
- `blocked_dependencies`
- `error_patterns`
- `failed_steps`
- `target_outcomes`
- `deterministic_truth_available`
- `diagnostic_confidence`

This will materially improve specificity of tutor responses without making prompt logic brittle.

### 6. Coach Integration

Current coach urgency is already stronger than simple chapter weakness, because it includes:

- competence gap
- syllabus weighting
- overdue/new SRS pressure
- ML risk
- semantic drift
- chapter flow and prerequisite boosts

The missing improvement is not “make the coach semantic for the first time.” The improvement is:

- make coach aggregation concept-aware

Recommended direction:

- compute concept-level urgency
- aggregate upward into chapter urgency
- use concept centrality and dependency blocking as modifiers

Suggested formula:

```text
concept_priority =
  mastery_gap
  * exam_weight
  * centrality
  * dependency_block_factor
  * error_recurrence_factor
  * recency_decay
```

Then chapter urgency becomes:

- sum or weighted blend of concept priorities
- not only chapter-level competence and due-state

### 7. Autopilot Integration

Do not expand the action list first.
Improve the evidence behind existing actions first.

Current actions such as:

- `weak_drill_start`
- `drill_start`
- `review_start`
- `interleave_start`

can remain unchanged at the UI surface.

What should change is the evidence payload:

```json
{
  "action": "weak_drill_start",
  "topic": "Groups",
  "target_concepts": ["f7.goodwill.basic"],
  "reason": "Repeated omit_nci and pre_post_mix errors",
  "confidence": 0.91
}
```

This preserves existing action discipline while making the underlying intelligence sharper.

## Solver Strategy

### What To Support First

Start with bounded procedural domains:

- `FM`: NPV, WACC, CAPM, working capital
- `F7/FR`: goodwill, NCI, group retained earnings, basic consolidation adjustments

Why:

- explicit formulas or stable procedural steps
- high recurrence
- clear error taxonomies
- deterministic validation is realistic

### What Not To Support First

Do not start with:

- open-ended discursive standards interpretation
- full free-form Section C narrative grading
- broad unstructured “solve any accounting scenario” pipelines

Those require either very large symbolic systems or more probabilistic grading, neither of which is the right first milestone.

## Deterministic Evaluation Pipeline

For supported procedural items:

1. `Question typing`
   - classify item as computational, stepwise procedural, conceptual short answer, or discursive

2. `Concept mapping`
   - map to concept IDs and candidate template refs

3. `Input extraction`
   - obtain template inputs from authored question metadata or structured parsing

4. `Truth generation`
   - run template `solve()`

5. `Learner comparison`
   - compare final answer
   - compare intermediate values
   - compare step order
   - detect omissions and sign errors

6. `Diagnostic classification`
   - emit `error_patterns`
   - emit `failed_steps`
   - emit confidence

7. `Adaptive propagation`
   - update learner profile
   - inform tutor follow-up
   - inform coach prioritization
   - inform autopilot targeting

## Question Authoring Requirements

To make deterministic evaluation reliable, supported question items should gain richer metadata.

Example:

```json
{
  "question": "Calculate goodwill on acquisition...",
  "chapter": "Groups",
  "outcome_ids": ["B3a"],
  "concept_ids": ["f7.goodwill.basic"],
  "template_ref": "acca_f7.consolidation.goodwill_v1",
  "template_inputs": {
    "consideration": 120000,
    "nci": 30000,
    "net_assets": 100000
  }
}
```

For the first phase, prefer authored metadata over trying to infer everything from free text.

Inference can be added later as a convenience layer, not as the source of truth.

## Backward Compatibility

Backward compatibility is mandatory.

Rules:

- existing modules must continue working without explicit concept metadata
- existing questions must continue working without template metadata
- unsupported items must fall back to the current assessment path
- tutor and autopilot must continue functioning when deterministic diagnostics are absent

This implies a layered capability model:

- Level 0: current behavior
- Level 1: explicit concept mapping only
- Level 2: deterministic truth available
- Level 3: stepwise deterministic diagnosis available

## Rollout Plan

### Phase 1: Concept Schema Upgrade (✅ Done)

The concept definitions live in `studyplan/domain_reasoning/concepts.py` as `BUILTIN_CONCEPTS` (a hardcoded dict of FM concepts). This replaced the original plan of extending module JSON with concept metadata. Key differences from the original proposal:

- No module JSON extension — concepts are code-defined
- No centrality field — not needed for the first implementation
- Dependency edges are encoded in `_OUTPUT_SLOT_GROUPS` and concept `requires`/`provides` fields

Future work: extend module JSON with explicit concept metadata for user-authored modules.

### Phase 2: Contract And Profile Enrichment (✅ Done)

The original proposal to add `concept_ids`, `error_patterns`, `failed_steps`, etc. to assessment/profile artifacts has been implemented:

- `TutorPracticeItem` — added `concept_ids`, `template_ref`, `template_inputs`
- `TutorAssessmentResult` — added `concept_ids`, `template_ref`, `failed_steps`, `error_patterns`, `diagnostic_confidence`
- `TutorLearnerProfileSnapshot` — added `weak_concept_ids_top`, `concept_error_patterns`

All fields include `to_dict()`/`from_dict()` serialization. The reasoning engine produces `ReasoningTrace` objects which are merged into `TutorAssessmentResult` by the assessment service.

### Phase 3: First Deterministic Template Slice (✅ Done — expanded scope)

Implemented all 10 FM concepts instead of the proposed 2–3:

| Concept | File |
|---|---|
| NPV | `domains/acca_fm/npv.py` |
| WACC | `domains/acca_fm/wacc.py` |
| CAPM | `domains/acca_fm/capm.py` |
| IRR | `domains/acca_fm/irr.py` |
| Payback | `domains/acca_fm/payback.py` |
| ARR | `domains/acca_fm/arr.py` |
| Cash Conversion Cycle | `domains/acca_fm/ccc.py` |
| EOQ | `domains/acca_fm/eoq.py` |
| Gearing | `domains/acca_fm/gearing.py` |
| Cost of Equity (DVM) | integrated via gearing |

F7/FR consolidation (goodwill, NCI, group retained earnings) remains future work.

### Phase 4: Practice Loop Integration (✅ Done)

Deterministic evaluation path is connected to the practice loop through `DeterministicTutorAssessmentService._assess_domain_item()`:

1. When a practice item has `template_ref` and the assessment service has a `domain_reasoner` configured, the assessment calls `reason_question()` via the engine's `domain_reason_question()` method.
2. The deterministic truth is computed and compared against the learner's submitted answer.
3. Step-level diagnostics (`failed_steps`, `error_patterns`, `diagnostic_confidence`) are merged into the `TutorAssessmentResult`.
4. `InMemoryTutorLearnerModelStore.note_assessment()` tracks concept error patterns per concept ID and maintains `weak_concept_ids_top`.

The integration point in `studyplan_app.py._get_practice_loop_controller()` passes `self.engine.domain_reason_question` as the `domain_reasoner` callback.

Limitations:
- Only final numeric answer comparison (no step-by-step learner working comparison yet)
- Requires explicit `template_ref` on the practice item (no automatic concept detection during practice)
- Only wired for the deterministic (non-LLM) assessment path; the `AITutorAssessmentService` path does not include domain reasoning

### Phase 5: Tutor Context Upgrade (✅ Partial)

`_build_ai_tutor_learner_profile_brief()` in `studyplan_app.py` now surfaces:
- `weak_concept_ids_top` as "Weak domain concepts"
- `failed_steps` and `diagnostic_confidence` in "Most recent assessed response"

These appear in the `planner_brief` section of the tutor prompt, enabling the LLM to reference specific concept-level weaknesses.

Not yet implemented: practice item planning context injection, post-assessment feedback generation using concept diagnostics.

### Phase 6: Coach And Autopilot Upgrade (✅ Partial — Autopilot Done)

Concept diagnostics (`weak_concept_ids_top`, `concept_error_summary`) now flow through the autopilot pipeline:

1. **`_build_local_ai_context_packet()`** — Extracts `weak_concept_ids_top` and `concept_error_summary` from the learner profile via `TutorWorkspaceState.practice_learner_profile()` with fallback to `InMemoryTutorLearnerModelStore.get_or_create_profile()`.
2. **`_format_local_ai_context_block()`** — Renders concept diagnostics as a "Concept diagnostics: Weak concepts: ID1, ID2 | ID3 (errors: tag1,tag2)" line in the context block.
3. **`_build_ai_tutor_autopilot_snapshot()`** — Passes `weak_concept_ids_top` and `concept_error_summary` through the snapshot dict (serialized into the LLM prompt payload via `json.dumps`).
4. **`_derive_ai_tutor_action_evidence()`** — Adds `weak_concepts=ID1,ID2` and `concept_errors=ID1(N)|ID2(M)` evidence lines when the action is `weak_drill_start` or `drill_start`.
5. **`_build_ai_tutor_fallback_action()`** — Includes concept IDs in the fallback reason string (e.g., "weak concepts: fm.npv, fm.wacc") and triggers weak_drill_start when weak concepts exist even without chapter-level weak topics.

The LLM now sees concept diagnostics in two places:
- The formatted `learning_context` text block (rendered by `_format_local_ai_context_block`)
- The raw `weak_concept_ids_top` and `concept_error_summary` JSON keys in the snapshot payload

Not yet implemented:
- Coach urgency (`engine.get_daily_plan`, `engine.top_recommendations`) — operates at chapter-level only; engine does not have access to concept-level learner profile data
- Coach pick; concept-level error pattern aggregation

### Phase 7: Authoring And Tooling (📋 Not started)

## Testing Strategy

This feature should be test-heavy and deterministic.

### Unit Tests

For each template:

- solve correct scenarios
- verify edge cases
- verify sign conventions
- verify rounding policy
- verify error classification rules

### Contract Tests

Ensure new optional fields serialize and deserialize safely:

- module metadata
- assessment results
- learner profiles
- session state

### Engine Tests

Cover:

- explicit concept graph import
- fallback synthesis
- dependency edge handling
- concept-aware routing

### Practice Loop Tests

Cover:

- supported template item path
- unsupported item fallback path
- learner profile updates from deterministic diagnostics

### Prompt Context Tests

Cover:

- tutor context includes weak concepts/error patterns/failed steps
- autopilot snapshot includes structured concept evidence when available
- degradation path remains stable when unavailable

### KPI / Regression Tests

Add targeted benchmarks for:

- diagnostic precision on supported solver domains
- consistency of concept-level remediation suggestions
- no regression in current tutor/autopilot behavior when deterministic layer is absent

## Risks

### 1. Overgrowth In Engine Or App Layers

Risk:

- solver logic leaks into `studyplan_engine.py` or `studyplan_app.py`

Mitigation:

- keep domain reasoning in `studyplan/domain_reasoning/`
- expose narrow service interfaces upward

### 2. Metadata Burden

Risk:

- concept and template authoring becomes too expensive

Mitigation:

- start with small high-value concept sets
- allow graph synthesis fallback
- require authored metadata only for solver-supported items

### 3. False Precision

Risk:

- deterministic classifier emits overconfident but wrong diagnostics

Mitigation:

- carry `diagnostic_confidence`
- retain fallback heuristic behavior
- require tests per error pattern

### 4. Prompt Bloat

Risk:

- tutor/autopilot prompts become overloaded with diagnostic detail

Mitigation:

- inject only top-N concept diagnostics
- summarize repeated patterns
- keep raw truth structures out of prompt unless needed

## Non-Goals

This architecture does not attempt, initially, to:

- solve arbitrary free-form exam questions
- fully automate discursive accounting judgment evaluation
- replace the tutor with a symbolic reasoning engine
- remove the current LLM-based pedagogical layer

The first goal is narrower and higher leverage:

- deterministic diagnosis for supported procedural concepts

## Recommended First Slice

If the goal is fastest path to reliable execution, start with `FM`:

- `npv`
- `wacc`

If the goal is strongest product differentiation for this app’s current syllabus direction, start with `F7/FR`:

- `goodwill`
- `NCI`
- `group retained earnings`

My engineering preference is:

1. prove the architecture with `FM.npv`
2. add `FM.wacc`
3. then implement `F7.goodwill`

Reason:

- easier deterministic parsing and validation
- faster iteration on contracts and evaluator interfaces
- lower ambiguity during first rollout

## Final Recommendation

The codebase does not need a separate “AI solver system.”

It needs:

- explicit concept semantics
- executable templates for supported domains
- structured deterministic diagnostics
- concept-aware propagation into learner state, tutor context, coach policy, and autopilot evidence

That path fits the existing architecture and strengthens its best qualities:

- local-first behavior
- deterministic control
- GTK-free domain/runtime logic
- strong testability

If implemented this way, the system will stop being merely good at adaptation around content and start becoming good at reasoning within content.
