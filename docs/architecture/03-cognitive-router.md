# Chapter 3 — Cognitive Router

## 3.1 Motivation

The Recognition Engine (Cognitive Router) solves a problem the architecture ignored until now: **before reasoning begins, the learner must recognize what kind of reasoning situation they are in.**

A learner who treats an ethical dilemma as a compliance exercise does not have a protocol problem. They have a *routing* problem — the wrong reasoning runtime was activated. No amount of protocol optimization fixes this.

The Cognitive Router is the subsystem that answers:

> *What kind of cognitive situation is this?*

It performs classification on the problem surface, selects the appropriate reasoning runtime, and determines whether the required protocol is compiled, constructible, or absent.

---

## 3.2 The Recognition Problem

### 3.2.1 Three failure modes

Any reasoning failure falls into exactly one of three categories:

| Type | Failure | Example |
|------|---------|---------|
| **A — Execution** | Correct runtime, correct protocol, incorrect execution | Wrong NPV calculation |
| **B — Protocol** | Correct runtime, no protocol available | Knows this is ethical, has no framework |
| **C — Recognition** | Wrong runtime selected | Treats ethics as compliance checklist |

Types A and B are downstream of the router. Type C is the router's responsibility.

### 3.2.2 The router's contract

The Cognitive Router takes a problem description and returns:

```
Routing Decision {
    primary_runtime: RuntimeID       // dominant cognitive mode
    sub_runtimes: List[RuntimeID]    // supporting modes (possibly empty)
    protocol_status: ProtocolStatus  // COMPILED | CONSTRUCTIBLE | ABSENT
    confidence: Float                // 0.0 - 1.0
    evidence: List[String]           // surface features that drove the decision
}
```

Where `ProtocolStatus` is:

```
ProtocolStatus ::= COMPILED          // stable, repeatable, exists
                  | CONSTRUCTIBLE    // principles exist, synthesis required
                  | ABSENT           // neither protocol nor principles available
```

---

## 3.3 Taxonomy of Cognitive Situations

The taxonomy defines seven categories. Each is defined by:
- **Core operations**: the CISA instructions that dominate execution
- **Output type**: what a successful response looks like
- **Protocol structure**: how the protocol is organized
- **Recognition features**: surface features that distinguish the category

### 3.3.1 Computation

| Property | Value |
|----------|-------|
| Core ops | OBSERVE, RECALL (formula), CALCULATE, VERIFY |
| Output | Numeric value |
| Protocol | Linear, compiled, deterministic |
| Recognition | Verb: *calculate, compute, determine (numeric)*. Inputs are numerical. Known formula exists. |

**Examples**: NPV, WACC, IRR, EPS, tax liability, lease payment.

### 3.3.2 Classification

| Property | Value |
|----------|-------|
| Core ops | OBSERVE, RECALL (criteria), COMPARE, SELECT |
| Output | Categorical label |
| Protocol | Decision tree or threshold comparison |
| Recognition | Verb: *classify, identify (category), determine whether*. Binary or multi-class decision boundary. |

**Examples**: Finance vs. operating lease, current vs. non-current liability, acceptable vs. unacceptable risk.

### 3.3.3 Diagnosis

| Property | Value |
|----------|-------|
| Core ops | OBSERVE, RECALL (patterns), COMPARE, INFER, SELECT |
| Output | Identified condition + supporting evidence |
| Protocol | Generate hypotheses → test against evidence → select best explanation |
| Recognition | Verb: *diagnose, identify (problem), what is wrong*. Anomalous data present. Multiple candidate explanations. |

**Examples**: Audit misstatement identification, financial distress diagnosis, control deficiency identification, medical diagnosis.

### 3.3.4 Evaluation

| Property | Value |
|----------|-------|
| Core ops | OBSERVE, RECALL (criteria), COMPARE, EVALUATE, JUSTIFY |
| Output | Judgement + justification |
| Protocol | Retrieve criteria → apply to facts → form judgement → justify |
| Recognition | Verb: *evaluate, assess, comment on, is this appropriate*. Open-ended judgement against explicit or implicit criteria. |

**Examples**: Ethical conflict evaluation, going concern assessment, corporate governance evaluation, internal control effectiveness.

### 3.3.5 Construction

