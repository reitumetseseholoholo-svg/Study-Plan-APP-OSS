"""Knowledge Compiler — FMKnowledgeBase → ViewState bridge.

Trivial now: FMFormula has structured params/expression/assumptions.
Just format into TopicSpec and compile via DomainCompiler.
"""

from studyplan.provenance.compiler import DomainCompiler, TopicSpec, ComputationStep
from studyplan.provenance.knowledge_ir import FMKnowledgeBase, FMFormula


def formula_to_topic_spec(formula: FMFormula) -> TopicSpec:
    """Compile one FMFormula into a TopicSpec.

    Parameters are the formula's params (each becomes a config_value Artifact).
    Computations encode the transformation with rule_spec and assumptions.
    Output is the formula's output concept.
    """
    parameters: list[dict] = []
    for p in formula.params:
        param_id = f"param_{p.name}"
        parameters.append(
            {
                "id": param_id,
                "type": "config_value",
                "target": p.role.replace("_", " ").title(),
                "metadata": {"semantic_role": p.role or p.name},
            }
        )

    consumes = tuple(f"param_{p.name}" for p in formula.params)

    computations = [
        ComputationStep(
            id=f"compute_{formula.concept_id.split('.')[-1]}",
            input_artifact_id=f"param_{formula.params[0].name}" if formula.params else "",
            output_artifact_id=formula.concept_id.split(".")[-1],
            rule_spec=formula.expression,
            transformation_type="generative_mapping",
            consumes=consumes,
            assumptions=tuple(a.condition for a in formula.assumes),
        )
    ]

    outputs = [
        {
            "id": formula.concept_id.split(".")[-1],
            "type": "call_graph_region",
            "target": formula.label,
            "metadata": {"semantic_role": formula.label.replace(" ", "")},
        }
    ]

    return TopicSpec(
        id=formula.concept_id,
        title=formula.label,
        parameters=tuple(parameters),
        computations=tuple(computations),
        outputs=tuple(outputs),
    )


def compile_formula(
    kb: FMKnowledgeBase,
    concept_id: str,
    compiler: DomainCompiler | None = None,
):
    """Compile one formula → ViewState. Returns (TopicSpec, ViewState) or None."""
    formula = kb.formula_for(concept_id)
    if formula is None:
        return None
    spec = formula_to_topic_spec(formula)
    c = compiler or DomainCompiler()
    vs = c.compile(spec)
    return spec, vs


def compile_all(kb: FMKnowledgeBase):
    """Compile all formulas in a KB into (TopicSpec, ViewState) pairs."""
    compiler = DomainCompiler()
    results: list[tuple[str, TopicSpec]] = []
    for cid in kb.formulas:
        spec = formula_to_topic_spec(kb.formulas[cid])
        results.append((cid, spec))
    return results
