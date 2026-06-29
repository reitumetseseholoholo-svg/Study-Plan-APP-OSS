"""Reasoning engine: compiles domain concepts into executable solution plans.

The engine reasons about *which* concepts a question involves, resolves
their transitive dependencies, orders them into an executable plan,
runs each step forwarding intermediate results downstream, and returns
a structured trace with diagnostics.

High-level flow::

    question
       │
       ▼
    detect_concepts()  ──►  target concept(s)
       │
       ▼
    _resolve_dependencies()  ──►  topological order (deps first)
       │
       ▼
    _compile_plan()  ──►  ordered PlanStep list
       │
       ▼
    _execute_plan()  ──►  ExecutionRecord per step
       │
       ▼
    ReasoningTrace  (result + diagnostics + trace)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import Any

from studyplan.domain_reasoning.concepts import (
    BUILTIN_CONCEPTS,
    detect_concepts,
)
from studyplan.domain_reasoning.templates import (
    TEMPLATE_REGISTRY,
    run_template,
)
from studyplan.domain_reasoning.diagnostics import (
    QuestionDiagnostic,
    format_error_summary,
)


# ---------------------------------------------------------------------------
# Phase 4: Input source quality weights
# ---------------------------------------------------------------------------


class InputSource(str, Enum):
    EXPLICIT = "explicit"
    INFERRED = "inferred"
    EXTRACTED = "extracted"
    GIVEN = "given"
    MISSING = "missing"


_INPUT_QUALITY: dict[str, float] = {
    "explicit": 1.0,
    "inferred": 0.85,
    "extracted": 0.70,
    "given": 0.60,
    "missing": 0.0,
}


# ---------------------------------------------------------------------------
# Phase 2: Output slot groups for multi-path resolution
# ---------------------------------------------------------------------------


def _build_slot_groups(
    concept_map: dict[str, Any] | None = None,
) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    source = concept_map if concept_map is not None else BUILTIN_CONCEPTS
    for cid, meta in source.items():
        for slot in meta.output_slots:
            groups.setdefault(slot, []).append(cid)
    return groups


_OUTPUT_SLOT_GROUPS: dict[str, list[str]] = _build_slot_groups()


def _find_alternatives(
    concept_id: str,
    concept_map: dict[str, Any] | None = None,
    slot_groups: dict[str, list[str]] | None = None,
) -> list[str]:
    """Concepts producing the same output slots, excluding *concept_id* itself."""
    source = concept_map if concept_map is not None else BUILTIN_CONCEPTS
    groups = slot_groups or _OUTPUT_SLOT_GROUPS
    meta = source.get(concept_id)
    if not meta:
        return []
    result: list[str] = []
    seen: set[str] = set()
    for slot in meta.output_slots:
        for alt_id in groups.get(slot, ()):
            if alt_id != concept_id and alt_id not in seen:
                seen.add(alt_id)
                result.append(alt_id)
    return result


# ---------------------------------------------------------------------------
# Public data types (extended for Phases 2–4)
# ---------------------------------------------------------------------------


@dataclass
class PlanStep:
    """A single step in the execution plan — *what* to compute and *how*."""

    concept_id: str
    template_ref: str
    label: str
    inputs: dict[str, Any]
    output_slots: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    skipped: bool = False
    expected_params: set[str] = field(default_factory=set)
    input_sources: dict[str, str] = field(default_factory=dict)
    # input_sources: param_name → "explicit"|"inferred"|"extracted"|"given"|"missing"


@dataclass
class ExecutionRecord:
    """Outcome of running one plan step."""

    concept_id: str
    success: bool
    label: str = ""
    result: float | None = None
    detailed_steps: list[dict[str, Any]] = field(default_factory=list)
    error_tags: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    skipped: bool = False
    input_source_quality: float = 0.0


@dataclass
class ReasoningTrace:
    """Full output of the reasoning engine — trace + diagnostics."""

    question: str
    target_concept_id: str | None = None
    concept_ids: list[str] = field(default_factory=list)
    givens: dict[str, Any] = field(default_factory=dict)
    plan: list[PlanStep] = field(default_factory=list)
    execution: list[ExecutionRecord] = field(default_factory=list)
    final_result: float | None = None
    confidence: float = 0.0
    diagnostic: QuestionDiagnostic | None = None

    @property
    def has_result(self) -> bool:
        return self.final_result is not None and self.confidence > 0

    @property
    def trace_summary(self) -> str:
        """Short human-readable summary."""
        if not self.execution:
            return "no reasoning possible"
        parts: list[str] = []
        if self.target_concept_id:
            parts.append(f"target: {self.target_concept_id}")
        parts.append(f"steps: {len(self.execution)}")
        successes = sum(1 for e in self.execution if e.success)
        parts.append(f"ok: {successes}")
        if self.final_result is not None:
            parts.append(f"result: {self.final_result:.4g}")
        if self.diagnostic:
            parts.append(format_error_summary(self.diagnostic))
        return " | ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable dict for pipeline integration."""
        return {
            "question": self.question,
            "target_concept_id": self.target_concept_id,
            "concept_ids": list(self.concept_ids),
            "final_result": self.final_result,
            "confidence": self.confidence,
            "has_result": self.has_result,
            "trace_summary": self.trace_summary,
            "execution": [
                {
                    "concept_id": e.concept_id,
                    "success": e.success,
                    "result": e.result,
                    "error_tags": list(e.error_tags),
                    "duration_ms": round(e.duration_ms, 2),
                    "skipped": e.skipped,
                    "input_source_quality": round(e.input_source_quality, 4),
                }
                for e in self.execution
            ],
            "diagnostic_error_tags": (list(self.diagnostic.all_error_tags) if self.diagnostic else []),
            "diagnostic_error_summary": (
                self.diagnostic.error_summary if self.diagnostic and self.diagnostic.error_summary else ""
            ),
        }


