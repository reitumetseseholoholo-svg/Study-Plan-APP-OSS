"""
Prompt engineering for major AI actions: 3Es (Economy, Efficiency, Effectiveness) + fail-safe.

Use this module for:
- Shared snippets so prompts stay consistent and one-place editable.
- In-app **tutor** base/variable layering: see `tutor_prompt_layers.py` (coach identity lines, `pedagogical_mode`).
- Schema-first, rules-then-payload structure for generation (Section C, MCQ/gap, syllabus, etc.).
- Retry suffixes for relaxed second attempts when parse fails.

Design: DEVELOPER_DOC.md § "Prompt engineering design (3Es + fail-safe)".
"""
from __future__ import annotations

import os

from studyplan.question_quality import (
    MCQ_GAP_LONG_OUTLIER_VS_DISTRACTOR_MEAN,
    MCQ_GAP_MIN_AVG_DISTRACTOR_CHARS_LONG_RULE,
    MCQ_GAP_MIN_AVG_DISTRACTOR_CHARS_SHORT_RULE,
    MCQ_GAP_SHORT_OUTLIER_VS_DISTRACTOR_MEAN,
)

# --- Economy: single source for common phrases (no duplication across actions) ---

# Grammar and style: require correct English in all user-facing text (tutor, generated questions, feedback).
GRAMMAR_QUALITY_RULE = (
    "Write in correct, professional English: no grammatical errors, no spelling mistakes, "
    "and clear sentence structure. Proofread your response before finishing."
)
GRAMMAR_QUALITY_RULE_SHORT = "Use correct grammar and spelling; no errors in any text you generate."

JSON_ONLY_NO_PROSE = "JSON only (no prose)."
JSON_ONLY_NO_MARKDOWN = "Return only the JSON object. No markdown, no code block, no explanation."
RETRY_SUFFIX_ONE_ITEM = (
    JSON_ONLY_NO_MARKDOWN + " Generate exactly one question."
)
RETRY_SUFFIX_ONE_CASE = (
    JSON_ONLY_NO_MARKDOWN + " Generate exactly one case."
)
SYLLABUS_JSON_ONLY = "Return valid JSON only, no markdown or explanation."

# --- Schema one-liners (economy: single source for generation prompts) ---

GAP_SCHEMA_ONE_LINE = (
    '{"chapter":"<exact chapter title from payload>","questions":['
    '{"question":"exam-style stem with command verb (Calculate/Evaluate/…)",'
    '"options":["Full text option A","Full text B","Full text C","Full text D"],'
    '"correct":"Full text B" or "B",'
    '"explanation":"brief syllabus-grounded rationale"}]}'
)
SECTION_C_SCHEMA_ONE_LINE = (
    '{"chapter":"...","scenario":"Full case narrative (company, situation, numbers). 150-400 words. No placeholders.",'
    '"requirements":[{"part":"a","requirement_text":"Requirement with command verb (e.g. Calculate, Evaluate, Recommend).","marks":8},'
    '{"part":"b","requirement_text":"...","marks":8},{"part":"c","requirement_text":"...","marks":4}],'
    '"model_answer_outline":["bullet aligned to (a)","bullet aligned to (b)","bullet aligned to (c)"],'
    '"time_budget_minutes":45}'
)
SECTION_C_SCHEMA_FR_SUFFIX = (
    " For each requirement that asks to Prepare or Present a primary statement or a note extract, "
    "the matching model_answer_outline entry must be a compact skeleton (main headings, material line items, "
    "and key subtotals), not narrative paragraphs."
)
SYLLABUS_OUTCOMES_SCHEMA_ONE_LINE = (
    '{"outcomes":[{"id":"...","text":"...","level":1 or 2 or 3,"chapter":"<exact chapter title>"}],"warnings":["optional note"]}'
)
# Assessment (AI judge): outcome, marks, feedback, optional tags.
ASSESSMENT_JUDGE_SCHEMA_ONE_LINE = (
    '{"outcome":"correct"|"partial"|"incorrect","marks_awarded":number,"marks_max":number,'
    '"feedback":"short reason","error_tags":[],"misconception_tags":[],"suggested_next_step":"optional"}'
)
JUDGE_JSON_ONLY = "Return only the JSON object. No other text."

