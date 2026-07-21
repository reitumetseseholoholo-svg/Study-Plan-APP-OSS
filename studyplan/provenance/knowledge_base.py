"""FM Knowledge Base — investment_appraisal chapter.

Structured chapter: sources → formulas → pedagogical content.
No flat graph. No redundant relationship declarations.
"""

from studyplan.provenance.knowledge_ir import (
    FMKnowledgeBase,
    FMChapter,
    FMFormula,
    FormulaParam,
    Assumption,
    FMPedagogicalSet,
    PedagogicalArtifact,
    LearningObjective,
    FMSource,
)

# ====================================================================
# Sources
# ====================================================================

_SRC_STUDY_TEXT = FMSource("src_study_text", "ACCA FM Study Text", "study_text", authority=0.9)
_SRC_FORMULAE = FMSource("src_formulae", "ACCA FM Formulae Sheet", "formulae_sheet", authority=0.8)
_SRC_REVISION = FMSource("src_revision", "ACCA FM Revision Kit", "revision_kit", authority=0.7)
_SRC_EXAMINER = FMSource("src_examiner", "ACCA Examiner Report", "examiner_report", authority=0.85)
_SRC_PAST_PAPER = FMSource("src_past_paper", "ACCA FM Past Paper", "past_paper", authority=0.75)

# ====================================================================
# Formulas (self-contained, structured, compilable)
# ====================================================================

_F_NPV = FMFormula(
    concept_id="fm.npv",
    label="Net Present Value",
    description="NPV = sum of discounted cash flows minus initial investment.",
    expression="sum(cf / (1 + r)^t for t, cf in enumerate(cashflows, 1)) - initial",
    params=(
        FormulaParam("initial", "value", "initial_investment"),
        FormulaParam("r", "percent", "discount_rate"),
        FormulaParam("cashflows", "list", "cash_flows"),
    ),
    output_concept_id="fm.npv",
    assumes=(
        Assumption("constant_discount_rate", "discount rate is constant across all periods"),
        Assumption("periodic_cash_flows", "cash flows occur at period ends"),
    ),
    dependencies=(),
    diagnostic_tags=("sign_error", "wrong_discount_rate", "omit_initial"),
    centrality=0.9,
    source_ids=("src_study_text", "src_formulae"),
)

_F_PAYBACK = FMFormula(
    concept_id="fm.payback",
    label="Payback Period",
    description="Time for cumulative cash flows to recover initial investment.",
    expression="payback_period(initial, cashflows)",
    params=(
        FormulaParam("initial", "value", "initial_investment"),
        FormulaParam("cashflows", "list", "cash_flows"),
    ),
    output_concept_id="fm.payback",
    assumes=(),
    dependencies=(),
    diagnostic_tags=("cumulative_error", "fractional_year_error"),
    centrality=0.6,
    source_ids=("src_study_text", "src_formulae"),
)

_F_DISCOUNTED_PAYBACK = FMFormula(
    concept_id="fm.discounted_payback",
    label="Discounted Payback Period",
    description="Time for cumulative DISCOUNTED cash flows to recover initial investment.",
    expression="discounted_payback_period(initial, cashflows, r)",
    params=(
        FormulaParam("initial", "value", "initial_investment"),
        FormulaParam("r", "percent", "discount_rate"),
        FormulaParam("cashflows", "list", "cash_flows"),
    ),
    output_concept_id="fm.discounted_payback",
    assumes=(
        Assumption("constant_discount_rate", "discount rate is constant across all periods"),
        Assumption("periodic_cash_flows", "cash flows occur at period ends"),
    ),
    dependencies=(),
    diagnostic_tags=("pv_error", "cumulative_error"),
    centrality=0.6,
    source_ids=("src_study_text", "src_formulae"),
)

