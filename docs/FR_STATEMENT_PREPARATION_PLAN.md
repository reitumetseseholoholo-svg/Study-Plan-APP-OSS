# FR (Financial Reporting) & statement preparation – implementation plan

Plan to make the app effective for papers like **FR** where **financial statement preparation** is a core part of the learning outcomes (SoFP, SoPL, SoCF, notes). Complements existing MCQ, Section C, and tutor flows with preparation-focused practice and format awareness.

---

## 1. Goals

1. **Support “prepare” outcomes** – Treat “Prepare the statement of financial position” (and similar) as first-class: link to statement-focused tasks, not only MCQs.
2. **Format and disclosure** – Help learners practise correct layout, classification (current/non-current), and required disclosures (IAS 1, IAS 7, etc.).
3. **Reuse existing pieces** – Section C generation, outcome linking, tutor/RAG, and syllabus structure stay the backbone; add FR-specific prompts, schemas, and optional task types.
4. **Progressive delivery** – Quick wins (prompts, tagging, tutor) first; then format checklists and templates; then optional statement-builder or marking if needed.

---

## 2. Why FR is different

| Aspect | Typical papers | FR (and similar) |
|--------|----------------|------------------|
| **Outcomes** | “Explain…”, “Discuss…”, “Calculate…” | “**Prepare** the statement of financial position”, “**Prepare** the statement of cash flows”, “**Present** in accordance with IAS 1” |
| **Markers** | Correct answer, workings | **Format**, layout, classification, subtotals, **disclosure** |
| **Task shape** | MCQ, short calculation, essay | Multi-step: trial balance → adjustments → **draft statement** (SoFP/SoPL/SoCF/notes) |
| **Standards** | Concepts, formulas | **IFRS/IAS by name** (IFRS 15, 16, 9, IAS 1, 7, 23, 36…) with presentation and disclosure |

The app should support **doing** statement preparation and **getting feedback on structure and content**, not only answering MCQs or reading explanations.

---

## 3. Current state (relevant parts)

- **Section C**: `studyplan/ai/prompt_design.py` (SECTION_C_*), `studyplan_app.py` Section C generation and case UI. Schema: scenario + requirements (a)(b)(c) + model_answer_outline. No explicit “prepare statement” requirement type or statement-shaped model answer.
- **Outcomes**: `syllabus_structure[chapter].learning_outcomes` with `id`, `text`, `level`. No standard tag (e.g. IFRS 15) or outcome type (e.g. “preparation” vs “explain”).
- **Tutor / RAG**: Tutor prompt, RAG retrieval, syllabus scope. Can answer “how do I present X?” if RAG has the content; no dedicated “format” or “statement preparation” prompts.
- **Practice**: MCQ (gap generation), quiz, drill, outcome linking. No “statement preparation” or “fill statement” task type.
- **Module config**: `modules/<id>.json` with chapters, syllabus_structure, capabilities, aliases. No per-module “statement_templates” or “fr_section_c_spec”.

---

## 4. Phased implementation

### Phase 1 – Quick wins (prompts, tagging, tutor)

**Goal**: Better alignment with FR without new UI or new task types.

| # | Deliverable | Description | Where / how |
|---|-------------|-------------|-------------|
| 1.1 | **Outcome type / standard (optional)** | Allow outcomes to carry optional `type` (“preparation” | “explain” | “calculate”) and/or `standard` (“IAS 1”, “IFRS 16”) for filtering and analytics. | `syllabus_structure[ch].learning_outcomes[].type`, `standard`. Schema in `module_schema.json` (optional props). Reconfig/syllabus import: keep existing behaviour; extend only if source text or LLM extraction can infer (e.g. “Prepare…” → type=preparation). |
| 1.2 | **Section C: FR-oriented spec** | When generating Section C for FR (or when module is FR), add FR-specific rules: requirement parts can be “Prepare the statement of financial position (12 marks)”, “Prepare the statement of cash flows (8 marks)”; model answer to include **statement structure** (skeleton + key line items) where the requirement is preparation. | `studyplan/ai/prompt_design.py`: add optional FR_SECTION_C_RULES or a `section_c_variant: "default" | "fr"` in spec. App: when building Section C prompt, pass module_id or a “fr_mode” flag and use FR rules + schema hint (e.g. model_answer can be list of statement lines). |
| 1.3 | **Tutor / RAG for format** | Predefined or suggested prompts for format: “How do I format the statement of cash flows under IAS 7?”, “What are the minimum line items in the statement of financial position?”. Ensure RAG for FR module includes IAS/IFRS presentation and disclosure material. | App: add “Format & preparation” or “Statement format” quick prompts in tutor when module is FR (or when chapter is statement-related). RAG: prefer chunks that mention “statement of”, “IAS 1”, “IAS 7”, “presentation” when user asks about format. Optional: `get_syllabus_scope_instruction` or tutor context to mention “FR: focus on preparation and presentation where relevant”. |
| 1.4 | **“Preparation” in study plan** | In the study plan / dashboard, optionally highlight or filter outcomes that are preparation-type (e.g. “Prepare…”) so the learner can prioritise them. | Engine or app: when computing “next topic” or “weak areas”, optionally weight or tag outcomes whose text starts with “Prepare” or has type=preparation. No new UI required; can be a label or sort option. |