# Coach/autopilot: single JSON action object.
AUTOPILOT_ACTION_SCHEMA_ONE_LINE = (
    '{"action":"focus_start|timer_pause|timer_resume|timer_stop|tutor_open|coach_open|quiz_start|quick_quiz_start|'
    'drill_start|weak_drill_start|leitner_drill_start|error_drill_start|leech_drill_start|review_start|'
    'interleave_start|coach_next|gap_drill_generate|section_c_start","topic":"chapter|empty","duration_minutes":25,'
    '"reason":"short reason","confidence":0.0,"requires_confirmation":false,"evidence":["signal=value"]}'
)

# --- Task prompt library (best prompt per in-app AI task; see PROMPT_QUALITY_SLICE.md) ---

# Autopilot: role and rules live here; app injects runtime_contract (from _build_local_ai_runtime_contract).
AUTOPILOT_ROLE_BASE = "You are an ACCA AI tutor cockpit controller."
AUTOPILOT_ROLE_SUFFIX = " Return exactly one JSON object and nothing else."
AUTOPILOT_RULES = [
    "Prefer the highest exam-impact safe action with bounded latency.",
    "Decision bias: high must_review_due -> review_start; weak-topic pressure -> weak_drill_start/drill_start; otherwise focus_start or quiz_start.",
    "Use only topics found in snapshot weak_topics_top3/current_topic/coach_pick.",
    "Set requires_confirmation=true for higher-impact actions (review_start, interleave_start, gap_drill_generate, section_c_start, timer_stop).",
    "Include 1-3 compact evidence items grounded in snapshot fields.",
    "Use tutor_open when opening/focusing the Tutor dialog would unblock the learner.",
    "Use coach_open when a coaching recommendation should be shown before further execution.",
    "If no action should run now, return action='focus_start' with a concise reason.",
]

# Coach: app injects runtime_contract and learning_context; same pattern as autopilot.
COACH_ROLE_BASE = "You are an ACCA AI study coach."
COACH_ROLE_SUFFIX = " Return exactly one JSON object and nothing else."
COACH_SCHEMA_ONE_LINE = (
    '{"action":"focus|quiz|drill|interleave|review","topic":"chapter","duration_minutes":25,'
    '"reason":"short explanation","confidence":0.0}'
)
COACH_RULES = [
    "Choose only one action from: focus, quiz, drill, interleave, review.",
    "If unsure, pick the safest deterministic action from the payload action_topics map.",
    "Do not invent topics; use only payload.action_topics values or payload.recommended_topic.",
    "Keep reason concise, practical, and lightly explanatory (max 220 chars). Use correct grammar and spelling.",
]

# Gap generation: role + rules; app may add extra_rules (syllabus_scope).
# JSON shape and length-balance contract match strict gap validation + bank quarantine (question_quality).
GAP_GENERATION_ROLE_BASE = (
    "You are an ACCA examiner–style MCQ author. "
    + JSON_ONLY_NO_PROSE
    + " "
    + JSON_ONLY_NO_MARKDOWN
    + " Single best answer, four substantive options, professional English, strictly syllabus-aligned."
)
GAP_GENERATION_RULES = [
    "Output: one JSON object with \"chapter\" (string) and \"questions\" (array), or a bare JSON array of question objects. No markdown fence, no commentary outside JSON.",
    "Schema: each question object has \"question\" (string), \"options\" (array of exactly four strings — full option text, not placeholders), \"correct\" (exact copy of the winning option string, or the letter \"A\"|\"B\"|\"C\"|\"D\"), and \"explanation\" (string).",
    "Stems: ACCA-style command verbs (Calculate, Evaluate, Recommend, Explain, Discuss, Compare, Assess, Advise). One unambiguous best answer; no trick wording; include marks in the stem when appropriate (e.g. (2 marks)).",
    "Options: four parallel, plausible distractors rooted in typical syllabus misconceptions — not nonsense or filler. Do not use \"See explanation\", \"All of the above\", or placeholder labels as option bodies.",
    (
        "Length-balance contract (same checks as the app’s strict auto-save gate and bank quarantine): "
        f"once the three incorrect options average ≥{MCQ_GAP_MIN_AVG_DISTRACTOR_CHARS_LONG_RULE} characters, "
        f"the correct option must not be ≥{MCQ_GAP_LONG_OUTLIER_VS_DISTRACTOR_MEAN}× that average length "
        "(avoid the obvious “longest answer is correct” leak). "
        f"When those three average ≥{MCQ_GAP_MIN_AVG_DISTRACTOR_CHARS_SHORT_RULE} characters, "
        f"the correct option must not be ≤{MCQ_GAP_SHORT_OUTLIER_VS_DISTRACTOR_MEAN}× that average "
        "(avoid the extreme short outlier). Aim for similar word counts and grammatical shape across A–D."
    ),
    "Structural parity: similar sentence length, clause count, and technical depth across all four options so candidates must use knowledge, not layout heuristics.",
    "Quality over quantity: fewer flawless items beat many uneven ones. Avoid duplicating stems the model already emitted in this response.",
    GRAMMAR_QUALITY_RULE,
]