_F_IRR = FMFormula(
    concept_id="fm.irr",
    label="Internal Rate of Return",
    description="The discount rate at which NPV = 0.",
    expression="irr_interpolation(initial, cashflows, low_rate, high_rate)",
    params=(
        FormulaParam("initial", "value", "initial_investment"),
        FormulaParam("cashflows", "list", "cash_flows"),
        FormulaParam("low_rate", "percent", "lower_trial_rate"),
        FormulaParam("high_rate", "percent", "higher_trial_rate"),
    ),
    output_concept_id="fm.irr",
    assumes=(
        Assumption("single_irr", "cash flows have only one sign change"),
        Assumption("periodic_cash_flows", "cash flows occur at period ends"),
    ),
    dependencies=("fm.npv",),
    diagnostic_tags=("interpolation_error", "sign_error"),
    centrality=0.75,
    source_ids=("src_study_text", "src_formulae"),
)

_F_ARR = FMFormula(
    concept_id="fm.arr",
    label="Accounting Rate of Return",
    description="Average annual profit / average investment.",
    expression="(avg_profit / avg_investment) * 100",
    params=(
        FormulaParam("avg_profit", "value", "average_annual_profit"),
        FormulaParam("avg_investment", "value", "average_investment"),
    ),
    output_concept_id="fm.arr",
    assumes=(),
    dependencies=(),
    diagnostic_tags=("avg_investment_error", "profit_error"),
    centrality=0.55,
    source_ids=("src_study_text", "src_formulae"),
)

_F_PI = FMFormula(
    concept_id="fm.profitability_index",
    label="Profitability Index",
    description="PV of future cash flows / initial investment.",
    expression="pv_future_cfs / initial",
    params=(
        FormulaParam("pv_future_cfs", "value", "pv_of_future_cash_flows"),
        FormulaParam("initial", "value", "initial_investment"),
    ),
    output_concept_id="fm.profitability_index",
    assumes=(),
    dependencies=("fm.npv",),
    diagnostic_tags=("pv_error", "investment_error"),
    centrality=0.6,
    source_ids=("src_study_text", "src_formulae"),
)

_F_PERPETUITY_NPV = FMFormula(
    concept_id="fm.perpetuity_npv",
    label="Present Value of a Perpetuity",
    description="PV = annual cash flow / discount rate.",
    expression="annual_cf / r",
    params=(
        FormulaParam("annual_cf", "value", "annual_cash_flow"),
        FormulaParam("r", "percent", "discount_rate"),
    ),
    output_concept_id="fm.perpetuity_npv",
    assumes=(
        Assumption("constant_cash_flow", "cash flow amount is identical each period"),
        Assumption("constant_discount_rate", "discount rate is constant"),
    ),
    dependencies=(),
    diagnostic_tags=("rate_error", "cashflow_error"),
    centrality=0.55,
    source_ids=("src_study_text", "src_formulae"),
)

_F_EAC = FMFormula(
    concept_id="fm.equivalent_annual_cost",
    label="Equivalent Annual Cost",
    description="Annualized cost of an asset over its life.",
    expression="pv_costs / annuity_factor(r, n)",
    params=(
        FormulaParam("pv_costs", "value", "present_value_of_costs"),
        FormulaParam("r", "percent", "discount_rate"),
        FormulaParam("n", "value", "asset_life_years"),
    ),
    output_concept_id="fm.equivalent_annual_cost",
    assumes=(Assumption("constant_discount_rate", "discount rate is constant"),),
    dependencies=(),
    diagnostic_tags=("pvifa_error", "annuity_error"),
    centrality=0.65,
    source_ids=("src_study_text", "src_formulae"),
)

# ====================================================================
# Pedagogical sets (all teachable content for each concept)
# ====================================================================

