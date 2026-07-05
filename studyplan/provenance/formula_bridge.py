"""Formula Bridge — Auto-compile provenance DomainSpecs from the DSL formula registry.

Essentialist Question:
    What phenomenon does this bridge exist to preserve?
Answer:
    Formula-registry coherence — the property that every formula declared
    in the domain reasoning DSL automatically gets a provenance-compilable
    representation without separate hand-authoring.

Hypothesis H-FB-01:
    The FormulaDecl registry (formula_registry.py) contains sufficient
    structural information to generate provenance DomainSpecs for the
    FastDomainCompiler. No additional metadata is required.

Predictions:
    P1: Every declared formula maps to a valid DomainSpec (passes compilation).
    P2: Formula chains produce multi-step DomainSpecs with correct linear topology.
    P3: Dependency edges between formulas produce edges between DomainSpecs.
    P4: The auto-compiled ViewState supports collect_inherited_constraints queries.
    P5: Zero hand-authored specs needed for FM domain after bridge is active.

Falsification conditions:
    F1: A FormulaDecl with empty param_names, dependencies, output_slot, and
        expression that cannot produce a valid DomainSpec.
    F2: Two formulas that share param_names produce conflicting DomainNodes.
    F3: A FormulaDecl that compiles to a ViewState that fails iR1 connectivity.
"""

from typing import Any

from studyplan.provenance.fast_compiler import (
    DomainSpec,
    DomainNode,
    DomainEdge,
    TypeRegistry,
)
from studyplan.domain_reasoning.formula_registry import (
    get_registry,
    FormulaDecl,
    CONCEPT_TYPE_EXPRESSION,
    CONCEPT_TYPE_RULE_CHAIN,
    CONCEPT_TYPE_LOOKUP,
    CONCEPT_TYPE_CLASSIFICATION,
)

FM_DOMAIN = "fm"


def formula_to_domainspec(concept_id: str, decl: FormulaDecl) -> DomainSpec:
    """Convert a single FormulaDecl to a provenance DomainSpec.

    Maps:
    - formula parameters -> DomainNode(kind="parameter")
    - dependencies -> DomainNode(kind="intermediate")
    - output -> DomainNode(kind="output")
    - expression -> DomainEdge with formula expression as rule
    """
    nodes: list[DomainNode] = []
    edges: list[DomainEdge] = []

    for pname in decl.param_names:
        nodes.append(
            DomainNode(
                id=pname,
                concept=_infer_concept_from_param(pname),
                kind="parameter",
                target=pname,
                metadata={"role": "parameter", "formula": concept_id},
            )
        )

    for dep_id in decl.dependencies:
        dep_node_id = _dependency_node_id(dep_id)
        nodes.append(
            DomainNode(
                id=dep_node_id,
                concept=_extract_concept_name(dep_id),
                kind="intermediate",
                target=dep_id,
                metadata={"role": "dependency", "source_formula": dep_id},
            )
        )

    output_id = decl.output_slot or _default_output_id(concept_id)
    nodes.append(
        DomainNode(
            id=output_id,
            concept=_extract_concept_name(concept_id),
            kind="output",
            target=decl.label or concept_id,
            metadata={
                "role": "output",
                "formula": concept_id,
                "concept_type": decl.concept_type,
            },
        )
    )

    inputs = list(decl.param_names)
    inputs.extend(_dependency_node_id(d) for d in decl.dependencies)

    if not inputs:
        primary = output_id
        consumes: tuple[str, ...] = ()
    else:
        primary = inputs[0]
        consumes = tuple(inputs[1:])

    rule = decl.expression or f"compute {_short_name(concept_id)}"

    edges.append(
        DomainEdge(
            id=f"{_short_name(concept_id)}_compute",
            from_id=primary,
            to_id=output_id,
            rule=rule,
            semantics="generative_mapping",
            assumptions=decl.diagnostic_tags,
            consumes=consumes,
        )
    )

    return DomainSpec(
        id=concept_id,
        title=decl.label or concept_id,
        domain=FM_DOMAIN,
        nodes=tuple(nodes),
        edges=tuple(edges),
        metadata={
            "concept_type": decl.concept_type,
            "source": "formula_bridge",
        },
    )