| Property | Value |
|----------|-------|
| Core ops | OBSERVE, RECALL (principles), GENERATE, EVALUATE, SELECT, JUSTIFY, PLAN |
| Output | Novel artifact (plan, recommendation, memorandum) |
| Protocol | Recursive: generate → evaluate → refine → finalize |
| Recognition | Verb: *prepare, draft, design, recommend, plan*. Output is synthetic, not extracted. |

**Examples**: Audit plan, financing recommendation, risk mitigation strategy, business memorandum.

### 3.3.6 Explanation

| Property | Value |
|----------|-------|
| Core ops | OBSERVE, INFER (causal), PREDICT, JUSTIFY |
| Output | Causal narrative |
| Protocol | Identify causal chain → link causes to effects → verify coherence |
| Recognition | Verb: *explain why, what would happen if, reason, discuss the impact of*. Asks for causal/temporal reasoning. |

**Examples**: "Explain why the share price fell", "What happens if interest rates rise?", "Discuss the impact of adopting IFRS 16."

### 3.3.7 Interpretation

| Property | Value |
|----------|-------|
| Core ops | OBSERVE, RECALL (principles), ASSOCIATE, INFER (meaning), JUSTIFY |
| Output | Meaning extraction + application to context |
| Protocol | Read → associate with principles → infer contextual meaning → apply |
| Recognition | Verb: *interpret, apply (standard/clause), explain the meaning of*. Text-heavy. Requires mapping general principles to specific facts. |

**Examples**: Apply IAS 36 impairment indicators to a scenario, interpret a contract clause, explain the accounting treatment of a transaction.

---

## 3.4 Reasoning Runtimes

Each cognitive situation routes to a reasoning runtime. A runtime is a computational environment that:
- Provides the instruction set (primitives from CISA)
- Manages protocol execution or construction
- Tracks execution trace
- Reports diagnostics

### 3.4.1 Runtime catalogue

| Runtime | Cognitive Situations | Protocol Type |
|---------|---------------------|---------------|
| Computational | Computation | Compiled |
| Taxonomic | Classification | Compiled |
| Diagnostic | Diagnosis | Constructed (from evidence patterns) |
| Evaluative | Evaluation | Constructed (from criteria) |
| Generative | Construction | Constructed (from principles) |
| Causal | Explanation | Constructed (from causal primitives) |
| Hermeneutic | Interpretation | Constructed (from principles + context) |

### 3.4.2 Runtime interface

```
Runtime {
    id: RuntimeID
    execute(protocol: Protocol, context: Situation) -> ExecutionTrace
    diagnose(trace: ExecutionTrace) -> List[DiagnosticSignal]
    protocol_for(situation: Situation) -> Protocol | None
}
```

`protocol_for` returns a compiled protocol if one exists, delegates to the Protocol Constructor if constructible, and returns `None` if absent.

---

## 3.5 Protocol Types

### 3.5.1 Compiled protocols

Stable, repeatable sequences. Pre-exist in the system. Linear or near-linear.

**Characteristics**:
- Deterministic output given correct inputs
- Low variance across executions
- Can be cached and reused
- Failure is usually execution error (Type A)

**Examples**: NPV calculation steps, journal entry format, ratio computation.

### 3.5.2 Constructed protocols

Synthesized at runtime from principles, criteria, or patterns.

**Characteristics**:
- Multiple valid outputs
- Higher variance across executions
- Generated by the Protocol Constructor from knowledge objects
- Failure may be missing principles (Type B) or faulty construction

**Examples**: Ethics analysis (synthesized from ethical principles + facts), audit plan (synthesized from risk assessment + procedures), going concern evaluation (synthesized from indicators + judgement).

### 3.5.3 Protocol construction

The Protocol Constructor is a subsystem of the Cognitive Router.

```
construct_protocol(
    runtime: RuntimeID,
    principles: List[Principle],
    context: Situation
) -> Protocol | ConstructionFailure
```

Construction follows the runtime's template. For example, the Evaluative runtime's template is:
1. RECALL criteria from principles
2. OBSERVE facts from context
3. COMPARE each fact against each criterion
4. EVALUATE overall judgement
5. JUSTIFY with evidence

If any step cannot be completed (e.g., no criteria exist for this situation), construction fails with a `ConstructionFailure` that specifies the missing component.

---