_PED_NPV = FMPedagogicalSet(
    concept_id="fm.npv",
    definitions=(
        PedagogicalArtifact(
            "def_npv",
            "definition",
            "Net Present Value (NPV) is the difference between the present "
            "value of future cash inflows and the present value of cash "
            "outflows. A positive NPV indicates the project generates more "
            "value than its cost and should be accepted under the NPV rule.",
            source_id="src_study_text",
            bloom_level="understand",
            difficulty="easy",
        ),
    ),
    formulas=(
        PedagogicalArtifact(
            "formula_npv",
            "formula",
            "NPV = CF₁/(1+r)¹ + CF₂/(1+r)² + ... + CFₙ/(1+r)ⁿ - I₀",
            source_id="src_formulae",
            bloom_level="apply",
            difficulty="medium",
        ),
    ),
    worked_examples=(
        PedagogicalArtifact(
            "example_npv",
            "worked_example",
            "Project X: Initial investment $100,000. Cash flows: Y1 $30,000, "
            "Y2 $40,000, Y3 $50,000. Discount rate 10%.\n"
            "PV(Y1) = 30,000/1.1 = 27,273\n"
            "PV(Y2) = 40,000/1.1² = 33,058\n"
            "PV(Y3) = 50,000/1.1³ = 37,566\n"
            "Total PV = 97,897\n"
            "NPV = 97,897 - 100,000 = -2,103 (Reject)",
            source_id="src_revision",
            bloom_level="apply",
            difficulty="medium",
        ),
    ),
    misconceptions=(
        PedagogicalArtifact(
            "mis_npv_ignore_time",
            "misconception",
            "Students often simply add up all cash flows without discounting. "
            "NPV requires discounting each cash flow to its present value "
            "because money has time value.",
            source_id="src_examiner",
            bloom_level="understand",
            difficulty="easy",
        ),
    ),
    exam_questions=(
        PedagogicalArtifact(
            "q_npv_basic",
            "exam_question",
            "A company is considering a project with an initial investment "
            "of $200,000. Expected cash flows: Y1 $60,000, Y2 $80,000, "
            "Y3 $90,000, Y4 $50,000. Cost of capital 12%.\n"
            "(a) Calculate the NPV.\n"
            "(b) Advise whether the project should be accepted.",
            source_id="src_past_paper",
            bloom_level="apply",
            difficulty="medium",
        ),
    ),
    examiner_guidance=(
        PedagogicalArtifact(
            "examiner_npv",
            "examiner_guidance",
            "Common NPV mistakes: (1) forgetting to deduct initial "
            "investment, (2) using wrong discount rate, (3) inconsistent "
            "timing assumptions. Always state your recommendation clearly.",
            source_id="src_examiner",
            bloom_level="understand",
            difficulty="easy",
        ),
    ),
)

_PED_PAYBACK = FMPedagogicalSet(
    concept_id="fm.payback",
    definitions=(
        PedagogicalArtifact(
            "def_payback",
            "definition",
            "Payback period is the length of time required to recover the "
            "initial investment from the project's cash inflows. Decision "
            "rule: accept if payback < target period set by management.",
            source_id="src_study_text",
            bloom_level="understand",
            difficulty="easy",
        ),
    ),
    formulas=(
        PedagogicalArtifact(
            "formula_payback",
            "formula",
            "Payback = Year before full recovery + (Unrecovered / CF in recovery year)",
            source_id="src_formulae",
            bloom_level="apply",
            difficulty="medium",
        ),
    ),
    worked_examples=(
        PedagogicalArtifact(
            "example_payback",
            "worked_example",
            "Project Y: Initial investment $60,000. Cash flows: Y1 $20,000, "
            "Y2 $30,000, Y3 $25,000.\n"
            "Cumulative after Y1: $20,000\n"
            "Cumulative after Y2: $50,000\n"
            "Cumulative after Y3: $75,000 (recovered)\n"
            "Payback = 2 + (60,000 - 50,000)/25,000 = 2.4 years",
            source_id="src_revision",
            bloom_level="apply",
            difficulty="medium",
        ),
    ),
    misconceptions=(
        PedagogicalArtifact(
            "mis_payback_ignore_post",
            "misconception",
            "Students sometimes forget that payback ignores cash flows after "
            "the payback date, which may lead to rejecting highly profitable "
            "long-term projects.",
            source_id="src_examiner",
            bloom_level="understand",
            difficulty="easy",
        ),
    ),
)

