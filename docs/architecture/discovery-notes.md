# Discovery Notes

## Evidence Repository for the Cognitive Runtime Extraction

This document preserves empirical evidence from the three implemented
cognitive algebras.  It is the raw material from which the Runtime
Constitution and the CognitiveRuntime will be extracted.

**Branch:** `discovery-cognitive-runtime`
**Baseline commit:** `2766d48`

---

## Phase 0 — Evidence Preservation

Three independent process template implementations exist as of this branch
creation.  Each was built without knowledge of the others' internal
lifecycle.  This makes them valid "fossils" — empirical data points for
archaeological extraction.

### Fossil 1: ComputationalAlgebra

| Property | Value |
|----------|-------|
| **File** | `studyplan/domain_reasoning/formula_registry.py` |
| **Class** | `ExpressionTemplate` (lines 358–447) |
| **Declaration** | `declare_formula()` → `_declare_expression_concept()` |
| **Runtime class** | None standalone; inlined in `ExpressionTemplate.solve()` |
| **Signature** | `(Inputᵢ) → Result` |
| **State mgmt** | Local variables in solve(); no persistent state |
| **Transition** | Single `solver(**inputs)` call via `_substitute_and_eval()` |
| **Termination** | Immediate after result |
| **Trace** | `steps = [{step_id, value, formula}]` |
| **Diagnostics** | `evaluate_steps`: tolerance-match. `classify_errors`: `{step_id}_mismatch` |
| **Explanation** | Display expression with substituted values |
| **Validation** | `param_kinds` type check → NaN |

### Fossil 2: ClassificationAlgebra

| Property | Value |
|----------|-------|
| **File** | `studyplan/domain_reasoning/concept_types/classification_concept.py` |
| **Class** | `ClassificationTemplate` (lines 60–227) |
| **Declaration** | `declare_concept(type="classification")` |
| **Runtime class** | None standalone; inlined in `ClassificationTemplate.solve()` |
| **Signature** | `(Featureᵢ) → Label` |
| **State mgmt** | `ctx` (numeric-only input subset) + `path` (decision trace) |
| **Transition** | `_traverse()` — recursive tree walk; one branch per call |
| **Termination** | Leaf reached (`node.result is not None`) or no match |
| **Trace** | `path = [{question, value, matched_condition}]` |
| **Diagnostics** | `evaluate_steps`: exact string match. `classify_errors`: `classification_mismatch` + `wrong_category_{truth}` |
| **Explanation** | `classification_path` — ordered list of question texts |
| **Validation** | Silent non-numeric filter |

### Fossil 3: EvaluationAlgebra

| Property | Value |
|----------|-------|
| **File** | `studyplan/domain_reasoning/process/evaluation.py` |
| **Class** | `EvaluationTemplate` (lines 70–345) |
| **Declaration** | `declare_process(type="evaluation")` |
| **Runtime class** | None standalone; inlined in `EvaluationTemplate.solve()` |
| **Signature** | `(Criterionᵢ → {Candidateⱼ → Score}) → {Candidateⱼ → Rank}` |
| **State mgmt** | `scores` dict + `contributions` list (accumulated over criteria loop) |
| **Transition** | Per-criterion: `scores[c] += norm_weight * clamp(raw)` |
| **Termination** | All criteria processed (linear pass) |
| **Trace** | `contributions = [{criterion, candidate, weight, score, weighted_contribution}]` |
| **Diagnostics** | `evaluate_steps`: string match. `classify_errors`: `wrong_judgment`, `missing_criterion`, `over/under_weighted_criterion` |
| **Explanation** | `justification` — top 5 criteria by weighted impact |
| **Validation** | Score clamping to `criterion.score_range` |

---

## Cross-Cutting Capabilities Discovered

| Capability | Appears In | Description |
|------------|-----------|-------------|
| `expected_information_gain` | DiagnosticTemplate (sketched), EvaluationTemplate | Simulate outcomes of an observation → compute entropy reduction |
| `confidence` | EvaluationTemplate (score gap), DiagnosticTemplate (MAP prob) | How certain is the result? |
| `is_nan` guard | All three | Result validity check |
| `inputs` preservation | All three | Provenance snapshot |

---

## Rejected Candidates (failed promotion tests)

*To be filled during Phase 1.*

| Candidate | Rejected by | Why |
|-----------|-------------|-----|
| | | |