## 3.6 Routing Decision Procedure

The router uses a lightweight classifier operating on surface features of the problem.

### 3.6.1 Feature extraction

From the problem text and metadata, extract:

- **Verb class**: the primary action verb (calculate, classify, diagnose, evaluate, prepare, explain, interpret)
- **Output mode**: number, category, prose, artifact
- **Input structure**: numeric data, textual scenario, mixed, code
- **Formula presence**: is a known formula applicable? (lookup against knowledge graph)
- **Open-endedness**: is there a single correct answer or a range of defensible answers?
- **Principle density**: does the problem reference standards, principles, or criteria?
- **Causal markers**: "because", "if...then", "impact of", "why"

### 3.6.2 Decision procedure

```
function route(situation: Situation) -> RoutingDecision:
    features = extract_features(situation)

    // Rule 1: Closed-form computation
    if features.verb_class == COMPUTE and features.formula_present:
        return Computation(COMPILED, high_confidence)

    // Rule 2: Category assignment
    if features.verb_class in {CLASSIFY, IDENTIFY_CATEGORY}:
        return Taxonomic(COMPILED, high_confidence)

    // Rule 3: Diagnosis with anomalous data
    if features.verb_class in {DIAGNOSE, IDENTIFY_PROBLEM}
       and features.has_anomalous_data:
        return Diagnostic(CONSTRUCTIBLE, medium_confidence)

    // Rule 4: Judgement against criteria
    if features.verb_class in {EVALUATE, ASSESS, COMMENT}:
        protocol_status = CONSTRUCTIBLE if features.principles_exist else ABSENT
        return Evaluative(protocol_status, medium_confidence)

    // Rule 5: Synthetic output
    if features.verb_class in {PREPARE, DRAFT, DESIGN, RECOMMEND, PLAN}:
        return Generative(CONSTRUCTIBLE, medium_confidence)

    // Rule 6: Causal reasoning
    if features.verb_class in {EXPLAIN_WHY, PREDICT, DISCUSS_IMPACT}
       and features.causal_markers:
        return Causal(CONSTRUCTIBLE, medium_confidence)

    // Rule 7: Meaning extraction
    if features.verb_class in {INTERPRET, APPLY_STANDARD}:
        return Hermeneutic(CONSTRUCTIBLE, medium_confidence)

    // Fallback: low-confidence routing
    // Select runtime with highest feature overlap
    return best_guess_routing(features)
```

### 3.6.3 Confidence and fallback

When confidence is below a threshold (e.g., 0.6 for primary, 0.4 for sub-runtimes):

1. **Ask the learner**: "What kind of problem is this?" (meta-cognitive prompt — itself diagnostic)
2. **Execute multiple runtimes**: run the top-2 candidates and compare outputs
3. **Escalate to LLM**: use a general-purpose model as the emergency exit

---

## 3.7 Multi-Runtime Coordination

Many real problems activate multiple runtimes.

### 3.7.1 Runtime graph

A complex problem like audit planning activates:

```
Primary: Diagnosis (what is the risk?)
    |
    ├── Sub: Computation (materiality threshold)
    ├── Sub: Evaluation (control effectiveness)
    └── Sub: Construction (audit programme)
```

The router returns a primary runtime and an ordered list of sub-runtimes. The primary runtime's execution may suspend and delegate to sub-runtimes at specific protocol steps.

### 3.7.2 Handoff protocol

```
1. Primary begins execution
2. Primary reaches step requiring sub-runtime
3. Primary suspends, context passed to sub-runtime
4. Sub-runtime executes, returns result
5. Primary resumes with result
6. Trace records both primary and sub-runtime segments
```

### 3.7.3 Conflict arbitration

When two runtimes produce contradictory intermediate results (e.g., Computation says 100, Evaluation says "immaterial"), the system records the contradiction as a diagnostic signal rather than resolving it. The learner's handling of the contradiction is itself diagnostic of their understanding of how runtimes interact.

---

## 3.8 Validation Against Test Cases

### 3.8.1 Case 1: Closed-form computation (NPV)

*Situation*: "Calculate the NPV of a project with cash flows £100k/year for 5 years, discount rate 10%, initial investment £350k."

*Router output*:
- Primary runtime: Computational
- Protocol status: COMPILED
- Confidence: 0.98
- Evidence: verb=calculate, numeric inputs, formula=NPV exists