**Acceptance**: (1) Section C for FR can generate “Prepare SoFP/SoPL/SoCF” requirements and a statement-shaped model outline. (2) Tutor can be steered toward format/preparation when the user asks. (3) Outcome metadata supports type/standard without breaking existing modules.

---

### Phase 2 – Format and disclosure (checklists, drills)

**Goal**: Practise “what goes where” and “what must be disclosed” without building a full statement builder.

| # | Deliverable | Description | Where / how |
|---|-------------|-------------|-------------|
| 2.1 | **Format checklists (static)** | Per statement type (SoFP, SoPL, SoCF), a checklist of required format items (e.g. IAS 1 minimum line items, current/non-current split, subtotals). Shown as reference or “self-check” after a Section C attempt. | New data: `studyplan/data/statement_format_checklists.json` or embedded in a FR module config extension. Structure: `{ "SoFP": [ "Current/non-current distinction", "…" ], "SoCF": [ "Operating, investing, financing", "…" ] }`. UI: simple read-only view (e.g. in Section C feedback or Module metadata). |
| 2.2 | **“Where does it go?” drills** | MCQs or short tasks: “Where does revaluation surplus appear?” → SoFP (equity); “Operating lease payment in SoCF?” → operating activities. Can be generated (gap-style) or curated. | Reuse gap generation with a dedicated prompt/spec for “classification” questions: stem = “Where does [X] appear in the financial statements?”; options = statement + section (e.g. “SoFP – equity”, “SoCF – operating”). Store as normal MCQs with outcome_id linking to “presentation” or “preparation” outcomes. Optional: `get_task_prompt_spec("classification_drill")` in prompt_design. |
| 2.3 | **Disclosure quizzes** | “Which of the following must be disclosed for property, plant and equipment (IAS 16)?” with multi-select or single best answer. | Same as 2.2: either gap generation with disclosure-focused rules or a small bank of disclosure MCQs per standard. Outcome tags (standard) help link these to “IAS 16” etc. |

**Acceptance**: (1) Learners can open a format checklist for SoFP/SoPL/SoCF. (2) At least one “where does it go?” / classification drill flow exists (e.g. new prompt spec or question bank). (3) Disclosure-style questions can be linked to standards/outcomes.

---

### Phase 3 – Statement templates and structured input

**Goal**: Let learners practise layout and key line items without full free-form editing.

| # | Deliverable | Description | Where / how |
|---|-------------|-------------|-------------|
| 3.1 | **Statement templates (static)** | Blank SoFP, SoPL, SoCF in exam-style layout (PDF or in-app HTML). Download or view only; no submission yet. | Add `studyplan/data/` or `modules/fr/` templates (e.g. `statement_fp_blank.pdf` or HTML). App: “View statement template” in Module menu or FR workspace when module is FR. |
| 3.2 | **Fill key line items (form)** | A simple form: “Complete the statement of financial position” with fields for key line items (Current assets, Non-current assets, Equity, etc.). Learner fills text or numbers; submit for self-check or simple validation (e.g. “current + non-current = total”). | New task type or “practice” mode: `task_type: "statement_fill"`, payload: statement type + list of line item keys. UI: form with labels; no drag-and-drop. Validation: optional rule-based (totals, current/non-current split) or compare to a model answer. Engine: store attempt in progress_log or a new `statement_attempts` structure. |
| 3.3 | **Partial preparation** | Tasks like “Prepare the PPE note” or “Prepare the current assets section” only. Could be a short Section C requirement (one part) or a dedicated “extract” task. | Reuse Section C with a single requirement: “Prepare the property, plant and equipment note (IAS 16).” Model answer = note structure. Or add `section_c_variant: "fr_extract"` with one-part requirement and note-style model answer. |

