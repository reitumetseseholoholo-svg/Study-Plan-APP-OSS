# Discovery Notes

## Evidence Repository for the Cognitive Runtime Extraction

**Branch:** `discovery-cognitive-runtime`
**Baseline commit:** `2766d48`

---

## Phase 0 — Evidence Preservation

Three independent process template implementations exist as of this branch
creation.  Each was built without knowledge of the others' internal
lifecycle.  This makes them valid "fossils" — empirical data points for
archaeological extraction.

---

## Phase 1 — Architectural Archaeology: Comparison Matrix

### 1. Lifecycle Phase Inventory

Each algebra was decomposed into its execution phases.  A `✓` means the
phase is explicitly implemented; `—` means it is absent or trivial.

| Phase | Computation | Classification | Evaluation |
|-------|-------------|---------------|------------|
| DECLARE | `declare_formula()` | `declare_concept()` | `declare_process(type="evaluation")` |
| INITIALIZE | Build solver closure | Build `ctx` + `path=[]` | Build `scores=0.0` + `contrib=[]` |
| VALIDATE | `param_kinds` → NaN | Non-numeric filter | Score-range clamp |
| TRANSITION | `_substitute_and_eval()` | `_traverse()` branch eval | Weighted-score accumulate |
| TERMINATE | Result produced | Leaf reached | All criteria processed |
| TRACE | `steps = [{value, formula}]` | `path = [{question, value, match}]` | `contributions = [{criterion, cand, score, weight}]` |
| DIAGNOSE | `evaluate_steps()`, `classify_errors()` | Same | Same |
| EXPLAIN | Expression with values | `classification_path` questions | `justification` top-5 drivers |
| RETURN | `{concept_id, result, inputs, is_nan, steps}` | Same + `classification_path` | Same + `judgment, ranked, confidence, entropy` |

**Observation:** All three implement every phase except VALIDATE (classification
skips it silently) and DIAGNOSE/EXPLAIN (computation has the weakest
version).  The lifecycle is universal.

---

### 2. Candidate Abstraction Matrix

For each *concept* that appears in ≥2 algebras, we evaluate the four
promotion tests.  A candidate may be promoted to the runtime only if all
four pass.

**Test definitions:**

| Test | Question | Pass condition |
|------|----------|---------------|
| **Behavioral Identity** | Do ≥2 algebras express equivalent behavior? | Same logical operation, even if names differ |
| **Semantic Identity** | Does it express the same *concept*? | Conceptually identical, not just structurally similar |
| **Evolution Identity** | Would both algebras have evolved it independently? | Removing the common concept would force re-invention in each |
| **Removal Test** | Does its absence force duplication? | Without it, each algebra must reimplement it |

#### Candidate A: `concept_id` identity

| Test | Result |
|------|--------|
| Behavioral | ✓ All three stamp `concept_id` on result |
| Semantic | ✓ The concept identity is the same idea |
| Evolution | ✓ Each algebra needs to identify itself |
| Removal | ✓ Without it, caller cannot route results |
| **Promote?** | **YES** → runtime owns `concept_id` binding |

#### Candidate B: Input snapshot (provenance)

| Test | Result |
|------|--------|
| Behavioral | ✓ All three return `inputs` as a copy of the original input dict |
| Semantic | ✓ Provenance — what inputs produced this result |
| Evolution | ✓ Every process needs to record what it was asked |
| Removal | ✓ Without it, caller cannot audit or replay |
| **Promote?** | **YES** → runtime owns `inputs` capture |

#### Candidate C: `is_nan` / null guard

| Test | Result |
|------|--------|
| Behavioral | ✓ All three have `is_nan` or equivalent null result |
| Semantic | ✓ Result validity indicator |
| Evolution | ✓ Every process needs an "I don't know" signal |
| Removal | ✓ Without it, callers must infer validity from result type |
| **Promote?** | **YES** → runtime owns validity flag |

#### Candidate D: Steps / trace collection

| Test | Result |
|------|--------|
| Behavioral | ✓ All three collect an ordered list of step dicts |
| Semantic | Partial — trace semantics differ: computation=formula steps, classification=decision path, evaluation=criterion contributions |
| Evolution | ✓ Each would independently reify its execution trace |
| Removal | ✓ Without it, diagnostics and explanation have no input |
| **Promote?** | **YES, with caveat** — runtime owns the *trace container* and the *immutable contract*, but the step schema is algebra-specific. Runtime defines `ExecutionTrace` as an immutable sequence. Algebras define step fields. |

#### Candidate E: `evaluate_steps()` signature

| Test | Result |
|------|--------|
| Behavioral | ✓ All three: `evaluate_steps(learner_steps, truth) → List[{step_id, expected, actual, match}]` |
| Semantic | ✓ Comparing learner steps against ground truth is identical across algebras |
| Evolution | ✓ Each algebra needs student-facing evaluation |
| Removal | ✓ Without it, each algebra reimplements the same comparison loop |
| **Promote?** | **YES** → runtime owns `evaluate_steps()` dispatch and result envelope |

#### Candidate F: `classify_errors()` signature

