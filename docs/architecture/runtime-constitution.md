# Runtime Constitution

## Ownership Boundaries & Falsification Criteria for the Cognitive Process Runtime

*Derived from empirical comparison of three independent cognitive algebras
(Computation, Classification, Evaluation).  See `discovery-notes.md` for
the raw evidence and promotion test matrix.*

---

## Principles

1. **Discovery over Invention** — No abstraction is designed.  It is
   admitted only when it passes all four promotion tests against ≥2
   independent algebras.
2. **Empirical Warrant** — Every architectural claim cites specific lines
   of evidence from the fossil records.
3. **Falsification Section** — Every owned concept includes "This is wrong
   if…" conditions.
4. **Compression Ratio** — Progress = code removed + concepts clarified.
5. **Trace is First-Class** — ExecutionTrace is immutable and central.

---

## Ownership

### Runtime Owns

#### 1. `concept_id` binding
Every result must identify which concept produced it.

- **Evidence:** All three algebras stamp `concept_id` on their return dict.
- **Falsified if:** An algebra exists that does not need to identify itself.

#### 2. Input provenance snapshot
Every result must carry a copy of its inputs for audit and replay.

- **Evidence:** All three return a copy of `inputs`.
- **Falsified if:** An algebra exists that intentionally discards inputs
  after processing them.

#### 3. Result validity flag (`is_nan`)
Every process produces a valid/invalid signal.

- **Evidence:** All three have `is_nan` or equivalent (computation: NaN
  guard; classification: `is_nan` on no-match; evaluation: always `False`
  but present).
- **Falsified if:** An algebra exists whose result channel does not need
  a validity indicator.

#### 4. `ExecutionTrace` container (immutable)
The runtime owns the trace *container* — an ordered, immutable sequence of
step records.  Step schema is algebra-specific.

- **Evidence:** All three collect step dicts.
- **Falsified if:** An algebra exists that produces no trace at all and
  cannot benefit from one.

#### 5. `evaluate_steps(learner_steps, truth) → List[{step_id, expected, actual, match}]`
The comparison loop and result envelope are runtime-owned.

- **Evidence:** All three implement identical signature.
- **Falsified if:** An algebra exists whose step evaluation cannot be
  expressed as comparison against a truth result.

#### 6. `classify_errors(learner_steps, truth) → List[str]`
The method signature and dispatch are runtime-owned.  Tag values are
algebra-specific.

- **Evidence:** All three implement identical signature.
- **Falsified if:** An algebra exists whose error classification cannot
  return a list of string tags.

#### 7. Common result envelope
Every `execute()` returns a dict containing at minimum: `concept_id`,
`result`, `inputs`, `is_nan`, `steps`.

- **Evidence:** All three produce this shape.  Evaluation extends it.
- **Falsified if:** An algebra exists that cannot express its result in
  this shape (would force a breaking schema change).

#### 8. `ProcessState` marker interface
The runtime owns the *concept* that a process has state.  It does NOT own
the state shape.

- **Evidence:** All three have state (solver closure, ctx+path, scores+contrib).
- **Falsified if:** An algebra exists that is genuinely stateless and
  a `ProcessState` abstraction would be meaningless overhead.

---

### Algebras Own (runtime provides hook only)

#### 1. Transition logic
The runtime provides a `transition(state) → state` hook.  Each algebra
implements its own transition function.

- **Rationale:** Computation is single-step; classification is conditional
  branching; evaluation is linear accumulation.  No shared semantics.

#### 2. Termination predicate
The runtime provides a `terminated(state) → bool` hook.  Each algebra
defines termination.

- **Rationale:** Computation terminates immediately; classification
  terminates on leaf; evaluation terminates after last criterion.

#### 3. Validation
The runtime provides an optional `validate(state) → List[str]` hook.
Algebras may implement or ignore it.

- **Rationale:** Classification proves that zero validation is valid.

#### 4. Explanation
The runtime provides an optional `explain(trace) → List[str]` hook.
Algebras may implement it.

- **Rationale:** Computation explanations are trivial.  Evaluation produces
  rich justifications.  The shape and necessity differ.

#### 5. Confidence
The runtime provides an optional `confidence(result) → float` hook.

- **Rationale:** Present in only 1 of 3 algebras.

---

### What Belongs Nowhere

| Concept | Reason for Rejection | Evidence |
|---------|---------------------|----------|
| Shared validation logic | Semantic Identity fail | Classification skips validation entirely |
| Shared state shape | Semantic Identity fail | State is intrinsic to each algebra's transitions |
| Shared transition loop | Semantic Identity fail | Computation proves single-step is valid |
| Shared explanation format | All four tests fail | Each algebra's explanation is domain-tied |

---

## Runtime Interface (Derived)