def formula_chain_to_domainspec(
    concept_id: str,
    decl: FormulaDecl,
    chain_steps: list[Any],
) -> DomainSpec:
    """Convert a formula chain to a multi-step DomainSpec.

    Each chain step becomes one transformation edge. Step outputs are
    intermediate nodes feeding into subsequent steps. The final step's
    output is the overall formula output.
    """
    nodes: list[DomainNode] = []
    edges: list[DomainEdge] = []

    all_params: list[str] = []
    for step in chain_steps:
        for p in step.param_names:
            if p not in all_params:
                all_params.append(p)

    for pname in all_params:
        nodes.append(
            DomainNode(
                id=pname,
                concept=_infer_concept_from_param(pname),
                kind="parameter",
                target=pname,
                metadata={"role": "parameter", "formula": concept_id},
            )
        )

    for dep_id in decl.dependencies:
        dep_node_id = _dependency_node_id(dep_id)
        nodes.append(
            DomainNode(
                id=dep_node_id,
                concept=_extract_concept_name(dep_id),
                kind="intermediate",
                target=dep_id,
                metadata={"role": "dependency", "source_formula": dep_id},
            )
        )

    step_output_ids: list[str] = []
    for i, step in enumerate(chain_steps):
        slot = step.slot
        step_output_ids.append(slot)

        step_params = list(step.param_names)
        step_dep_ids = [_dependency_node_id(d) for d in decl.dependencies]

        all_input_ids = list(step_params)
        all_input_ids.extend(n for n in step_dep_ids if n not in all_input_ids)

        if i > 0:
            prev_slot = chain_steps[i - 1].slot
            if prev_slot in all_input_ids:
                all_input_ids.remove(prev_slot)

        if not all_input_ids:
            primary = slot
            consumes: tuple[str, ...] = ()
        else:
            primary = all_input_ids[0]
            consumes = tuple(all_input_ids[1:])

        kind = "output" if i == len(chain_steps) - 1 else "intermediate"
        nodes.append(
            DomainNode(
                id=slot,
                concept=_infer_concept_from_param(slot),
                kind=kind,
                target=slot,
                metadata={
                    "role": "step_output",
                    "step_index": i,
                    "formula": concept_id,
                },
            )
        )

        edges.append(
            DomainEdge(
                id=f"{_short_name(concept_id)}_step_{i}",
                from_id=primary,
                to_id=slot,
                rule=step.expression,
                semantics="generative_mapping",
                assumptions=(),
                consumes=consumes,
            )
        )

    return DomainSpec(
        id=concept_id,
        title=decl.label or concept_id,
        domain=FM_DOMAIN,
        nodes=tuple(nodes),
        edges=tuple(edges),
        metadata={
            "concept_type": "formula_chain",
            "source": "formula_bridge",
            "step_count": len(chain_steps),
        },
    )


def registry_to_domainspecs() -> dict[str, DomainSpec]:
    """Convert entire formula registry to DomainSpecs.

    Returns dict mapping concept_id -> DomainSpec for every formula
    that can be compiled by FastDomainCompiler.
    """
    registry = get_registry()
    specs: dict[str, DomainSpec] = {}

    for concept_id, decl in registry.items():
        try:
            chain_steps = _try_extract_chain_steps(decl)
            if chain_steps is not None:
                specs[concept_id] = formula_chain_to_domainspec(
                    concept_id,
                    decl,
                    chain_steps,
                )
            else:
                specs[concept_id] = formula_to_domainspec(concept_id, decl)
        except Exception:
            pass

    return specs