*Expected behavior*:
- Learner executes compiled NPV protocol
- Execution trace: OBSERVE → RECALL NPV formula → CALCULATE each PV → SUM → VERIFY
- Diagnosis on failure: Type A (wrong formula recalled, arithmetic error) or
  Type B (formula not recalled — rare at this level)

### 3.8.2 Case 2: Protocol acquisition (first-time WACC)

*Situation*: "Calculate the WACC for a company with 60% equity, 40% debt, cost of equity 12%, cost of debt 8%, tax rate 25%."

*Router output*:
- Primary runtime: Computational
- Protocol status: COMPILED
- Confidence: 0.95

*Why COMPILED?* WACC has a known formula. The protocol exists in the system even if the learner has never encountered it.

*But the learner may not have the protocol yet.* The router routes to the Computational runtime, which attempts to load the compiled protocol. If the learner fails, the diagnosis distinguishes:
- Type A: Formula recalled but applied incorrectly (e.g., forgot tax shield)
- Type B: Formula not recalled at all → system teaches the protocol, then retests

### 3.8.3 Case 3: Constructive reasoning (ethics)

*Situation*: "You discover your client has been misstating revenue. Your manager tells you to ignore it. What do you do?"

*Router output*:
- Primary runtime: Evaluative
- Sub-runtimes: Taxonomic (classify conflict type)
- Protocol status: CONSTRUCTIBLE
- Confidence: 0.82
- Evidence: verb=evaluate, principles=ACCA Code of Ethics present, open-ended

*Expected behavior*:
- Protocol Constructor synthesizes: RECALL fundamental principles → IDENTIFY threats → EVALUATE severity → GENERATE safeguards → EVALUATE residual risk → SELECT action → JUSTIFY
- Diagnosis distinguishes:
  - Type C (recognition): Learner treats as compliance → "find the rule that says what to do" vs. "exercise professional judgement"
  - Type B (protocol): Learner recognizes ethical dimension but has no framework
  - Type A (execution): Learner has framework but fails to construct a coherent argument

### 3.8.4 Case 4: Multi-runtime reasoning (audit)

*Situation*: "Assess the risk of material misstatement for a client in a declining industry. Recommend audit procedures."

*Router output*:
- Primary runtime: Diagnosis
- Sub-runtimes: [Evaluative, Computational, Generative]
- Protocol status: CONSTRUCTIBLE (primary), COMPILED (computational sub)
- Confidence: 0.74
- Evidence: verb=assess, anomalous data (declining industry), open-ended, principles=ISA 315

*Expected behavior*:
- Diagnosis: identify risk factors → assess likelihood → materiality threshold (Computation sub-runtime)
- Evaluation: evaluate control environment → evaluate management integrity
- Construction: generate audit procedures → match to identified risks
- Traces from all four runtimes are recorded and correlated

### 3.8.5 Case 5: Transfer

*Scenario*: Learner improves at stakeholder analysis in ethics.
- Ethics stakeholder analysis uses Evaluative runtime with Constructed protocol.
- Later, learner faces strategy question: "Assess the impact of a new regulation on key stakeholders."
- Router selects Evaluative runtime (same as ethics).
- Protocol Constructor uses same template: RECALL stakeholder groups → EVALUATE impact on each → JUSTIFY assessment.
- If learner's improved ethics performance transfers to strategy, the shared runtime and protocol template explain why.

*Prediction*: Transfer should be stronger when the *runtime* is shared than when only *content* overlaps. This is falsifiable: compare transfer between ethics→strategy (shared runtime, different content) with ethics→tax (different runtime, different content).

---

## 3.9 Failure Modes

### 3.9.1 Ambiguous routing

*Problem*: "Discuss the impact of adopting IFRS 16 on a company's financial statements."

This problem could be classified as Explanation ("impact of") or Interpretation ("adopt IFRS 16 — text-heavy with principles") or Evaluation ("discuss" — open-ended judgement).

*Degradation*: Multiple runtimes are activated. The system presents the question as multi-runtime and observes which runtime the learner's answer primarily uses. The routing decision is refined post-hoc.

### 3.9.2 Misrecognition

*Problem*: Router sends an ethical dilemma to the Computational runtime because surface features suggest formula application.