**Acceptance**: (1) At least one statement template is available for FR. (2) A “fill in the blanks” or form-based statement practice exists and can be linked to an outcome. (3) “Prepare extract” appears as a supported requirement type (Section C or dedicated).

---

### Phase 4 – Statement builder and marking (optional, larger)

**Goal**: Full “prepare statement” flow with structured output and optional marking.

| # | Deliverable | Description | Where / how |
|---|-------------|-------------|-------------|
| 4.1 | **Statement builder UI** | Drag-and-drop or ordered list of line items to build SoFP/SoPL/SoCF. Optional: enter figures per line. Save as “attempt” for review. | New UI component (e.g. in practice or Section C flow). Data: list of standard line items per statement type; learner order + values. Significant front-end work. |
| 4.2 | **Validation / marking** | Compare learner’s structure (and optionally figures) to a model: layout score, classification score, totals. Could be rule-based first (required lines present, current/non-current correct). | Engine or new module: `studyplan/statement_marking.py` with rules per statement type. Input: learner attempt (structure + optional numbers). Output: checklist pass/fail and optional score. |
| 4.3 | **Trial balance → adjustments → statement** | Full flow: show trial balance and adjustments; learner computes adjusted figures; then “prepare statement” using builder or form. | Combines Section C (scenario + adjustments) with statement builder or form. Requires integration between “adjustments” state and “statement” state; likely Phase 4 only. |

**Acceptance**: (1) Learner can produce a structured statement (order of lines ± figures) in-app. (2) At least one automatic check (e.g. “all required line items present”, “current/non-current”) runs on submission. (3) Optional: one end-to-end “trial balance → statement” flow.

---

## 5. Dependencies and order

- **Phase 1** depends only on current codebase; no new data format required (outcome type/standard optional).
- **Phase 2** can use Phase 1 outcome/standard tagging for “drill by standard” and disclosure links.
- **Phase 3** benefits from Phase 2 checklists (show alongside form or after submit).
- **Phase 4** builds on Phase 3 (templates and form become the basis for builder and marking).

**Suggested order**: 1.1 → 1.2 → 1.3 → 1.4 → 2.1 → 2.2 → 3.1 → 3.2 → 2.3 → 3.3; then 4.x if needed.

---

## 6. File and component map

| Area | Current | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|------|---------|---------|---------|---------|---------|
| **Prompt design** | `studyplan/ai/prompt_design.py` | FR Section C rules, optional variant | Classification/disclosure spec | – | – |
| **Module config** | `modules/<id>.json`, `module_schema.json` | Optional outcome `type`, `standard` | – | Optional `statement_templates` ref | – |
| **Section C** | App Section C generation + case UI | FR mode, statement-shaped model | – | fr_extract variant | – |
| **Tutor** | Tutor prompt, RAG, quick prompts | Format/preparation prompts (FR) | – | – | – |
| **Data** | – | – | `statement_format_checklists.json` | Statement templates (PDF/HTML) | – |
| **Practice / task types** | MCQ, quiz, drill | – | Classification drill (MCQ) | statement_fill task | Statement builder UI |
| **Engine** | – | – | – | Optional statement_attempts | statement_marking.py |

---

## 7. Open questions and future work

- **Standard tagging at scale**: Should outcome `standard` (e.g. IAS 1) come from syllabus text, from LLM during reconfig, or from a manual mapping file per module?
- **Section C marking**: When model answer is statement-shaped, should the app auto-mark learner statements (Phase 4) or only show model for self-check (Phase 3)?
- **Other papers**: Same “preparation” and “format” ideas can apply to other papers with presentation outcomes (e.g. SBL, AFM); FR is the first target.
- **Accessibility**: Statement builder and forms should work with keyboard and screen readers; templates should be readable (e.g. HTML or tagged PDF).

---

## 8. Summary

- **Phase 1**: Outcome type/standard, FR Section C spec, tutor format prompts, preparation visibility in plan. **No new UI.**
- **Phase 2**: Format checklists, “where does it go?” and disclosure drills. **Light new data + optional prompt spec.**
- **Phase 3**: Statement templates, fill-in form, partial preparation (extract). **New task type or Section C variant + templates.**
- **Phase 4** (optional): Statement builder, validation/marking, trial balance → statement flow. **Larger UI and engine work.**

This plan keeps the app’s existing syllabus refresh, outcome linking, and Section C infrastructure at the centre, and adds FR-specific behaviour and data in clear, testable steps.