# ---------------------------------------------------------------------------
# Phase 1: Parameter key detection  (candidate-function probing)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=128)
def _get_expected_param_keys(
    concept_id: str,
    formula_decls: dict[str, Any] | None = None,
) -> set[str] | None:
    """Return the set of parameter names a concept's solver expects.

    If *formula_decls* is provided (a dict of concept_id → FormulaDecl),
    reads ``param_names`` directly from the declaration.  Otherwise uses
    the formula candidate function's first return dict as a schema.
    Returns ``None`` if no candidate is available.
    """
    # Fast path: read from FormulaDecl param_names
    if formula_decls is not None:
        decl = formula_decls.get(concept_id)
        if decl is not None and hasattr(decl, "param_names") and decl.param_names:
            return set(decl.param_names)
        return None

    from studyplan.numerical_solver import _FORMULA_CANDIDATES

    # -- Build a synthetic number pool rich enough to trigger every
    #    candidate function (including chain formulas with many percent params). --
    _pool = [
        {
            "value": 500.0,
            "raw": "500",
            "is_percent": False,
            "is_currency": False,
            "is_year_like": False,
            "is_negative": False,
        },
        {
            "value": 300.0,
            "raw": "300",
            "is_percent": False,
            "is_currency": False,
            "is_year_like": False,
            "is_negative": False,
        },
        {
            "value": 100.0,
            "raw": "100",
            "is_percent": False,
            "is_currency": False,
            "is_year_like": False,
            "is_negative": False,
        },
        {
            "value": 0.12,
            "raw": "12%",
            "is_percent": True,
            "is_currency": False,
            "is_year_like": False,
            "is_negative": False,
        },
        {
            "value": 0.08,
            "raw": "8%",
            "is_percent": True,
            "is_currency": False,
            "is_year_like": False,
            "is_negative": False,
        },
        {
            "value": 0.30,
            "raw": "30%",
            "is_percent": True,
            "is_currency": False,
            "is_year_like": False,
            "is_negative": False,
        },
        {
            "value": 0.06,
            "raw": "6%",
            "is_percent": True,
            "is_currency": False,
            "is_year_like": False,
            "is_negative": False,
        },
        {
            "value": 1.2,
            "raw": "120%",
            "is_percent": True,
            "is_currency": False,
            "is_year_like": False,
            "is_negative": False,
        },
        {
            "value": 0.60,
            "raw": "60%",
            "is_percent": True,
            "is_currency": False,
            "is_year_like": False,
            "is_negative": False,
        },
        {
            "value": 0.40,
            "raw": "40%",
            "is_percent": True,
            "is_currency": False,
            "is_year_like": False,
            "is_negative": False,
        },
    ]

    formula = concept_id.replace("fm.", "", 1) if concept_id.startswith("fm.") else concept_id
    candidate_fn = _FORMULA_CANDIDATES.get(formula)
    if candidate_fn is None:
        return None

    if formula == "irr":
        param_sets = candidate_fn(_pool)
    elif formula == "eoq":
        param_sets = candidate_fn(
            [
                {"is_percent": False, "value": 10000},
                {"is_percent": False, "value": 50},
                {"is_percent": False, "value": 2},
            ]
        )
    else:
        param_sets = candidate_fn(_pool)
    if param_sets:
        return set(param_sets[0].keys())
    return None