def auto_register_fm_domain(
    registry: TypeRegistry | None = None,
) -> TypeRegistry:
    """Auto-register all FM formula concepts into a TypeRegistry.

    Reads the formula registry and registers every concept_id as
    a type mapping in the FM domain.
    """
    tr = registry or TypeRegistry()
    formulas = get_registry()

    fm_mapping: dict[str, str] = {}
    for concept_id, decl in formulas.items():
        concept_name = _extract_concept_name(concept_id)
        fm_mapping[concept_name] = _infer_artifact_type(decl)
        if decl.formula_name and decl.formula_name not in fm_mapping:
            fm_mapping[decl.formula_name] = _infer_artifact_type(decl)

    if fm_mapping:
        existing = dict(tr._mappings.get("fm", {})) if "fm" in tr._mappings else {}
        existing.update(fm_mapping)
        tr.register_domain("fm", existing, "generative_mapping")

    return tr


def _resolve_in_all_topics(topic: str, tl: str) -> str:
    """Check ALL_TOPICS for a matching key. Returns match or empty string."""
    from studyplan.provenance.compiler_spec import ALL_TOPICS

    if topic in ALL_TOPICS:
        return topic
    for k in ALL_TOPICS:
        if k.lower() == tl:
            return k
    if "(" in topic and ")" in topic:
        paren = topic[topic.index("(") + 1 : topic.index(")")].strip()
        if paren in ALL_TOPICS:
            return paren
    for k in ALL_TOPICS:
        if k.lower() in tl or tl in k.lower():
            return k
    return ""


def _resolve_in_formula_registry(topic: str, tl: str) -> str:
    """Check the formula registry for a matching key. Returns match or empty string."""
    from studyplan.domain_reasoning.formula_registry import get_registry

    registry = get_registry()
    if topic in registry:
        return topic
    for cid in registry:
        cn = _extract_concept_name(cid)
        if cn.lower() == tl or (cn.lower() in tl or tl in cn.lower()):
            return cid
    tl_nodot = topic.replace("fm.", "", 1) if topic.startswith("fm.") else topic
    for cid in registry:
        cn = _extract_concept_name(cid)
        if cn == tl_nodot:
            return cid
    return ""


def resolve_topic_key(topic: str) -> str:
    """Resolve a topic name to a provenance key, checking ALL_TOPICS then formula registry.

    Returns:
        The matching key (ALL_TOPICS key or concept_id), or empty string.
    """
    if not topic:
        return ""

    tl = topic.lower()
    match = _resolve_in_all_topics(topic, tl)
    if match:
        return match
    return _resolve_in_formula_registry(topic, tl)


def get_topic_viewstate(
    topic_key: str,
) -> tuple[Any, str] | None:
    """Resolve a topic key to (ViewState, target_artifact_id).

    Checks ALL_TOPICS first (5 hand-authored), then formula registry.
    Returns None if neither source can produce a ViewState.

    Usage:
        result = get_topic_viewstate("CAPM")
        if result:
            vs, target_id = result
            ctx = ExecutionContext(vs)
            data = ctx.inherited_assumptions_fast(target_id)
    """
    from studyplan.provenance.compiler import DomainCompiler
    from studyplan.provenance.compiler_spec import ALL_TOPICS
    from studyplan.provenance.fast_compiler import FastDomainCompiler

    if topic_key in ALL_TOPICS:
        spec = ALL_TOPICS[topic_key]
        target_id = spec.outputs[-1]["id"] if spec.outputs else spec.id
        vs = DomainCompiler.compile_one(spec)
        return vs, target_id

    from studyplan.domain_reasoning.formula_registry import get_registry

    registry = get_registry()
    decl = registry.get(topic_key)
    if decl is None:
        return None

    chain_steps = _try_extract_chain_steps(decl)
    if chain_steps is not None:
        spec = formula_chain_to_domainspec(topic_key, decl, chain_steps)
    else:
        spec = formula_to_domainspec(topic_key, decl)

    reg = auto_register_fm_domain()
    compiler = FastDomainCompiler(reg)
    vs, record = compiler.compile(spec)
    if not record.validation.get("pass", False):
        return None

    target_id = decl.output_slot or _default_output_id(topic_key)
    return vs, target_id