| Test | Result |
|------|--------|
| Behavioral | ✓ All three: `classify_errors(learner_steps, truth) → List[str]` |
| Semantic | ✓ Error categorization is same conceptual operation |
| Evolution | ✓ Each algebra needs to tell the tutor what went wrong |
| Removal | ✓ Without it, each algebra reimplements the same iteration logic |
| **Promote?** | **YES** → runtime owns `classify_errors()` dispatch. Tags are algebra-specific but the method contract is shared. |

#### Candidate G: Transition loop (iteration)

| Test | Result |
|------|--------|
| Behavioral | Computation: no loop (1 step). Classification: branch loop. Evaluation: criteria loop |
| Semantic | ✗ Computation has no iteration. The "loop" is not universal |
| Evolution | — |
| Removal | — |
| **Promote?** | **NO** — fails Semantic Identity. Computation proves a algebra can be single-step. Loop is algebra-specific. |

#### Candidate H: Validation

| Test | Result |
|------|--------|
| Behavioral | Computation: param check → NaN. Classification: silent skip. Evaluation: range clamp |
| Semantic | ✗ Completely different validation semantics |
| Evolution | ✗ Classification proves "no validation" is a valid approach |
| Removal | — |
| **Promote?** | **NO** — fails Semantic and Evolution Identity. Validation is algebra-specific. |

#### Candidate I: Explanation

| Test | Result |
|------|--------|
| Behavioral | Computation: formula display. Classification: question path. Evaluation: justification drivers |
| Semantic | ✗ Each produces a different type of explanation |
| Evolution | ✗ Each algebra's explanation is tied to its domain |
| Removal | Each could live without explanations (degrade to raw result only) |
| **Promote?** | **NO** — fails all four tests partially. Runtime should provide an *optional hook* but not own the concept. |

#### Candidate J: Confidence / certainty

| Test | Result |
|------|--------|
| Behavioral | Evaluation: score gap. Classification: N/A (hard yes/no). Computation: N/A (deterministic) |
| Semantic | ✗ Only Evaluation has it |
| Evolution | ✗ Not universal |
| Removal | — |
| **Promote?** | **NO** — appears in only one algebra. |

#### Candidate K: Result envelope shape

| Test | Result |
|------|--------|
| Behavioral | All three return a dict with `concept_id`, `result`, `inputs`, `is_nan`, `steps`. Evaluation adds more fields |
| Semantic | ✓ The common subset is identical |
| Evolution | ✓ Each needs to return these to be useful |
| Removal | ✓ Without a common envelope, caller must handle each algebra differently |
| **Promote?** | **YES** → runtime owns the common result envelope. Algebras extend it with type-specific fields. |

#### Candidate L: Execution context / state object

| Test | Result |
|------|--------|
| Behavioral | Computation: solver closure state. Classification: `ctx + path`. Evaluation: `scores + contributions` |
| Semantic | ✗ The *shape* of state is completely different per algebra |
| Evolution | ✗ Each algebra's state is intrinsic to its transition logic |
| Removal | — |
| **Promote?** | **NO** for a shared state class. But the *concept* of "process state exists" is universal. Runtime owns the *interface* `ProcessState` (empty marker). Algebras define concrete state classes. |

---

### 3. Promotion Summary

| Candidate | Promote? | Runtime owns |
|-----------|----------|-------------|
| `concept_id` identity | **YES** | Concept binding |
| Input snapshot | **YES** | Provenance capture |
| `is_nan` / validity | **YES** | Result validity guard |
| Trace collection | **YES** | `ExecutionTrace` immutable container |
| `evaluate_steps()` | **YES** | Method dispatch + result envelope |
| `classify_errors()` | **YES** | Method dispatch (tags are algebra-specific) |
| Transition loop | **NO** | Algebra-specific |
| Validation | **NO** | Algebra-specific |
| Explanation | **NO** | Optional hook only |
| Confidence | **NO** | Algebra-specific |
| Result envelope | **YES** | Common dict shape (`concept_id`, `result`, `inputs`, `is_nan`, `steps`) |
| Process state | **Partial** | Runtime owns `ProcessState` marker interface; algebras own concrete state |

---

### 4. Rejected Candidates (failed promotion tests)

| Candidate | Primary Failure | Evidence |
|-----------|----------------|----------|
| Transition loop | Semantic Identity | Computation is single-step; loop is not universal |
| Validation | Semantic + Evolution Identity | Each algebra validates differently or not at all |
| Explanation | All four | Different types; optional; domain-tied |
| Confidence | Behavioral Identity | Present in only one algebra (1/3) |
| Shared state shape | Semantic Identity | State is intrinsic to each algebra's transitions |

---

## Cross-Cutting Capabilities Discovered

| Capability | Appears In | Description |
|------------|-----------|-------------|
| `expected_information_gain` | DiagnosticTemplate (sketched), EvaluationTemplate | Simulate outcomes → compute entropy reduction |
| `confidence` | EvaluationTemplate (score gap), DiagnosticTemplate (MAP prob) | Result certainty |
| `is_nan` guard | All three | Result validity check |
| `inputs` preservation | All three | Provenance snapshot |
