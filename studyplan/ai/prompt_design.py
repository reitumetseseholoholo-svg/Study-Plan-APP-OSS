"""
Prompt engineering for major AI actions: 3Es (Economy, Efficiency, Effectiveness) + fail-safe.

Use this module for:
- Shared snippets so prompts stay consistent and one-place editable.
- Schema-first, rules-then-payload structure for generation (Section C, MCQ/gap, syllabus, etc.).
- Retry suffixes for relaxed second attempts when parse fails.

Design: DEVELOPER_DOC.md § "Prompt engineering design (3Es + fail-safe)".
"""
from __future__ import annotations

# --- Economy: single source for common phrases (no duplication across actions) ---

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

GAP_SCHEMA_ONE_LINE = '{"chapter":"chapter","questions":[{"question":"text","options":["A","B","C","D"],"correct":"A","explanation":"short why"}]}'
SECTION_C_SCHEMA_ONE_LINE = (
    '{"chapter":"...","scenario":"Full case narrative (company, situation, numbers). 150-400 words. No placeholders.",'
    '"requirements":[{"part":"a","requirement_text":"Requirement with command verb (e.g. Calculate, Evaluate, Recommend).","marks":8},'
    '{"part":"b","requirement_text":"...","marks":8},{"part":"c","requirement_text":"...","marks":4}],'
    '"model_answer_outline":["...","...","..."],"time_budget_minutes":45}'
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

# --- Efficiency: consistent structure = schema first, then rules, then payload ---


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


def build_syllabus_extraction_prompt(
    *,
    syllabus_text: str,
    chapters_blob: str,
    role_and_style: str = "You are parsing a syllabus document. Extract every learning outcome (bullet or numbered item that describes what the candidate must be able to do or know). For each outcome provide: id (short identifier e.g. A1a, B2c), text (outcome statement), level (1=knowledge, 2=application, 3=analysis/synthesis; use 2 if unclear), chapter (exactly one of the chapter titles below; copy verbatim).",
    schema_one_line: str | None = None,
    rules: list[str] | None = None,
) -> str:
    """Schema-first prompt for syllabus outcome extraction. Order: role → Schema → Rules → Syllabus text → Chapters."""
    schema = (schema_one_line or SYLLABUS_OUTCOMES_SCHEMA_ONE_LINE).strip()
    rule_list = list(rules or [])
    rule_list.append(SYLLABUS_JSON_ONLY)
    parts = [role_and_style.strip(), "Schema:", schema, "Rules:"]
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