_PED_IRR = FMPedagogicalSet(
    concept_id="fm.irr",
    definitions=(
        PedagogicalArtifact(
            "def_irr",
            "definition",
            "Internal Rate of Return (IRR) is the discount rate at which the "
            "NPV of all cash flows equals zero. Decision rule: accept if IRR "
            "> cost of capital. May give incorrect rankings when comparing "
            "mutually exclusive projects.",
            source_id="src_study_text",
            bloom_level="understand",
            difficulty="medium",
        ),
    ),
    formulas=(
        PedagogicalArtifact(
            "formula_irr",
            "formula",
            "IRR = L + [NPVₗ / (NPVₗ - NPVₕ)] × (H - L)",
            source_id="src_formulae",
            bloom_level="apply",
            difficulty="hard",
        ),
    ),
    worked_examples=(
        PedagogicalArtifact(
            "example_irr",
            "worked_example",
            "Project Z: Initial $50,000. CF Y1 $20,000, Y2 $25,000, Y3 $20,000.\n"
            "Try 15%: NPV = 20,000/1.15 + 25,000/1.15² + 20,000/1.15³ - 50,000 = -555\n"
            "Try 12%: NPV = 17,857 + 19,930 + 14,237 - 50,000 = 2,024\n"
            "IRR = 12% + [2,024/(2,024 + 555)] × 3% = 14.36%",
            source_id="src_revision",
            bloom_level="apply",
            difficulty="hard",
        ),
    ),
    misconceptions=(
        PedagogicalArtifact(
            "mis_irr_mutually_exclusive",
            "misconception",
            "A common error is choosing the project with the higher IRR when "
            "projects are mutually exclusive. NPV is the correct decision "
            "criterion for mutually exclusive projects. IRR can rank "
            "differently due to scale and timing differences.",
            source_id="src_examiner",
            bloom_level="understand",
            difficulty="medium",
        ),
    ),
    exam_questions=(
        PedagogicalArtifact(
            "q_irr_interpolation",
            "exam_question",
            "A project has an initial outlay of $150,000 and generates "
            "$55,000 per year for 4 years. Using trial rates of 15% and 20%, "
            "calculate the IRR using interpolation.",
            source_id="src_past_paper",
            bloom_level="apply",
            difficulty="hard",
        ),
    ),
    examiner_guidance=(
        PedagogicalArtifact(
            "examiner_irr",
            "examiner_guidance",
            "When using interpolation, work to at least one decimal place. "
            "Show both NPV calculations clearly. If NPV changes sign between "
            "two rates, the IRR lies between them.",
            source_id="src_examiner",
            bloom_level="understand",
            difficulty="medium",
        ),
    ),
)

_PED_ARR = FMPedagogicalSet(
    concept_id="fm.arr",
    definitions=(
        PedagogicalArtifact(
            "def_arr",
            "definition",
            "Accounting Rate of Return (ARR) measures the average annual "
            "accounting profit as a percentage of the average investment. "
            "Decision rule: accept if ARR > target return. Has limitations: "
            "uses profit not cash, ignores time value.",
            source_id="src_study_text",
            bloom_level="understand",
            difficulty="easy",
        ),
    ),
    formulas=(
        PedagogicalArtifact(
            "formula_arr",
            "formula",
            "ARR = (Average annual profit / Average investment) × 100%",
            source_id="src_formulae",
            bloom_level="apply",
            difficulty="easy",
        ),
    ),
)