# ---------------------------------------------------------------------------
# Phase 4: Input assembly with source tracking
# ---------------------------------------------------------------------------


def _build_inputs_with_sources(
    concept_id: str,
    question: str,
    explicit_ref: str | None,
    explicit_inputs: dict[str, Any] | None,
    intermed: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    """Assemble inputs and track their provenance.

    Returns ``(inputs_dict, sources_dict)`` where ``sources_dict`` maps
    each param name → source tag.
    """
    expected = _get_expected_param_keys(concept_id)
    inputs: dict[str, Any] = {}
    sources: dict[str, str] = {}

    from studyplan.numerical_solver import _FORMULA_CANDIDATES, extract_numbers

    formula = concept_id.replace("fm.", "", 1) if concept_id.startswith("fm.") else concept_id
    candidate_fn = _FORMULA_CANDIDATES.get(formula)
    if candidate_fn is not None:
        nums = extract_numbers(question)
        param_sets = candidate_fn(nums)
        if param_sets:
            for k, v in param_sets[0].items():
                if k not in inputs:
                    inputs[k] = v
                    sources[k] = "extracted"

    # Intermediate slot values
    if expected is not None:
        for k, v in intermed.items():
            if k in expected and k not in inputs:
                inputs[k] = v
                sources[k] = "inferred"
    else:
        for k, v in intermed.items():
            if k not in inputs:
                inputs[k] = v
                sources[k] = "inferred"

    # Explicit inputs
    if concept_id == explicit_ref and explicit_inputs:
        for k, v in explicit_inputs.items():
            inputs[k] = v
            sources[k] = "explicit"

    # Filter to expected keys only
    if expected is not None:
        inputs = {k: v for k, v in inputs.items() if k in expected}
        sources = {k: v for k, v in sources.items() if k in expected}
        for k in expected:
            if k not in sources:
                sources[k] = "missing"

    return inputs, sources


def _build_inputs_for(
    concept_id: str,
    question: str,
    explicit_ref: str | None,
    explicit_inputs: dict[str, Any] | None,
    intermed: dict[str, Any],
) -> dict[str, Any]:
    """Legacy wrapper — returns only the inputs dict (no sources)."""
    inputs, _ = _build_inputs_with_sources(
        concept_id,
        question,
        explicit_ref,
        explicit_inputs,
        intermed,
    )
    return inputs


def _compute_input_source_quality(
    expected_params: set[str],
    input_sources: dict[str, str],
) -> float:
    """Average quality of provided (non-missing) inputs.

    Missing parameters — which the template may handle via defaults —
    do not penalise the score.  A step that receives *all* its provided
    inputs from explicit sources gets 1.0; a step with no provided
    inputs at all gets 0.0.
    """
    if not expected_params:
        return 1.0
    provided = {k: v for k, v in input_sources.items() if v != "missing"}
    if not provided:
        return 0.0
    weights = [_INPUT_QUALITY.get(v, 0.0) for v in provided.values()]
    return sum(weights) / len(weights)


# ---------------------------------------------------------------------------
# Phase 3: Input gap analysis & auto-discovery
# ---------------------------------------------------------------------------


def _plug_input_gaps(
    plan: list[PlanStep],
    concept_map: dict[str, Any],
    question: str,
    givens: dict[str, Any],
    explicit_ref: str | None = None,
    explicit_inputs: dict[str, Any] | None = None,
    max_iter: int = 5,
    slot_groups: dict[str, list[str]] | None = None,
    template_registry: dict[str, Any] | None = None,
) -> list[PlanStep]:
    """Auto-discover missing sub-goals and insert them into the plan.

    Greedy fixed-point: for each step whose expected inputs aren't all
    available, find a concept that produces the missing slot and whose
    own inputs ARE available.  Insert it before the step that needs it.
    """
    available: dict[str, Any] = dict(givens)
    if explicit_inputs:
        available.update(explicit_inputs)

    existing_ids: set[str] = {p.concept_id for p in plan}

    for _ in range(max_iter):
        changed = False
        i = 0
        while i < len(plan):
            step = plan[i]
            expected = _get_expected_param_keys(step.concept_id)
            if not expected:
                i += 1
                continue

            missing = expected - set(available.keys())
            if not missing:
                i += 1
                continue

            _slot_groups = slot_groups or _OUTPUT_SLOT_GROUPS
            _treg = template_registry or TEMPLATE_REGISTRY
            for param in missing:
                providers = _slot_groups.get(param, [])
                for provider_id in providers:
                    if provider_id == step.concept_id or provider_id in existing_ids:
                        continue

                    p_meta = concept_map.get(provider_id)
                    if not p_meta or p_meta.template_ref not in _treg:
                        continue

                    p_expected = _get_expected_param_keys(provider_id)
                    if p_expected is not None and not p_expected.issubset(set(available.keys())):
                        continue

                    p_inputs, p_sources = _build_inputs_with_sources(
                        provider_id,
                        question,
                        explicit_ref,
                        explicit_inputs,
                        available,
                    )
                    new_step = PlanStep(
                        concept_id=provider_id,
                        template_ref=p_meta.template_ref,
                        label=p_meta.label,
                        inputs=p_inputs,
                        output_slots=p_meta.output_slots,
                        depends_on=p_meta.dependencies,
                        expected_params=p_expected or set(),
                        input_sources=p_sources,
                    )
                    plan.insert(i, new_step)
                    existing_ids.add(provider_id)
                    available[param] = None
                    changed = True
                    break
            i += 1

        if not changed:
            break

    return plan


# ---------------------------------------------------------------------------
# Phase 2: Plan compilation + multi-path fallback
# ---------------------------------------------------------------------------


def _resolve_dependency_chain(
    target_id: str,
    concept_map: dict[str, Any],
) -> list[str]:
    """Topological sort of *target_id* plus all transitive dependencies.

    Dependencies appear before their dependents (DFS post-order).
    """
    visited: set[str] = set()
    order: list[str] = []

    def _visit(cid: str) -> None:
        if cid in visited:
            return
        visited.add(cid)
        meta = concept_map.get(cid)
        if meta:
            for dep in getattr(meta, "dependencies", ()):
                _visit(dep)
        order.append(cid)

    _visit(target_id)
    return order


def _compile_plan(
    target_id: str,
    concept_map: dict[str, Any],
    question: str,
    givens: dict[str, Any],
    explicit_ref: str | None = None,
    explicit_inputs: dict[str, Any] | None = None,
    template_registry: dict[str, Any] | None = None,
    slot_groups: dict[str, list[str]] | None = None,
) -> list[PlanStep]:
    """Build an ordered execution plan from target concept + question text."""
    dep_order = _resolve_dependency_chain(target_id, concept_map)
    plan: list[PlanStep] = []

    # Intermediates start with givens, grow as plan steps succeed
    intermed: dict[str, Any] = dict(givens)

    _treg = template_registry if template_registry is not None else TEMPLATE_REGISTRY
    for cid in dep_order:
        meta = concept_map.get(cid)
        if meta is None:
            continue
        tref = meta.template_ref
        if tref not in _treg:
            continue

        # If this dependency's output slots are already provided as
        # explicit inputs to the target concept, skip it — the value is
        # known and doesn't need to be computed.
        if cid != explicit_ref and explicit_inputs and meta.output_slots:
            if all(slot in explicit_inputs for slot in meta.output_slots):
                # Still forward the slots to intermed so downstream steps
                # can consume them.
                for slot in meta.output_slots:
                    intermed[slot] = explicit_inputs[slot]
                continue

        expected = _get_expected_param_keys(cid)
        step_inputs, step_sources = _build_inputs_with_sources(
            cid,
            question,
            explicit_ref,
            explicit_inputs,
            intermed,
        )

        plan.append(
            PlanStep(
                concept_id=cid,
                template_ref=tref,
                label=meta.label,
                inputs=step_inputs,
                output_slots=meta.output_slots,
                depends_on=meta.dependencies,
                expected_params=expected or set(),
                input_sources=step_sources,
            )
        )

        # If this step's concept has output slots that are now in inputs,
        # carry them forward for the next iteration
        for slot in meta.output_slots:
            if slot in step_inputs:
                intermed[slot] = step_inputs[slot]

    # Phase 3: auto-discover missing sub-goals
    plan = _plug_input_gaps(
        plan,
        concept_map,
        question,
        givens,
        explicit_ref=explicit_ref,
        explicit_inputs=explicit_inputs,
        template_registry=_treg if template_registry is not None else None,
        slot_groups=slot_groups if slot_groups is not None else None,
    )

    return plan


# ---------------------------------------------------------------------------
# Phase 2: Multi-path execution with fallback
# ---------------------------------------------------------------------------


def _try_run_template(
    template_ref: str,
    ctx: dict[str, Any],
    template_registry: dict[str, Any] | None = None,
) -> tuple[bool, dict[str, Any] | None, float]:
    """Run one template, returning ``(success, raw_result, duration_ms)``.

    If *template_registry* is provided, the template is looked up there;
    otherwise the global ``TEMPLATE_REGISTRY`` is used.
    """
    t0 = time.perf_counter()
    try:
        if template_registry is not None:
            tpl = template_registry.get(template_ref)
            if tpl is None:
                return False, None, (time.perf_counter() - t0) * 1000
            raw = tpl.solve(ctx)
        else:
            raw = run_template(template_ref, ctx)
        duration = (time.perf_counter() - t0) * 1000
        if raw is not None and not raw.get("is_nan", True):
            return True, raw, duration
        return False, raw, duration
    except Exception:
        duration = (time.perf_counter() - t0) * 1000
        return False, None, duration


def _execute_plan(
    plan: list[PlanStep],
    givens: dict[str, Any],
    concept_map: dict[str, Any] | None = None,
    template_registry: dict[str, Any] | None = None,
    slot_groups: dict[str, list[str]] | None = None,
) -> tuple[list[ExecutionRecord], dict[str, Any]]:
    """Execute *plan* in order, forwarding intermediate results downstream.

    If a step fails, alternative concepts producing the same output slot
    are tried automatically (multi-path fallback, Phase 2).

    Only intermediate values produced by **prior step executions** are
    forwarded — givens from the original call are not merged into step
    inputs to avoid name collisions with output slot names (e.g.
    ``asset_beta`` the output slot vs. ``asset_beta`` the given).
    """
    execution: list[ExecutionRecord] = []
    intermed: dict[str, Any] = {}
    _cmap = concept_map if concept_map is not None else BUILTIN_CONCEPTS
    _treg = template_registry if template_registry is not None else TEMPLATE_REGISTRY
    _sgroups = slot_groups or _OUTPUT_SLOT_GROUPS

    for step in plan:
        if step.skipped:
            quality = _compute_input_source_quality(step.expected_params, step.input_sources)
            execution.append(
                ExecutionRecord(
                    concept_id=step.concept_id,
                    success=False,
                    skipped=True,
                    label=step.label,
                    input_source_quality=quality,
                )
            )
            continue

        # Build execution context — supplement with intermed from prior steps.
        # Forward any intermed value matching an expected param of this step.
        # (This is critical for multi-path fallback: when a fallback alternative
        # produces a value at execution time that wasn't available at compile time,
        # the downstream step still receives it via this forwarding.)
        ctx = dict(step.inputs)
        for k, v in intermed.items():
            if k in step.expected_params and k not in ctx:
                ctx[k] = v

        # --- try the original step ---
        success, raw, duration = _try_run_template(step.template_ref, ctx, template_registry=_treg)
        quality = _compute_input_source_quality(step.expected_params, step.input_sources)

        if success:
            result_val = float(raw["result"]) if raw and raw.get("result") is not None else None
            for slot in step.output_slots:
                intermed[slot] = result_val
            execution.append(
                ExecutionRecord(
                    concept_id=step.concept_id,
                    success=True,
                    label=step.label,
                    result=result_val,
                    detailed_steps=raw.get("steps", []) if raw else [],
                    error_tags=raw.get("error_tags", []) if raw else [],
                    duration_ms=duration,
                    input_source_quality=quality,
                )
            )
            continue

        # --- original failed → try alternatives (multi-path) ---
        alts = _find_alternatives(step.concept_id, concept_map=_cmap, slot_groups=_sgroups)
        fb_record: ExecutionRecord | None = None

        for alt_id in alts:
            alt_meta = _cmap.get(alt_id)
            if not alt_meta or alt_meta.template_ref not in _treg:
                continue

            # Fresh inputs for the alternative (no ctx from the failed step)
            alt_inputs, alt_sources = _build_inputs_with_sources(
                alt_id,
                "",
                None,
                None,
                intermed,
            )
            alt_expected = _get_expected_param_keys(alt_id) or set()
            alt_ctx = dict(alt_inputs)
            for k, v in intermed.items():
                if k in alt_expected and k not in alt_ctx:
                    alt_ctx[k] = v

            fb_success, fb_raw, fb_duration = _try_run_template(
                alt_meta.template_ref,
                alt_ctx,
                template_registry=_treg,
            )
            fb_quality = _compute_input_source_quality(alt_expected, alt_sources)

            if fb_success:
                fb_result = float(fb_raw["result"]) if fb_raw and fb_raw.get("result") is not None else None
                for slot in step.output_slots:
                    intermed[slot] = fb_result
                fb_record = ExecutionRecord(
                    concept_id=alt_id,
                    success=True,
                    label=alt_meta.label,
                    result=fb_result,
                    detailed_steps=fb_raw.get("steps", []) if fb_raw else [],
                    error_tags=fb_raw.get("error_tags", []) if fb_raw else [],
                    duration_ms=fb_duration,
                    input_source_quality=fb_quality,
                )
                break

        if fb_record is not None:
            execution.append(fb_record)
        else:
            # All alternatives failed — record the original failure
            execution.append(
                ExecutionRecord(
                    concept_id=step.concept_id,
                    success=False,
                    label=step.label,
                    error_tags=(raw.get("error_tags", ["nan_result"]) if raw else ["execution_error"]),
                    duration_ms=duration,
                    input_source_quality=quality,
                )
            )

    return execution, intermed


# ---------------------------------------------------------------------------
# Phase 4: Weighted confidence
# ---------------------------------------------------------------------------


def _compute_confidence(execution: list[ExecutionRecord]) -> float:
    """Weighted confidence from input source quality + step success rate."""
    if not execution:
        return 0.0
    total = 0
    success_count = 0
    quality_sum = 0.0
    for rec in execution:
        if rec.skipped:
            continue
        total += 1
        if rec.success:
            success_count += 1
        quality_sum += rec.input_source_quality
    if total == 0:
        return 0.0
    avg_quality = quality_sum / total
    success_rate = success_count / total
    return avg_quality * success_rate


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def reason_question(
    question: str,
    *,
    domain: str | None = None,
    options: list[str] | None = None,
    correct: str | None = None,
    learner_answer: str | None = None,
    explanation: str | None = None,
    template_ref: str | None = None,
    template_inputs: dict[str, Any] | None = None,
    learner_workings: str | None = None,
) -> ReasoningTrace:
    """Reason about a question and compile a solution plan.

    Parameters
    ----------
    question : str
        The question text.
    domain : str | None
        Exam domain prefix (e.g. ``"fm"``, ``"pmp"``).  Defaults to ACCA FM.
    options : list[str] | None
        Answer options for multiple choice (passed to diagnostic layer).
    correct : str | None
        The stated correct answer (for mismatch detection).
    learner_answer : str | None
        The learner's answer (for error classification).
    explanation : str | None
        Explanation text (for freeform verification).
    template_ref : str | None
        Explicit template reference (bypass concept detection).
    template_inputs : dict | None
        Explicit template inputs (bypass input extraction).

    Returns
    -------
    ReasoningTrace
        Structured trace with plan, execution records, diagnostics.
    """
    # Resolve domain registry (defaults to ACCA FM globals)
    if domain is not None:
        from studyplan.domain_reasoning.domain_registry import get_registry

        reg = get_registry(domain)
        _concepts = reg.concepts
        _templates = reg.templates
        _slot_groups = reg._slot_groups or _build_slot_groups(_concepts)
    else:
        reg = None
        _concepts = BUILTIN_CONCEPTS
        _templates = TEMPLATE_REGISTRY
        _slot_groups = _OUTPUT_SLOT_GROUPS

    result = ReasoningTrace(question=question)

    if not question:
        return result

    # 1. Detect concepts
    concept_ids = detect_concepts(question, domain=domain)
    result.concept_ids = list(concept_ids)

    # 2. Pick target concept
    target_id = template_ref or (concept_ids[0] if concept_ids else None)
    if target_id is None:
        return result
    result.target_concept_id = target_id

    # 3. Assemble givens
    givens: dict[str, Any] = {}
    if template_inputs:
        givens.update(template_inputs)
    result.givens = dict(givens)

    # 4. Compile plan
    plan = _compile_plan(
        target_id,
        _concepts,
        question,
        givens,
        explicit_ref=template_ref,
        explicit_inputs=template_inputs,
        template_registry=_templates,
        slot_groups=_slot_groups,
    )
    result.plan = plan
    if not plan:
        return result

    # 5. Execute plan
    execution, intermed = _execute_plan(
        plan,
        givens,
        concept_map=_concepts,
        template_registry=_templates,
        slot_groups=_slot_groups,
    )
    result.execution = execution

    # 6. Extract final result
    for rec in reversed(execution):
        if rec.success and rec.result is not None:
            result.final_result = rec.result
            break

    # 7. Confidence (Phase 4: weighted)
    result.confidence = _compute_confidence(execution)

    # 8. Diagnostics (use the existing pipeline)
    from studyplan.domain_reasoning.evaluator import evaluate_question

    diag = evaluate_question(
        question,
        domain=domain,
        options=options,
        correct=correct,
        template_ref=template_ref,
        template_inputs=template_inputs,
        explanation=explanation,
        learner_answer=learner_answer,
        learner_workings=learner_workings,
    )
    result.diagnostic = diag

    return result