# FR gap generation: classification / disclosure MCQs mixed into normal gap batches (acca_f7 or Financial Reporting title).
GAP_FR_CLASSIFICATION_EXTRA_RULES = [
    "Include at least one question that tests presentation or classification: stem asks where an item is reported "
    '(e.g. "Where should … be presented?" or "In which section of the financial statements …?") with four options '
    'that name the statement and area (e.g. "Statement of financial position – equity", '
    '"Statement of cash flows – operating activities").',
    "Optionally include one disclosure-style question: which items must be disclosed or presented for a named IFRS/IAS "
    "when it fits the topic; single best answer with four substantive options.",
]

# Section C generation: role + rules; app may add extra_rules (syllabus_scope).
SECTION_C_ROLE_BASE = (
    "Generate one ACCA exam-type Section C constructed-response case as "
    + JSON_ONLY_NO_PROSE
    + " Question must be ACCA exam-style: syllabus-aligned, professional level, realistic scenario and requirements as in real ACCA Section C papers. Output must match live exam format: one scenario narrative and requirements (a), (b), (c) with mark allocation. Do not use empty exhibits."
)
SECTION_C_RULES = [
    "scenario: Single narrative with case facts, figures, and context. No empty exhibits or [Exhibit 1] placeholders.",
    "requirements: Exactly 3 parts (a), (b), (c). Each has part (a/b/c), requirement_text (one clear task with command verb), and marks. Total marks must equal 20.",
    "Command verbs: Calculate, Evaluate, Recommend, Discuss, Explain, Assess, Compare, Advise.",
    "Part (a) often 8 marks (calculation/application), (b) 8 marks (discussion), (c) 4 marks (recommendation). Adjust so total = 20.",
    "model_answer_outline: exactly 3 strings in order (a)(b)(c); each must map to its requirement. Use heading-style bullets for preparation tasks; short prose bullets for discussion-only parts.",
    "time_budget_minutes: 20-90 (typically 45).",
    "Intelligence level (use payload.section_c_intelligence.target_difficulty): supportive = clearer scenario, more guided requirements; standard = typical ACCA exam difficulty; stretch = more complex scenario or integrated requirements.",
    "Use payload.section_c_intelligence.target_difficulty to tune scenario complexity.",
    "If payload.section_c_intelligence.rubric_emphasis is set, emphasise that skill in one requirement.",
    "Grammar: scenario, requirements, and model_answer_outline must be in correct English with no grammatical or spelling errors.",
]

# FR / financial reporting: appended to Section C generation when module is FR (acca_f7 or Financial Reporting title).
SECTION_C_FR_EXTRA_RULES = [
    "FR focus: At least one requirement should use Prepare or Present (e.g. 'Prepare the statement of financial position for …', 'Prepare the statement of cash flows …', 'Prepare extracts of notes to the financial statements …'). Other parts may be calculation, explanation, or interpretation as appropriate.",
    "Marks split: When using preparation tasks, typical split is (a) main statement 10–14 marks, (b) second statement or detailed workings 4–8 marks, (c) short explanation, disclosure, or recommendation 2–6 marks; total must remain 20.",
    "model_answer_outline: For any part that asks to prepare or present a statement, the matching bullet must be a clear statement skeleton (key headings and line items, e.g. non-current assets, current assets, equity, subtotals), not only a generic narrative.",
    "Use IFRS/IAS terminology where the scenario implies a standard (e.g. IAS 1 presentation, IAS 7 cash flows, relevant recognition standards).",
]

