"""Auto-discover formula declarations from syllabus outcomes + question bank.

Pipeline:
  1. Scan syllabus_structure for computational learning outcomes.
  2. For each outcome, gather questions from the bank that likely match.
  3. Build an LLM prompt that proposes ``declare_formula()`` calls.
  4. Validate each proposal against the question bank (run solver, compare).
  5. Register high-confidence formulas, flag low-confidence for review.

All pure functions / GTK-free.  Designed to be called from a Tools menu
action or a background thread.
"""

from __future__ import annotations

import copy
import logging
import re
import textwrap
from typing import Any, Callable

from studyplan.domain_reasoning.formula_registry import (
    declare_formula,
    declare_formula_chain,
    _registry as _FORMULA_REGISTRY,
    validate_registry,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _declare_formula_or_chain(proposal: ProposedFormula) -> None:
    """Register a single formula (or formula chain) into the live registry."""
    if proposal.is_chain() and proposal.chain_steps:
        declare_formula_chain(
            proposal.concept_id,
            steps=[
                {
                    "slot": s["slot"],
                    "expression": s["expression"],
                    "param_names": s.get("param_names", []),
                    "param_kinds": s.get("param_kinds", []),
                    "description": s.get("description", ""),
                }
                for s in proposal.chain_steps
            ],
            patterns=proposal.patterns,
            label=proposal.label,
            output_slot=proposal.output_slot,
            diagnostic_tags=proposal.diagnostic_tags,
        )
    else:
        declare_formula(
            proposal.concept_id,
            expression=proposal.expression,
            param_names=proposal.param_names,
            param_kinds=proposal.param_kinds,
            patterns=proposal.patterns,
            label=proposal.label,
            output_slot=proposal.output_slot,
            diagnostic_tags=proposal.diagnostic_tags,
        )


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class ProposedFormula:
    """One formula proposal from the LLM, before validation."""

    def __init__(
        self,
        concept_id: str,
        expression: str,
        param_names: list[str],
        param_kinds: list[str] | None = None,
        label: str = "",
        output_slot: str | None = None,
        patterns: list[str] | None = None,
        diagnostic_tags: list[str] | None = None,
        outcome_refs: list[str] | None = None,
        chain_steps: list[dict[str, Any]] | None = None,
    ) -> None:
        self.concept_id = concept_id
        self.expression = expression
        self.param_names = param_names
        self.param_kinds = param_kinds or ["value"] * len(param_names)
        self.label = label
        self.output_slot = output_slot or concept_id.split(".")[-1]
        self.patterns = patterns or []
        self.diagnostic_tags = diagnostic_tags or []
        self.outcome_refs = outcome_refs or []
        self.chain_steps = chain_steps

    def is_chain(self) -> bool:
        return bool(self.chain_steps)


class ValidationResult:
    """Outcome of validating one proposed formula against a question bank."""

    def __init__(
        self,
        proposal: ProposedFormula,
        total_questions: int = 0,
        passed: int = 0,
        failed: int = 0,
        errors: list[str] | None = None,
    ) -> None:
        self.proposal = proposal
        self.total_questions = total_questions
        self.passed = passed
        self.failed = failed
        self.errors = errors or []

    @property
    def pass_rate(self) -> float:
        if self.total_questions == 0:
            return 0.0
        return self.passed / self.total_questions

    @property
    def is_registration_ready(self) -> bool:
        return self.pass_rate >= 0.8 and self.total_questions >= 2

    @property
    def summary(self) -> str:
        return (
            f"{self.proposal.concept_id}: "
            f"{self.passed}/{self.total_questions} passed "
            f"({self.pass_rate:.0%}), "
            f"{'READY' if self.is_registration_ready else 'NEEDS REVIEW'}"
        )


# ---------------------------------------------------------------------------
# Step 1: Extract computational outcomes from syllabus_structure
# ---------------------------------------------------------------------------

_COMPUTATIONAL_VERBS: set[str] = {
    "calculate",
    "compute",
    "determine",
    "derive",
    "solve",
    "evaluate",
    "measure",
    "estimate",
    "quantify",
    "forecast",
    "project",
    "find",
    "obtain",
    "prepare",
    "construct",
}


def _is_computational_outcome(text: str) -> bool:
    """Heuristic: does this outcome text involve computation?"""
    lower = text.lower()
    return any(verb in lower for verb in _COMPUTATIONAL_VERBS)


def extract_computational_outcomes(
    syllabus_structure: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    """Return ``(chapter_name, learning_outcome)`` pairs for computation outcomes."""
    results: list[tuple[str, dict[str, Any]]] = []
    for chapter, info in syllabus_structure.items():
        if not isinstance(info, dict):
            continue
        for lo in info.get("learning_outcomes", []):
            if not isinstance(lo, dict):
                continue
            text = str(lo.get("text", "") or "").strip()
            if text and _is_computational_outcome(text):
                results.append((chapter, lo))
    return results


# ---------------------------------------------------------------------------
# Step 2: Gather candidate questions per outcome
# ---------------------------------------------------------------------------


def gather_questions_for_outcome(
    chapter: str,
    outcome: dict[str, Any],
    questions_by_chapter: dict[str, list[dict[str, Any]]],
    max_samples: int = 5,
) -> list[dict[str, Any]]:
    """Get questions from this chapter, preferring numerical ones."""
    candidates = list(questions_by_chapter.get(chapter, []) or [])

    # Score: numerical questions with options are best
    def _score(q: dict[str, Any]) -> float:
        s = 0.0
        if q.get("correct") and _looks_numeric(str(q["correct"])):
            s += 2.0
        if q.get("options") and len(q.get("options", [])) >= 2:
            s += 1.0
        if q.get("explanation"):
            s += 0.5
        return s

    candidates.sort(key=_score, reverse=True)
    return candidates[:max_samples]


def _looks_numeric(s: str) -> bool:
    s = s.strip().lstrip("$£€").replace(",", "").replace("%", "")
    try:
        float(s)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Step 2b: Filter questions relevant to a proposed formula
# ---------------------------------------------------------------------------


def _default_question_filter(
    proposal: ProposedFormula,
    questions: list[dict[str, Any]],
    chapter: str = "",
    min_samples: int = 2,
) -> list[dict[str, Any]]:
    """Select questions relevant to a proposed formula.

    Uses the proposal's ``patterns`` (regex patterns generated by the LLM)
    to match against question text.  If no patterns match or no patterns
    are defined, falls back to any question whose correct answer looks
    numeric — that at least ensures the solver pipeline can run.

    The ``chapter`` parameter is accepted for API compatibility with
    ``QuestionFilter`` but is not used by the default implementation.
    """
    patterns = proposal.patterns
    if patterns:
        compiled = [re.compile(p, re.IGNORECASE) for p in patterns]
        matched = [q for q in questions if any(p.search(str(q.get("question", "")) or "") for p in compiled)]
        if len(matched) >= min_samples:
            return matched

    # Fallback — questions with numeric correct answers
    numeric = [q for q in questions if _looks_numeric(str(q.get("correct", "")))]
    if numeric:
        return numeric

    # Last resort — return original pool; at least it's something to validate
    return questions[:min_samples]


# ---------------------------------------------------------------------------
# Step 3: Build LLM prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = textwrap.dedent("""\
You are a domain reasoning engineer for a study app.  Your task is to propose
``declare_formula()`` calls that would let the app's deterministic solver
evaluate student answers for given syllabus outcomes.

You will receive:
- A syllabus learning outcome text (e.g. "Calculate the weighted average cost of capital")
- Example questions from the bank (with correct answers and options)

You must respond with a JSON object containing ONE of:
  a) A single-step formula: {"type": "formula", "concept_id": "...", "expression": "...", "param_names": [...], "param_kinds": [...], "label": "...", "patterns": [...], "diagnostic_tags": [...]}
  b) A chain formula: {"type": "chain", "concept_id": "...", "steps": [{"slot": "...", "expression": "...", "param_names": [...], "param_kinds": [...]}, ...], "label": "...", "patterns": [...], "diagnostic_tags": [...]}
  c) null if the outcome is not suitable for deterministic evaluation

