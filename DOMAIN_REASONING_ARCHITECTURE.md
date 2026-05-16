# Domain Reasoning Architecture

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

## Proposed Package

Add a new package under `studyplan/`:

```text
studyplan/domain_reasoning/
  __init__.py
  concepts.py
  dependencies.py
  templates.py
  evaluator.py
  diagnostics.py
  planner.py
  domains/
    __init__.py
    acca_f7/
      __init__.py
      consolidation.py
      groups.py
      cashflow.py
    acca_fm/
      __init__.py
      npv.py
      wacc.py
      working_capital.py
```

This package should remain:

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

### Phase 1: Concept Schema Upgrade

Add:

- explicit module concept definitions
- dependency edges
- concept centrality field
- template references

Implementation notes:

- extend module loader and validation
- prefer explicit concepts when present
- retain current concept synthesis as fallback

### Phase 2: Contract And Profile Enrichment

Add to assessment/profile/session artifacts:

- `concept_ids`
- `primary_concept_id`
- `error_patterns`
- `failed_steps`
- `weak_concept_ids_top`
- `error_pattern_counts`

Implementation notes:

- keep old fields
- treat new fields as optional

### Phase 3: First Deterministic Template Slice

Implement one narrow domain end to end.

Recommended order:

1. `acca_fm.npv`
2. `acca_fm.wacc`
3. `acca_f7.consolidation.goodwill`

or reverse that order if product value is clearly F7-first.

Criteria for choosing first slice:

- stable formulas
- known error patterns
- frequent learner mistakes
- easy test oracle generation

### Phase 4: Practice Loop Integration

Add deterministic evaluation path for supported items:

- call template
- compare learner output
- emit structured diagnostics
- store results in learner profile

### Phase 5: Tutor Context Upgrade

Inject concept-level state into:

- tutor turn context
- practice item planning context
- post-assessment feedback generation

### Phase 6: Coach And Autopilot Upgrade

Use concept-aware aggregates to drive:

- coach prioritization bias
- drill targeting
- review suggestions
- autopilot justification

### Phase 7: Authoring And Tooling

Only after the end-to-end pattern is proven:

- add scripts to validate concept metadata
- add helper tools for template refs and dependency graphs
- add reporting for concept coverage and unsupported high-frequency topics

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
