# Cognitive Algebras

## A Lifecycle Extracted, Not Designed

Three process templates were implemented independently for three different
cognitive classes.  None was built from a shared base class beyond the thin
`ProcessTemplate` ABC (three methods).  Yet all three converged on the same
implicit lifecycle structure.

This document extracts that invariant — not as a prescription, but as an
empirical discovery.  The lifecycle below was not designed first.  It was
found emergent in all three implementations.

---

## The Invariant Lifecycle

```
┌─────────────────────────────────────────────────┐
│                  DECLARE                          │
│   declare_process(id, type="computation"          │
│                          | "classification"       │
│                          | "evaluation")          │
│        ↓                                          │
│   Binds config + template to concept_id          │
└─────────────────────────────────────────────────┘
        ↓
┌─────────────────────────────────────────────────┐
│              1. INITIALIZE                       │
│   Turn raw inputs into structured state          │
│                                                   │
│   Computation:  kwargs → solver closure          │
│   Classification: ctx = {numeric inputs}; path=[]│
│   Evaluation:    scores = {cand: 0.0}; contrib=[]│
└─────────────────────────────────────────────────┘
        ↓
┌─────────────────────────────────────────────────┐
│              2. VALIDATE (optional)               │
│   Reject malformed inputs against schema          │
│                                                   │
│   Computation:  param_kinds check → NaN          │
│   Classification: filter non-numeric, skip       │
│   Evaluation:    clamp scores to score_range     │
└─────────────────────────────────────────────────┘
        ↓
┌─────────────────────────────────────────────────┐
│              3. TRANSITION (loop)                 │
│   Apply one operation; repeat until terminated   │
│                                                   │
│   Computation:  evaluate expression (1 step)     │
│   Classification: evaluate condition → follow    │
│                  branch; loop per decision node  │
│   Evaluation:    evaluate criterion → aggregate  │
│                  weighted score per candidate    │
└─────────────────────────────────────────────────┘
        ↓
┌─────────────────────────────────────────────────┐
│              4. TERMINATE                         │
│   Stop condition triggers                         │
│                                                   │
│   Computation:  result produced (or NaN)         │
│   Classification: leaf reached (or no match)     │
│   Evaluation:    all criteria processed          │
└─────────────────────────────────────────────────┘
        ↓
┌─────────────────────────────────────────────────┐
│              5. TRACE                             │
│   Collect provenance of the computation           │
│                                                   │
│   Computation:  steps = [{value, formula}]       │
│   Classification: path = [{question, value}]     │
│   Evaluation:    contributions = [{criterion,     │
│                   candidate, score, weight}]      │
└─────────────────────────────────────────────────┘
        ↓
┌─────────────────────────────────────────────────┐
│              6. DIAGNOSE                          │
│   Compare trace against ground truth              │
│                                                   │
│   evaluate_steps(learner_steps, truth)            │
│   classify_errors(learner_steps, truth)           │
│                                                   │
│   All three templates implement both methods.     │
└─────────────────────────────────────────────────┘
        ↓
┌─────────────────────────────────────────────────┐
│              7. EXPLAIN (optional)                │
│   Generate human-readable justification           │
│                                                   │
│   Computation:  display expression with values   │
│   Classification: classification_path (questions)│
│   Evaluation:    justification (top 5 drivers)   │
└─────────────────────────────────────────────────┘
        ↓
┌─────────────────────────────────────────────────┐
│              8. RETURN                            │
│   Common result envelope                          │
│                                                   │
│   All return: {concept_id, result, inputs,        │
│                is_nan, steps, ...}                │
└─────────────────────────────────────────────────┘
```

---

## Three Instances of the Same Abstraction

### Computation (ExpressionTemplate)

| Phase | Implementation |
|-------|---------------|
| INITIALIZE | `solver(**inputs)` |
| VALIDATE | `math.isnan(result)` → `is_nan=True` |
| TRANSITION | `_substitute_and_eval()` — one step |
| TERMINATE | Result returned (single step) |
| TRACE | `steps = [{step_id, value, formula}]` |
| DIAGNOSE | `evaluate_steps`: tolerance-based comparison. `classify_errors`: `{step_id}_mismatch` tags |
| EXPLAIN | Display expression with substituted values |

**Algebra signature:** `(Inputᵢ) → Result` — a pure function.

### Classification (ClassificationTemplate)

| Phase | Implementation |
|-------|---------------|
| INITIALIZE | `ctx = {k: float(v) for k, v in inputs.items() if isinstance(v, (int, float))}`, `path = []` |
| VALIDATE | Skip non-numeric inputs silently |
| TRANSITION | `_traverse(node, ctx, path)` — evaluate `branch.condition` expression → follow branch or fall through |
| TERMINATE | Leaf node reached (`node.result is not None`) or no branch matched |
| TRACE | `path = [{question, value, matched_condition}]` |
| DIAGNOSE | `evaluate_steps`: exact string match. `classify_errors`: `classification_mismatch` + `wrong_category_{truth}` |
| EXPLAIN | `classification_path` — flat list of question strings visited |

**Algebra signature:** `(Featureᵢ) → Label` — a branching function.

### Evaluation (EvaluationTemplate)

| Phase | Implementation |
|-------|---------------|
| INITIALIZE | `scores = {candidate: 0.0}`, `contributions = []`, `total_weight` computed |
| VALIDATE | Clamp raw scores to `criterion.score_range` |
| TRANSITION | For each criterion: `score[c] += norm_weight * clamped(raw_score)` |
| TERMINATE | All criteria processed (ordered single-pass, not a convergence loop yet) |
| TRACE | `contributions = [{criterion, candidate, weight, score, weighted_contribution}]` |
| DIAGNOSE | `evaluate_steps`: judgment string match. `classify_errors`: `wrong_judgment`, `missing_criterion`, `over/under_weighted_criterion` |
| EXPLAIN | `justification` — top 5 criteria by `weighted_impact = norm_weight × (top_score - runner_up_score)` |