# Syllabus extraction: default role for build_syllabus_extraction_prompt and reconfig.
SYLLABUS_EXTRACTION_ROLE_DEFAULT = (
    "You are parsing a syllabus document. Extract every learning outcome (bullet or numbered item that describes what the candidate must be able to do or know). "
    "For each outcome provide: id (short identifier e.g. A1a, B2c), text (outcome statement in correct English, no grammatical errors), level (1=knowledge, 2=application, 3=analysis/synthesis; use 2 if unclear), chapter (exactly one of the chapter titles below; copy verbatim)."
)

# Assessment judge: role + rules; services builds prompt with module, topic, question, answer.
ASSESSMENT_JUDGE_ROLE_BASE = (
    "You are an ACCA examiner. Judge the learner's answer for correctness and quality. Use syllabus expertise only; do not match keywords."
)
ASSESSMENT_JUDGE_RULES = [
    "Use examiner-style wording: brief, constructive, and focused on what to improve (no praise without substance).",
    "Return JSON only (no prose). Schema:",
    "Rules: outcome correct = full marks for accurate, complete answer; partial = some right ideas; incorrect = wrong or irrelevant. feedback must be brief, constructive, and plain human-readable text (no LaTeX, no code blocks; write formulas as humans do, e.g. a/b, x²).",
    "Grammar: feedback and suggested_next_step must be in correct English with no grammatical or spelling errors.",
]

# Reconfig: static prompt prefixes (reconfig appends context + chapters and JSON_ONLY_NO_MARKDOWN).
RECONFIG_CAPABILITIES_PROMPT_PREFIX = (
    "You are parsing a syllabus document. From the excerpt below extract three things.\n"
    "1. capabilities: the COMPLETE list of section letters (A, B, C, D, ...) to their full title as in the syllabus. Include every capability that appears.\n"
    "2. aliases: for each chapter in the list, alternative names or abbreviations used in the document (e.g. 'FM' for 'Financial Management'). Use exact chapter strings as keys.\n"
    "3. chapter_to_capability: map each chapter (exact string from the list) to the single capability letter it belongs to (A, B, C, ...). Every chapter must be mapped.\n"
    "Schema (JSON only, no markdown):\n"
    '{"capabilities":{"A":"Full title for A","B":"Full title for B"},'
    '"aliases":{"Exact Chapter Title":["alias1"]},'
    '"chapter_to_capability":{"Exact Chapter Title":"A"}}\n'
    "Rules: Use only the excerpt as evidence. Use exact chapter strings from the list. Return valid JSON only.\n"
    "Excerpt:\n---\n"
)
RECONFIG_SYLLABUS_META_PROMPT_PREFIX = (
    "You are parsing syllabus metadata from a syllabus or study guide. Extract:\n"
    "1. exam_code: the ACCA exam code (e.g. FM, FR, AA) if present.\n"
    "2. effective_window: the exam session or date window (e.g. September 2024, 2024-2025) if present.\n"
    'Return JSON only, no markdown: {"exam_code": "...", "effective_window": "..."}\n'
    "Use null for missing values. Use only the excerpt as evidence.\n"
    "Excerpt:\n---\n"
)
RECONFIG_SUBTOPICS_PROMPT_PREFIX = (
    "You are parsing a syllabus or study guide. For each chapter in the list, extract the main "
    "section or subtopic titles (short phrases, e.g. 'Conceptual framework', 'Revenue recognition'). "
    "Use ONLY the excerpt as evidence. Use exact chapter strings as keys.\n"
    'Return JSON only, no markdown: {"Exact Chapter Title": ["subtopic1", "subtopic2"], ...}\n'
    "Excerpt:\n---\n"
)

# Known task IDs for get_task_prompt_spec (app and benchmark use these).
TASK_ID_AUTOPILOT = "autopilot"
TASK_ID_COACH = "coach"
TASK_ID_GAP_GENERATION = "gap_generation"
TASK_ID_SECTION_C = "section_c"
TASK_ID_CLASSIFICATION_DRILL = "classification_drill"