*Degradation*: The Computational runtime produces an answer (e.g., calculates a number). The answer is clearly wrong for the problem. Diagnosis flags that the output type doesn't match the expected output type for this problem. The router is recalled with the diagnosis as additional evidence.

### 3.9.3 No matching runtime

*Problem*: A genuinely novel cognitive situation that doesn't fit any category.

*Degradation*: The fallback executes. The LLM-based general reasoner handles the problem. The router records the situation as an "unclassified" example for offline analysis. If the same unclassified pattern appears multiple times, a new runtime category may be warranted.

### 3.9.4 Runtime conflict

*Problem*: Two runtimes produce contradictory intermediate outputs (e.g., Computation says "material", Evaluation says "not material for this stakeholder").

*Degradation*: The contradiction is recorded as a diagnostic signal. The learner's handling of the contradiction reveals their understanding of how different reasoning modes interact. No automatic resolution is attempted.

### 3.9.5 Protocol construction failure

*Problem*: Protocol Constructor lacks principles to complete a constructed protocol.

*Degradation*: Constructor returns `ConstructionFailure(missing=["principle: stakeholder_analysis"])`. The router reports protocol_status=ABSENT. The system teaches the missing component before retesting.

---

## 3.10 Kernel API Implications

The Cognitive Router affects the Kernel API at three points:

### 3.10.1 Request enrichment

Every interaction submitted to the kernel must include router metadata:

```
Interaction {
    problem: String
    routing: RoutingDecision       // from the router
    learner_context: LearnerState  // current cognitive hypotheses
}
```

### 3.10.2 Protocol registry

The kernel maintains a registry of compiled protocols and principle libraries for construction:

```
kernel.protocol_registry = {
    "computation": {
        "npv": Protocol,
        "wacc": Protocol,
        "irr": Protocol,
        ...
    },
    "evaluation": {
        "template": ProtocolTemplate,   // for construction
        "principles": List[Principle],  // ACCA Code, IASB Framework, etc.
        ...
    },
    ...
}
```

### 3.10.3 Diagnostics enrichment

The router's confidence and evidence inform diagnostic signals:

```
DiagnosticSignal {
    type: FailureType                // EXECUTION | PROTOCOL | RECOGNITION
    runtime: RuntimeID
    protocol_status: ProtocolStatus
    router_confidence: Float
    router_evidence: List[String]
    trace: ExecutionTrace
}
```

A Type C (recognition) diagnostic has low router confidence. A Type A (execution) diagnostic has high router confidence and a protocol failure in the trace. A Type B (protocol) diagnostic has high router confidence and protocol_status = ABSENT.

---

## 3.11 Open Questions

### Q1: Is the taxonomy complete and disjoint?

The seven categories must be validated against a representative corpus of exam questions across domains. Predictions:
- ≥90% of Finance questions route to Computation, Classification, or Diagnosis
- ≥90% of Ethics questions route to Evaluation or Classification
- ≥90% of Audit questions route to Diagnosis, Evaluation, or Construction

If coverage falls below 80% for any domain, the taxonomy needs extension.

### Q2: How many primitives are enough?

The CISA instruction set currently has ~14 instructions. Are these sufficient for all seven runtimes, or do some runtimes require specialized instructions? Hypothesis: the core 14 are sufficient — runtimes differ in *protocol structure*, not instruction vocabulary.

### Q3: Can recognition be learned?

The rule-based classifier is a v1. Over time, the router can learn from:
- Routing decisions that led to successful diagnosis
- Routing decisions that required correction
- Learner meta-cognitive responses ("I thought this was a calculation problem but it's actually...")

A learned router may outperform a rule-based one on ambiguous cases.

### Q4: What is the minimum viable Protocol Constructor?

Constructed protocols can range from simple template instantiation to full LLM-based synthesis. The v1 should be template-based: each runtime defines a protocol template with placeholder slots for principles, and the Constructor fills slots from the knowledge graph. LLM-based construction is a v2 capability, reserved for cases where template matching fails.

### Q5: Does the router improve with each interaction?

The router records its decisions and the outcomes (was the diagnosis correct? did the learner's behavior match the predicted runtime?). Over time, this data should refine routing accuracy. If routing accuracy does not improve with data, the taxonomy is wrong.