**Algebra signature:** `(Criterionᵢ → {Candidateⱼ → Score}) → {Candidateⱼ → Rank}` — a weighted comparison function.

---

## Cognitive Algebras: A Definition

A **Cognitive Algebra** is a tuple `(𝒮, 𝒯, τ, γ, δ, ε)` where:

| Symbol | Name | What it defines |
|--------|------|-----------------|
| 𝒮 | State space | The set of all possible internal states at any point in the process |
| 𝒯 | Transition space | The set of available operations (expressions, branches, criteria, etc.) |
| τ | Transition function | `τ: 𝒮 × 𝒯 → 𝒮` — apply one operation to advance state |
| γ | Termination predicate | `γ: 𝒮 → Bool` — has the process converged? |
| δ | Diagnostic function | `δ: Trace × Truth → List[ErrorTag]` — map to error classes |
| ε | Explanation function | `ε: Trace → List[Justification]` — generate reasons |

Each template is an implementation of one cognitive algebra.

```
declare_process(id, type="computation")     →  ComputationalAlgebra
declare_process(id, type="classification")  →  ClassificationAlgebra
declare_process(id, type="evaluation")      →  EvaluationAlgebra
```

---

## The Emergent Process Runtime

If the invariant lifecycle is real, then a single **Cognitive Process Runtime**
should be able to execute any cognitive algebra by driving it through the
generic loop:

```python
def execute(algebra, inputs):
    state = algebra.initialize(inputs)
    state = algebra.validate(state)
    while not algebra.terminated(state):
        state = algebra.transition(state)
    trace = algebra.collect_trace(state)
    result = algebra.assemble_result(trace)
    return result
```

With an optional diagnostic phase:

```python
def diagnose(algebra, learner_steps, truth):
    trace = algebra.collect_trace(truth)
    return {
        "step_evaluations": algebra.evaluate_steps(learner_steps, truth),
        "error_tags": algebra.classify_errors(learner_steps, truth),
        "explanation": algebra.generate_explanation(trace),
    }
```

**Key design constraint:** The runtime knows only about the invariant lifecycle
phases.  It does NOT know about expressions, branches, criteria, hypotheses,
or any domain concept.  Those belong to the algebra implementations.

---

## Active Cognition: EIG as a Cross-Cutting Capability

Expected Information Gain does not belong to any single algebra.  It's a
meta-operation: evaluate a candidate intervention and return the expected
reduction in uncertainty.

Two algebras already implement it:

- **DiagnosticTemplate** (Class III): EIG for observing a feature, computed
  by simulating posteriors over all possible evidence values.
- **EvaluationTemplate** (Class V): EIG for learning a criterion's scores,
  computed by simulating candidate-score vectors.

EIG is the first example of a **cross-cutting cognitive capability** — an
operation defined at the algebra level, not the template level.  Others might
include:

| Capability | Applies to | What it does |
|------------|-----------|-------------|
| `expected_information_gain` | Diagnosis, Evaluation | Which next observation maximally reduces uncertainty? |
| `counterfactual` | Evaluation, Explanation | What changes would flip the decision? |
| `confidence` | All algebras | How certain is the result? |
| `sensitivity` | Computation, Evaluation | Which input/weight most affects the output? |
| `transfer` | All algebras | Cross-domain similarity measurement |
| `abduction` | Diagnosis, Construction | What state would explain the observed trace? |

---

## What This Means for Architecture

### Previously

```text
declare_formula(...)  ← the architecture
```

This was a single-algebra system with no generalization path.

### Now

```text
declare_process(...)  ← the architecture

  ├── type="computation"       →  ComputationalAlgebra
  ├── type="classification"    →  ClassificationAlgebra
  ├── type="evaluation"        →  EvaluationAlgebra
  ├── type="diagnostic"        →  DiagnosticAlgebra (sketched)
  └── type="construction"      →  ConstructionAlgebra (future)
```

Different algebras. Same lifecycle. Same registry. Same result envelope.

### Rule (self-imposed)

> No new abstraction may enter the architecture unless at least two
> independent cognitive algebras require it.

This protects against:
- **Premature generalization**: Extracting a base class before the second
  algebra proves it necessary.
- **Over-engineering**: Building runtime features no algebra uses.
- **Architecture inflation**: Adding abstraction layers without empirical
  warrant.

Three algebras now exist.  The invariant lifecycle above has been demonstrated
three times.  The Cognitive Process Runtime is warranted.

---

## Testable Predictions

If the Cognitive Algebra model is correct, then:

1. **New algebras fit the same lifecycle.** The next cognitive class
   (e.g., Construction for essays / proofs) should naturally decompose
   into the same `initialize → validate → transition loop → terminate →
   trace → diagnose → explain → return` phases.

2. **The runtime is algebra-agnostic.** A single `execute(algebra, inputs)`
   function can drive any algebra without inspecting its internals.

3. **Cross-cutting capabilities compose.** `expected_information_gain` and
   `counterfactual` can be implemented once against the algebra contract
   and reused across all algebras that expose uncertainty.

4. **CISA is the algebra registry.** The Cognitive Instruction Set
   Architecture maps concept IDs to algebra instances, and the Cognitive
   Router selects the right algebra for the cognitive situation.