def compile_all_registry() -> dict[str, Any]:
    """Compile every formula in the registry into ViewStates.

    Returns dict mapping concept_id -> {spec, viewstate, record, errors}.
    Never raises — failures are recorded as error entries.
    """
    from studyplan.provenance.fast_compiler import FastDomainCompiler

    registry = auto_register_fm_domain()
    compiler = FastDomainCompiler(registry)
    specs = registry_to_domainspecs()
    results: dict[str, Any] = {}

    for concept_id, spec in specs.items():
        entry: dict[str, Any] = {"spec": spec}
        try:
            vs, record = compiler.compile(spec)
            entry["viewstate"] = vs
            entry["record"] = record
            entry["pass"] = record.validation.get("pass", False)
        except Exception as e:
            entry["error"] = str(e)
            entry["pass"] = False
        results[concept_id] = entry

    return results


# ---- Helpers ----


def _extract_concept_name(concept_id: str) -> str:
    return concept_id.split(".", 1)[-1] if "." in concept_id else concept_id


def _dependency_node_id(dep_id: str) -> str:
    name = _extract_concept_name(dep_id)
    return f"{name}_result"


def _default_output_id(concept_id: str) -> str:
    return _extract_concept_name(concept_id)


def _short_name(concept_id: str) -> str:
    return _extract_concept_name(concept_id)


def _try_extract_chain_steps(decl: FormulaDecl) -> list[Any] | None:
    """Extract chain steps from a FormulaDecl if it's a formula chain."""
    if decl.concept_type != CONCEPT_TYPE_EXPRESSION:
        return None
    template = getattr(decl, "template", None)
    if template is None:
        return None
    template_type = type(template).__name__
    if template_type != "ChainTemplate":
        return None
    steps = getattr(template, "_steps", None) or getattr(template, "steps", None)
    if steps:
        return list(steps)
    return None


_CONCEPT_FROM_PARAM: dict[str, str] = {
    "risk_free": "discount_rate",
    "beta": "beta",
    "market_return": "market_return",
    "market_return_avg": "market_return",
    "cost_debt": "cost_of_debt",
    "tax": "tax_rate",
    "equity_weight": "capital_structure",
    "debt_weight": "capital_structure",
    "growth_rate": "growth_rate",
    "dividend": "dividend",
    "share_price": "share_price",
    "d0": "dividend",
    "d1": "dividend",
    "p0": "share_price",
    "g": "growth_rate",
    "initial_investment": "initial_investment",
    "i_0": "initial_investment",
    "r": "discount_rate",
    "cf_1": "cash_flow",
    "cf_2": "cash_flow",
    "cf_3": "cash_flow",
    "mrkt_val_debt": "capital_structure",
    "mrkt_val_eq": "capital_structure",
}


def _infer_concept_from_param(param_name: str) -> str:
    low = param_name.lower()
    if low in _CONCEPT_FROM_PARAM:
        return _CONCEPT_FROM_PARAM[low]
    if low.startswith("cf_"):
        return "cash_flow"
    if low.startswith("cov_"):
        return "covariance"
    if low.endswith("_rate") or low.endswith("_cost") or low.endswith("_price"):
        return "config_value"
    return "config_value"


def _infer_artifact_type(decl: FormulaDecl) -> str:
    if decl.concept_type == CONCEPT_TYPE_CLASSIFICATION:
        return "control_flow_pattern"
    if decl.concept_type == CONCEPT_TYPE_RULE_CHAIN:
        return "data_flow_edge"
    if decl.concept_type == CONCEPT_TYPE_LOOKUP:
        return "symbol_table_entry"
    concept = _extract_concept_name(decl.concept_id)
    if any(s in concept.lower() for s in ("_rate", "_cost", "_price", "_value", "_amount")):
        return "config_value"
    return "call_graph_region"