CLASSIFICATION_DRILL_RULES = [
    "Same JSON schema and length-balance rules as gap_generation (chapter + questions array or bare array).",
    "Every stem in this batch uses presentation/classification or disclosure focus: where reported, which statement, "
    "which section (operating/investing/financing), or required disclosures under a standard.",
    "Options must name real statement areas (SoFP/SoPL/SoCF/notes; equity/liabilities/NCA/current assets; OCI; etc.) "
    "— not vague wording.",
    GRAMMAR_QUALITY_RULE,
]

_TASK_SPECS: dict[str, dict[str, object]] = {
    TASK_ID_AUTOPILOT: {
        "role_base": AUTOPILOT_ROLE_BASE,
        "role_suffix": AUTOPILOT_ROLE_SUFFIX,
        "rules": AUTOPILOT_RULES,
        "schema_one_line": AUTOPILOT_ACTION_SCHEMA_ONE_LINE,
    },
    TASK_ID_COACH: {
        "role_base": COACH_ROLE_BASE,
        "role_suffix": COACH_ROLE_SUFFIX,
        "rules": COACH_RULES,
        "schema_one_line": COACH_SCHEMA_ONE_LINE,
    },
    TASK_ID_GAP_GENERATION: {
        "role_base": GAP_GENERATION_ROLE_BASE,
        "rules": GAP_GENERATION_RULES,
        "schema_one_line": GAP_SCHEMA_ONE_LINE,
    },
    TASK_ID_SECTION_C: {
        "role_base": SECTION_C_ROLE_BASE,
        "rules": SECTION_C_RULES,
        "schema_one_line": SECTION_C_SCHEMA_ONE_LINE,
    },
    TASK_ID_CLASSIFICATION_DRILL: {
        "role_base": GAP_GENERATION_ROLE_BASE,
        "rules": CLASSIFICATION_DRILL_RULES,
        "schema_one_line": GAP_SCHEMA_ONE_LINE,
    },
}

# Optional versioned overrides for A/B or rollout. Key: task_id -> version -> spec (same shape as _TASK_SPECS).
# Env STUDYPLAN_PROMPT_VERSION_<TASK_ID> (e.g. STUDYPLAN_PROMPT_VERSION_autopilot=v2) selects version.
_TASK_SPEC_VERSIONS: dict[str, dict[str, dict[str, object]]] = {}


def get_prompt_version(task_id: str) -> str:
    """
    Return the prompt version to use for this task (for A/B or rollout).

    Reads STUDYPLAN_PROMPT_VERSION_<TASK_ID> (task_id uppercased). Returns "default" if unset or empty.
    """
    key = "STUDYPLAN_PROMPT_VERSION_" + (task_id or "").strip().upper()
    raw = (os.environ.get(key) or "").strip().lower()
    return raw if raw else "default"


def section_c_schema_one_line(module_id: str = "", module_title: str = "") -> str:
    """Section C JSON schema hint; FR modules get stricter model_answer_outline wording."""
    base = str(SECTION_C_SCHEMA_ONE_LINE or "").strip()
    if section_c_fr_extra_rules(module_id, module_title):
        return base + SECTION_C_SCHEMA_FR_SUFFIX
    return base


def gap_fr_classification_extra_rules(module_id: str = "", module_title: str = "") -> list[str]:
    """Extra gap-generation rules for FR (classification / disclosure MCQs)."""
    mid = (module_id or "").strip().lower()
    title_l = (module_title or "").strip().lower()
    if mid != "acca_f7" and "financial reporting" not in title_l:
        return []
    return list(GAP_FR_CLASSIFICATION_EXTRA_RULES)


def section_c_fr_extra_rules(module_id: str = "", module_title: str = "") -> list[str]:
    """
    Return extra Section C rules for FR (Financial Reporting) modules.

    Used by the app when building Section C generation prompts so cases align with
    statement preparation and presentation-style requirements.
    """
    mid = (module_id or "").strip().lower()
    title_l = (module_title or "").strip().lower()
    if mid != "acca_f7" and "financial reporting" not in title_l:
        return []
    return list(SECTION_C_FR_EXTRA_RULES)