RULES:
1. concept_id must start with the module prefix (e.g. "fm." for ACCA FM)
2. expression uses variable names, not numbers. Use standard math operators: + - * / **
3. param_names list the variable names in the expression
4. param_kinds: "value" for raw numbers, "percent" for percentages
5. patterns: regex patterns to detect this concept in question text
6. diagnostic_tags: possible error types (e.g. "sign_error", "wrong_rate")
7. Only propose if you are confident the formula can be validated against the questions
8. For multi-step calculations, use a chain formula
9. Expression variables will be substituted at solve time with float values
""").strip()


def _extract_numbers_from_question(q: dict[str, Any]) -> list[float]:
    """Extract all numbers from a question + options + explanation."""
    text = " ".join(
        [
            str(q.get("question", "") or ""),
            " ".join(str(o) for o in q.get("options", []) or []),
        ]
    )
    nums: list[float] = []
    for match in re.finditer(r"-?\d+(?:\.\d+)?(?:%|percent)?", text):
        try:
            nums.append(float(match.group()))
        except ValueError:
            pass
    return nums


def build_llm_prompt(
    chapter: str,
    outcome: dict[str, Any],
    sample_questions: list[dict[str, Any]],
    domain_prefix: str = "fm",
) -> list[dict[str, str]]:
    """Build a chat-style LLM prompt for formula proposal."""
    outcome_text = str(outcome.get("text", "") or "")
    outcome_id = str(outcome.get("id", "") or "")

    q_lines: list[str] = []
    for i, q in enumerate(sample_questions, 1):
        nums = _extract_numbers_from_question(q)
        q_lines.append(
            f"Question {i}: {q.get('question', '')}\n"
            f"  Options: {q.get('options', [])}\n"
            f"  Correct: {q.get('correct', '')}\n"
            f"  Numbers found: {nums[:10]}"
        )

    user_prompt = textwrap.dedent(f"""\
    Outcome: [{outcome_id}] {outcome_text}
    Chapter: {chapter}

    Sample questions from this chapter:
    {chr(10).join(q_lines) if sample_questions else "  (no questions available)"}

    Domain prefix: "{domain_prefix}."

    Propose a declare_formula() call as JSON, or null if not applicable.
    """).strip()

    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


# ---------------------------------------------------------------------------
# Step 4: Parse LLM response into a ProposedFormula
# ---------------------------------------------------------------------------


def parse_llm_response(response_text: str) -> ProposedFormula | None:
    """Parse LLM JSON response into a ProposedFormula."""
    import json

    text = response_text.strip()
    # Try to extract JSON from markdown code blocks
    code_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if code_match:
        text = code_match.group(1).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to find a JSON object anywhere in the text
        brace_match = re.search(r"\{[\s\S]*\}", text)
        if brace_match:
            try:
                data = json.loads(brace_match.group())
            except json.JSONDecodeError:
                return None
        else:
            return None

    if data is None:
        return None

    concept_id = str(data.get("concept_id", "") or "").strip()
    if not concept_id:
        return None

    if data.get("type") == "chain":
        steps = data.get("steps", [])
        if not steps:
            return None
        return ProposedFormula(
            concept_id=concept_id,
            expression="",
            param_names=[],
            label=str(data.get("label", "") or ""),
            output_slot=str(data.get("output_slot", "")) or None,
            patterns=data.get("patterns", []),
            diagnostic_tags=data.get("diagnostic_tags", []),
            chain_steps=steps,
        )

    expression = str(data.get("expression", "") or "").strip()
    param_names = list(data.get("param_names", []) or [])
    if not expression or not param_names:
        return None

    return ProposedFormula(
        concept_id=concept_id,
        expression=expression,
        param_names=param_names,
        param_kinds=list(data.get("param_kinds", []) or []),
        label=str(data.get("label", "") or ""),
        output_slot=str(data.get("output_slot", "")) or None,
        patterns=data.get("patterns", []),
        diagnostic_tags=data.get("diagnostic_tags", []),
    )


# ---------------------------------------------------------------------------
# Step 4b: Validate a proposed formula against the question bank
# ---------------------------------------------------------------------------

# Type alias for question filter callables.
# Signature: (proposal, questions, chapter_name) -> filtered_questions
QuestionFilter = Callable[
    [ProposedFormula, list[dict[str, Any]], str],
    list[dict[str, Any]],
]


def validate_proposal(
    proposal: ProposedFormula,
    questions: list[dict[str, Any]],
    question_filter: QuestionFilter | None = None,
    chapter: str = "",
) -> ValidationResult:
    """Test a proposed formula by running it against relevant questions.

    Uses the numerical solver pipeline to extract numbers, assign params,
    and compare solver output to the correct answer.

    Parameters
    ----------
    proposal:
        The formula proposal to validate.
    questions:
        Candidate questions from the chapter (typically 3-5).
    question_filter:
        Optional callable ``(proposal, questions) -> filtered_questions``.
        When omitted, ``_default_question_filter`` is used, which selects
        questions whose text matches the proposal's regex ``patterns``
        and falls back to any question with a numeric correct answer.

        The app layer can inject a filter that uses the engine's semantic
        matcher (``resolve_question_outcomes``) for higher precision.
    """
    from studyplan.numerical_solver import (
        _FORMULA_SOLVERS,
        _FORMULA_CANDIDATES,
    )

    filter_fn = question_filter or _default_question_filter
    questions = filter_fn(proposal, list(questions), chapter)
    result = ValidationResult(proposal, total_questions=len(questions))
    if not questions:
        return result

    # Temporarily register the formula so we can use the solver pipeline
    proposal.concept_id.split(".")[-1]
    _saved_solvers = copy.copy(_FORMULA_SOLVERS)
    _saved_candidates = copy.copy(_FORMULA_CANDIDATES)

    from studyplan.domain_reasoning.formula_registry import (
        build_solver_dict as _build_solver_dict,
        build_candidate_dict as _build_candidate_dict,
    )

    try:
        _declare_formula_or_chain(proposal)

        # Refresh solver dicts
        _FORMULA_SOLVERS.update(_build_solver_dict())
        _FORMULA_CANDIDATES.update(_build_candidate_dict())

        # Validate against each question
        for q in questions:
            question_text = str(q.get("question", "") or "")
            options = list(q.get("options", []) or [])
            correct = str(q.get("correct", "") or "")
            explanation = str(q.get("explanation", "") or "")

            if not _looks_numeric(correct):
                result.errors.append(f"non-numeric correct answer for '{correct}'")
                result.failed += 1
                continue

            from studyplan.numerical_solver import verify_numerical_answer

            rejection = verify_numerical_answer(
                question_text,
                options,
                correct,
                explanation=explanation,
            )
            if rejection is None:
                result.passed += 1
            else:
                result.failed += 1
                result.errors.append(f"{rejection}: q='{question_text[:60]}...'")

    except Exception as e:
        log.warning("Validation error for %s: %s", proposal.concept_id, e)
        result.errors.append(str(e))

    finally:
        # Restore original solvers (validation is read-only)
        _FORMULA_SOLVERS.clear()
        _FORMULA_SOLVERS.update(_saved_solvers)
        _FORMULA_CANDIDATES.clear()
        _FORMULA_CANDIDATES.update(_saved_candidates)

    return result


# ---------------------------------------------------------------------------
# Step 5: Register high-confidence formulas
# ---------------------------------------------------------------------------


def register_proposal(proposal: ProposedFormula) -> bool:
    """Register a validated formula proposal into the live registry.

    Returns True on success.
    """
    try:
        # Check if already registered
        existing = _FORMULA_REGISTRY.get(proposal.concept_id)
        if existing:
            log.info("Formula %s already registered, skipping", proposal.concept_id)
            return False

        _declare_formula_or_chain(proposal)

        validation_msgs = validate_registry()
        if validation_msgs:
            for msg in validation_msgs:
                log.warning("Registry warning after registering %s: %s", proposal.concept_id, msg)

        return True
    except Exception as e:
        log.error("Failed to register %s: %s", proposal.concept_id, e)
        return False


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class FormulaDiscoveryResult:
    """Aggregated result of a full auto-discovery run."""

    def __init__(self) -> None:
        self.proposals: list[ProposedFormula] = []
        self.validations: list[ValidationResult] = []
        self.registered: list[str] = []
        self.flagged: list[str] = []
        self.errors: list[str] = []
        self.skipped_outcomes: int = 0
        self.outcomes_scanned: int = 0

    @property
    def summary(self) -> str:
        lines = [
            f"Outcomes scanned: {self.outcomes_scanned}",
            f"Outcomes skipped (no suitable questions): {self.skipped_outcomes}",
            f"Formulas proposed: {len(self.proposals)}",
            f"Registered: {len(self.registered)}",
            f"Flagged for review: {len(self.flagged)}",
            f"Errors: {len(self.errors)}",
        ]
        if self.registered:
            lines.append(f"Registered: {', '.join(self.registered)}")
        if self.flagged:
            lines.append(f"Flagged: {', '.join(self.flagged)}")
        return "\n".join(lines)


def run_auto_discovery(
    syllabus_structure: dict[str, Any],
    questions_by_chapter: dict[str, list[dict[str, Any]]],
    llm_chat_fn: Callable[[list[dict[str, str]]], str],
    domain_prefix: str = "fm",
    confidence_threshold: float = 0.8,
    question_filter: QuestionFilter | None = None,
) -> FormulaDiscoveryResult:
    """Full auto-discovery pipeline.

    Parameters
    ----------
    syllabus_structure:
        Engine ``syllabus_structure`` dict (chapter → info → learning_outcomes).
    questions_by_chapter:
        Engine questions dict (chapter → list of question dicts).
    llm_chat_fn:
        Callable that takes a list of messages and returns response text.
    domain_prefix:
        The module domain prefix (e.g. ``"fm"`` for ACCA FM, ``"f7"`` for F7).
    confidence_threshold:
        Minimum pass rate to auto-register (default 0.8).
    question_filter:
        Callable ``(proposal, questions) -> filtered_questions`` forwarded to
        ``validate_proposal``.  Use this to inject semantic matching for
        higher-precision question selection.

    Returns
    -------
    FormulaDiscoveryResult with proposals, validations, registrations.
    """
    result = FormulaDiscoveryResult()

    # Step 1: Extract computational outcomes
    computational = extract_computational_outcomes(syllabus_structure)
    result.outcomes_scanned = len(computational)

    if not computational:
        result.errors.append("No computational outcomes found in syllabus")
        return result

    # Step 2-3: For each outcome, propose a formula
    for chapter, outcome in computational:
        questions = gather_questions_for_outcome(chapter, outcome, questions_by_chapter)
        if len(questions) < 2:
            result.skipped_outcomes += 1
            continue

        # Build prompt and call LLM
        prompt = build_llm_prompt(chapter, outcome, questions, domain_prefix)
        try:
            response = llm_chat_fn(prompt)
        except Exception as e:
            result.errors.append(f"LLM call failed for {outcome.get('id', '')}: {e}")
            continue

        # Parse response
        proposal = parse_llm_response(response)
        if proposal is None:
            result.skipped_outcomes += 1
            continue

        result.proposals.append(proposal)

        # Step 4: Validate against question bank
        validation = validate_proposal(
            proposal,
            questions,
            question_filter=question_filter,
            chapter=chapter,
        )
        result.validations.append(validation)

        # Step 5: Register or flag
        if validation.is_registration_ready:
            if register_proposal(proposal):
                result.registered.append(proposal.concept_id)
            else:
                result.errors.append(f"Registration failed for {proposal.concept_id}")
        else:
            result.flagged.append(proposal.concept_id)

    return result