_PED_PI = FMPedagogicalSet(
    concept_id="fm.profitability_index",
    definitions=(
        PedagogicalArtifact(
            "def_pi",
            "definition",
            "Profitability Index (PI) is the ratio of the present value of "
            "future cash flows to the initial investment. Used for capital "
            "rationing decisions: select projects with the highest PI.",
            source_id="src_study_text",
            bloom_level="understand",
            difficulty="medium",
        ),
    ),
    formulas=(
        PedagogicalArtifact(
            "formula_pi",
            "formula",
            "PI = PV of future cash flows / Initial investment",
            source_id="src_formulae",
            bloom_level="apply",
            difficulty="medium",
        ),
    ),
)

_PED_DISCOUNTED_PAYBACK = FMPedagogicalSet(
    concept_id="fm.discounted_payback",
    definitions=(
        PedagogicalArtifact(
            "def_discounted_payback",
            "definition",
            "Discounted Payback Period is the time required for the cumulative "
            "discounted cash flows to recover the initial investment. Unlike "
            "standard payback, it accounts for the time value of money.",
            source_id="src_study_text",
            bloom_level="understand",
            difficulty="medium",
        ),
    ),
    formulas=(
        PedagogicalArtifact(
            "formula_discounted_payback",
            "formula",
            "Discounted Payback = Year before discounted recovery + "
            "(Cumulative discounted negative / Discounted CF in recovery year)",
            source_id="src_formulae",
            bloom_level="apply",
            difficulty="medium",
        ),
    ),
)

# ====================================================================
# Chapter with learning objectives
# ====================================================================

LO_INVESTMENT_APPRAISAL = (
    LearningObjective("lo_npv_calc", "Calculate NPV and interpret results", "apply", ("fm.npv",)),
    LearningObjective("lo_irr_calc", "Calculate IRR using interpolation", "apply", ("fm.irr",)),
    LearningObjective(
        "lo_payback_calc", "Calculate payback and discounted payback", "apply", ("fm.payback", "fm.discounted_payback")
    ),
    LearningObjective("lo_arr_calc", "Calculate ARR and understand its limitations", "apply", ("fm.arr",)),
    LearningObjective(
        "lo_pi_calc", "Calculate profitability index for capital rationing", "apply", ("fm.profitability_index",)
    ),
    LearningObjective(
        "lo_compare_methods",
        "Compare investment appraisal methods and recommend the best",
        "evaluate",
        ("fm.npv", "fm.irr", "fm.payback", "fm.arr"),
    ),
)

# ====================================================================
# Knowledge Base assembly
# ====================================================================

_INVESTMENT_APPRAISAL = FMKnowledgeBase(
    chapter=FMChapter(
        id="investment_appraisal",
        title="Investment Appraisal",
        learning_objectives=LO_INVESTMENT_APPRAISAL,
    ),
    formulas={
        "fm.npv": _F_NPV,
        "fm.payback": _F_PAYBACK,
        "fm.discounted_payback": _F_DISCOUNTED_PAYBACK,
        "fm.irr": _F_IRR,
        "fm.arr": _F_ARR,
        "fm.profitability_index": _F_PI,
        "fm.perpetuity_npv": _F_PERPETUITY_NPV,
        "fm.equivalent_annual_cost": _F_EAC,
    },
    pedagogical={
        "fm.npv": _PED_NPV,
        "fm.payback": _PED_PAYBACK,
        "fm.irr": _PED_IRR,
        "fm.arr": _PED_ARR,
        "fm.profitability_index": _PED_PI,
        "fm.discounted_payback": _PED_DISCOUNTED_PAYBACK,
    },
    sources={
        "src_study_text": _SRC_STUDY_TEXT,
        "src_formulae": _SRC_FORMULAE,
        "src_revision": _SRC_REVISION,
        "src_examiner": _SRC_EXAMINER,
        "src_past_paper": _SRC_PAST_PAPER,
    },
)


def get_knowledge_base(chapter_id: str = "investment_appraisal") -> FMKnowledgeBase:
    if chapter_id == "investment_appraisal":
        return _INVESTMENT_APPRAISAL
    raise ValueError(f"Unknown chapter: {chapter_id}")