def get_task_prompt_spec(task_id: str, version: str | None = None) -> dict[str, object]:
    """
    Return the canonical prompt spec for an in-app AI task.

    Spec may include: role_base, role_suffix (app injects runtime_contract between them),
    rules (list[str]), schema_one_line. Used so app and benchmark share one source of truth.

    If version is None, uses get_prompt_version(task_id) (env STUDYPLAN_PROMPT_VERSION_<task_id>).
    When version is not "default" and _TASK_SPEC_VERSIONS has that version for task_id, returns it;
    otherwise returns the default spec. Schema contract is unchanged; only role/rules text may differ by version.
    """
    resolved = (version or get_prompt_version(task_id)).strip().lower() or "default"
    if resolved != "default":
        versions = _TASK_SPEC_VERSIONS.get(task_id, {})
        if resolved in versions:
            return dict(versions[resolved])
    spec = _TASK_SPECS.get(task_id)
    if spec is None:
        raise KeyError(f"Unknown task_id: {task_id!r}. Known: {list(_TASK_SPECS.keys())}")
    return dict(spec)

# --- 3Es contract: Role → Schema → Rules → Payload (one builder per prompt type; no duplication) ---
# See docs/THREE_ES_PROMPT_IMPLEMENTATION.md. Generation tasks use build_generation_prompt;
# syllabus extraction uses build_syllabus_extraction_prompt; assessment judge uses build_judge_prompt_3es.


def build_generation_prompt(
    *,
    role_and_style: str,
    schema_one_line: str,
    rules: list[str],
    payload_json: str,
    extra_rules: list[str] | None = None,
) -> str:
    """
    Build a single-shot generation prompt with schema-first order.

    Order: role/style → Schema: → Rules: → Payload JSON: → payload_json.
    Keeps tokens minimal and format clear for high first-try parse rate.
    """
    parts = [role_and_style.strip(), "Schema:", schema_one_line.strip(), "Rules:"]
    for r in list(rules or []) + list(extra_rules or []):
        r = str(r or "").strip()
        if r:
            parts.append("- " + r)
    parts.append("Payload JSON:")
    parts.append(payload_json.strip())
    return "\n".join(parts)


def append_retry_suffix(prompt: str, suffix: str) -> str:
    """Append a fail-safe retry suffix (e.g. JSON only, one item)."""
    base = (prompt or "").strip()
    add = (suffix or "").strip()
    if not add:
        return base
    return base + "\n\n" + add


def build_judge_prompt_3es(
    *,
    role_base: str,
    schema_one_line: str,
    rules: list[str],
    payload_blocks: list[tuple[str, str]],
) -> str:
    """
    Build assessment-judge prompt in 3Es order: Role → Schema → Rules → Payload.

    payload_blocks: list of (label, value) e.g. [("Module", "FR"), ("Question", "…"), ("Learner answer", "…")].
    Caller truncates question/answer lengths; this function does not truncate.
    """
    parts = [
        (role_base or "").strip(),
        "Schema:",
        (schema_one_line or "").strip(),
        "Rules:",
    ]
    for r in list(rules or []):
        r = str(r or "").strip()
        if r:
            parts.append("- " + r)
    parts.append("Payload:")
    for label, value in list(payload_blocks or []):
        if (label or "").strip():
            parts.append(f"{label.strip()}: {str(value or '').strip()}")
    parts.append("")
    parts.append("JSON:")
    return "\n".join(parts)


def build_syllabus_extraction_prompt(
    *,
    syllabus_text: str,
    chapters_blob: str,
    role_and_style: str | None = None,
    schema_one_line: str | None = None,
    rules: list[str] | None = None,
) -> str:
    """Schema-first prompt for syllabus outcome extraction. Order: role → Schema → Rules → Syllabus text → Chapters."""
    role = (role_and_style or SYLLABUS_EXTRACTION_ROLE_DEFAULT).strip()
    schema = (schema_one_line or SYLLABUS_OUTCOMES_SCHEMA_ONE_LINE).strip()
    rule_list = list(rules or [])
    rule_list.append(SYLLABUS_JSON_ONLY)
    parts = [role, "Schema:", schema, "Rules:"]
    for r in rule_list:
        r = str(r or "").strip()
        if r:
            parts.append("- " + r)
    parts.append("Syllabus text:")
    parts.append("---")
    parts.append((syllabus_text or "").strip())
    parts.append("---")
    parts.append("Chapters (use these exact strings for the \"chapter\" field):")
    parts.append((chapters_blob or "").strip())
    return "\n".join(parts)
