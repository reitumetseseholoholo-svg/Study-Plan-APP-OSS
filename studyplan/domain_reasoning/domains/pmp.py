"""PMP (Project Management Professional) domain — PoC formulas.

Formulas registered here use the ``declare_formula()`` DSL with an
explicit ``registry`` parameter to avoid mixing with the default ACCA FM
registry.

Registered formulas:
  - ``pmp.cpi`` — Cost Performance Index (CPI = EV / AC)
  - ``pmp.spi`` — Schedule Performance Index (SPI = EV / PV)
  - ``pmp.eac`` — Estimate at Completion (EAC = BAC / CPI)
"""

from __future__ import annotations

from studyplan.domain_reasoning.domain_registry import DomainRegistry, register_domain
from studyplan.domain_reasoning.formula_registry import FormulaDecl, declare_formula

# ---------------------------------------------------------------------------
# PMP-specific formula registry (separate from the default ACCA FM _registry)
# ---------------------------------------------------------------------------

_pmp_registry: dict[str, FormulaDecl] = {}

declare_formula(
    "pmp.cpi",
    expression="ev / ac",
    patterns=[
        r"\bcost\s*performance\s*index\b",
        r"\bCPI\b",
        r"\bEV\s*/\s*AC\b",
    ],
    param_names=["ev", "ac"],
    param_kinds=["value", "value"],
    label="Cost Performance Index (CPI = EV / AC)",
    output_slot="cpi",
    diagnostic_tags=["ev_error", "ac_error"],
    centrality=0.8,
    chapter_refs=["cost_management"],
    structure_types=["earned_value_analysis"],
    registry=_pmp_registry,
)

declare_formula(
    "pmp.spi",
    expression="ev / pv",
    patterns=[
        r"\bschedule\s*performance\s*index\b",
        r"\bSPI\b",
        r"\bEV\s*/\s*PV\b",
    ],
    param_names=["ev", "pv"],
    param_kinds=["value", "value"],
    label="Schedule Performance Index (SPI = EV / PV)",
    output_slot="spi",
    diagnostic_tags=["ev_error", "pv_error"],
    centrality=0.8,
    chapter_refs=["schedule_management"],
    structure_types=["earned_value_analysis"],
    registry=_pmp_registry,
)

declare_formula(
    "pmp.eac",
    expression="bac / cpi",
    patterns=[
        r"\bestimate\s*at\s*completion\b",
        r"\bEAC\b",
        r"\bBAC\s*/\s*CPI\b",
    ],
    param_names=["bac", "cpi"],
    param_kinds=["value", "value"],
    label="Estimate at Completion (EAC = BAC / CPI)",
    output_slot="eac",
    diagnostic_tags=["bac_error", "cpi_error"],
    dependencies=("pmp.cpi",),
    centrality=0.7,
    chapter_refs=["cost_management"],
    structure_types=["earned_value_analysis"],
    registry=_pmp_registry,
)


# ---------------------------------------------------------------------------
# Build PMP DomainRegistry from the formula registry
# ---------------------------------------------------------------------------


def _build_pmp_registry() -> DomainRegistry:
    reg = DomainRegistry(prefix="pmp")

    for cid, decl in _pmp_registry.items():
        # Concept metadata
        from studyplan.domain_reasoning.concepts import ConceptMetadata

        meta = ConceptMetadata(
            concept_id=cid,
            label=decl.label,
            template_ref=cid,
            dependencies=decl.dependencies,
            output_slots=(decl.output_slot,),
            diagnostic_tags=decl.diagnostic_tags,
            centrality=decl.centrality,
            chapter_refs=decl.chapter_refs,
        )
        reg.add_concept(meta)

        # Template
        if decl.template is not None:
            reg.add_template(cid, decl.template)

        # Formula mapping
        fname = cid.split(".", 1)[1]
        reg.add_formula_mapping(fname, cid)

    # Structure types
    for cid, decl in _pmp_registry.items():
        for st in decl.structure_types:
            reg.structure_types.setdefault(st, []).append(cid)

    # Formula detection patterns
    for cid, decl in _pmp_registry.items():
        fname = cid.split(".", 1)[1]
        if decl.compiled_patterns:
            reg.formula_patterns.append((fname, decl.compiled_patterns))

    # Label aliases for step matcher normalisation
    reg.label_aliases.update(
        {
            "cost performance index": "cpi",
            "cost performance": "cpi",
            "schedule performance index": "spi",
            "schedule performance": "spi",
            "estimate at completion": "eac",
            "earned value": "ev",
            "actual cost": "ac",
            "planned value": "pv",
            "budget at completion": "bac",
        }
    )

    reg.rebuild_slot_groups()
    return reg


# Register the PMP domain at import time
register_domain(_build_pmp_registry())