```python
class CognitiveRuntime(ABC):
    """Drives any cognitive algebra through the invariant lifecycle."""

    def execute(
        self,
        concept_id: str,
        inputs: dict[str, Any],
    ) -> dict[str, Any]:
        """Run one complete process lifecycle.

        Template method calling algebra-specific hooks:
        - initialize(inputs)     → state
        - validate(state)        → state  (optional)
        - transition(state)      → state  (called until terminated)
        - terminated(state)      → bool
        - collect_trace(state)   → ExecutionTrace
        - compute_diagnostics(trace, truth)  → List[str]
        - generate_explanation(trace)        → List[str]  (optional)
        """
        state = self.initialize(concept_id, inputs)
        state = self.validate(state) or state
        while not self.terminated(state):
            state = self.transition(state)
        trace = self.collect_trace(state)
        return self._assemble_result(concept_id, inputs, trace, state)

    def evaluate_steps(
        self,
        learner_steps: list[dict],
        truth: dict,
    ) -> list[dict]:
        """Compare learner steps against ground truth.

        Default implementation iterates learner steps and compares each
        against truth["result"].  Algebras may override for custom matching.
        """
        ...

    def classify_errors(
        self,
        learner_steps: list[dict],
        truth: dict,
    ) -> list[str]:
        """Categorize learner errors.

        Default returns empty list.  Algebras override to produce tags.
        """
        return []
```

### Hook Definitions

| Hook | Required? | Signature | Called by |
|------|-----------|-----------|-----------|
| `initialize` | Yes | `(concept_id, inputs) → ProcessState` | `execute()` |
| `validate` | No | `(state) → ProcessState | None` | `execute()`, after init |
| `transition` | Yes | `(state) → ProcessState` | `execute()`, loop |
| `terminated` | Yes | `(state) → bool` | `execute()`, loop guard |
| `collect_trace` | Yes | `(state) → ExecutionTrace` | `execute()`, after loop |
| `explain` | No | `(trace) → List[str]` | `execute()`, optional |

---

## Falsification Criteria

| Claim | Falsified If |
|-------|-------------|
| The lifecycle has 8 phases | A new algebra requires a phase not in the set |
| `is_nan` is universal | A new algebra has no concept of invalid results |
| `evaluate_steps` signature is universal | A new algebra needs ≥2 truth values to evaluate |
| `classify_errors` returns `List[str]` | A new algebra needs structured error objects |
| Transition loop is algebra-specific | A new algebra has the same transition semantics as an existing one |
| Validation is algebra-specific | Two algebras have identical validation that could share code |
| Explanation is algebra-specific | Two algebras have identical explanation format |
| Trace container is universal | A new algebra cannot express its steps in an ordered sequence |

---

## Amendment Process

1. Any algebra author may propose promoting a new abstraction to the runtime.
2. The proposal must include promotion test results for ≥2 algebras.
3. If the tests pass and all four are satisfied, the abstraction is admitted.
4. If runtime interface changes are required, all existing algebras must
   be updated in the same commit.
5. Falsification criteria must be added for every new abstraction.

---

## Legacy Deletion Checklists

Before deleting any legacy template class, ALL items in the corresponding
checklist must pass for ≥2 independent input sets.

### ExpressionTemplate Safe Deletion

``ExpressionTemplate`` (``studyplan/domain_reasoning/formula_registry.py``)
is the first collapse target because computation is the simplest algebra
and has the least semantic drift risk.

#### Preconditions

- [ ] ``tests/test_computation_equivalence.py`` passes at 100% — this is
      the specification oracle.  Every test runs both
      ``ExpressionTemplate`` and ``CognitiveRuntime → ComputationProcess
      → interpreter``, asserting byte-level identity for all three public
      methods (``solve``, ``evaluate_steps``, ``classify_errors``).
- [ ] ``tests/test_cognitive_runtime.py`` computation identity tests pass
      (proves the runtime + process + interpreter contract is stable).
- [ ] All legacy tests that import ``ExpressionTemplate`` are updated to
      use the runtime path OR are deleted.
- [ ] ``declare_formula`` (the sole production entry point) delegates to
      the runtime path, not to ``ExpressionTemplate``.
- [ ] The adapter function ``legacy_computation_adapter(inputs) →
      {concept_id, result, inputs, is_nan, steps}`` is verified in
      production for ≥50 random input sets across ≥3 distinct formulas.
- [ ] ``grep -r "ExpressionTemplate"`` returns only:
      - the definition in ``formula_registry.py`` (to be deleted)
      - the equivalence harness (to be updated to remove import of
        the now-deleted class)
      - the adapter function (to be removed afterward)
- [ ] Performance benchmark: runtime path is within ±10% of legacy path
      for 1000 repeated calls (no regression from the trace allocation).

#### Deletion procedure

1. Remove ``ExpressionTemplate`` class definition from ``formula_registry.py``.
2. Remove all imports of ``ExpressionTemplate`` outside of
   ``test_computation_equivalence.py``.
3. In ``test_computation_equivalence.py``, replace ``ExpressionTemplate``
   imports with direct solver calls (since ``declare_formula`` now uses
   the runtime, the template intermediary is gone).
4. Remove the adapter function (no longer needed — runtime is the only path).
5. Run ``pytest -q tests/test_computation_equivalence.py`` — should still
   pass (tests now compare runtime vs runtime via different constructors,
   confirming the runtime path is self-consistent).
6. Run full test suite — 0 new failures.
