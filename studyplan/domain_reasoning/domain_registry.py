"""Domain registry — per-exam concept maps, template registries, and label normalizers.

Allows the reasoning engine and evaluation pipeline to work with any
professional exam (ACCA, CFA, PMP, CPA, BAR, etc.) by routing through
a DomainRegistry instead of relying on hardcoded ``fm.``-prefixed globals.

Usage::

    from studyplan.domain_reasoning.domain_registry import get_registry

    acca = get_registry("fm")        # built-in ACCA FM registry
    pmp  = DomainRegistry("pmp")     # new PMP registry
    pmp.add_concepts(...)
    pmp.add_templates(...)
    register_domain(pmp)

    # Later, in the reasoning engine:
    trace = reason_question("...", domain="pmp")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from studyplan.domain_reasoning.concepts import ConceptMetadata

if TYPE_CHECKING:
    from studyplan.domain_reasoning.templates import ConceptTemplate


# ---------------------------------------------------------------------------
# Global registry hub
# ---------------------------------------------------------------------------

_REGISTRIES: dict[str, DomainRegistry] = {}


def register_domain(registry: DomainRegistry) -> None:
    """Register a domain so it can be looked up by prefix."""
    _REGISTRIES[registry.prefix] = registry


def get_registry(prefix: str) -> DomainRegistry:
    """Look up a registered domain registry by prefix."""
    reg = _REGISTRIES.get(prefix)
    if reg is not None:
        return reg
    raise KeyError(f"No domain registry registered for prefix {prefix!r}. Available: {list(_REGISTRIES)}")


def list_domains() -> list[str]:
    """Return all registered domain prefixes."""
    return list(_REGISTRIES)


# ---------------------------------------------------------------------------
# DomainRegistry
# ---------------------------------------------------------------------------


@dataclass
class DomainRegistry:
    """Holds all exam-specific data for one professional exam domain.

    Each domain has its own:
    - ``prefix`` (e.g. ``"fm"``, ``"pmp"``, ``"cfa"``)
    - ``concepts`` — mapping of ``concept_id`` → ``ConceptMetadata``
    - ``templates`` — mapping of ``concept_id`` → ``ConceptTemplate``
    - ``formula_to_concept`` — mapping of formula name → concept ID
    - ``structure_types`` — mapping of group name → list of concept IDs
    - ``label_aliases`` — mapping of variant term → canonical term
      (used by the step matcher to normalise learner workings)
    - ``formula_patterns`` — list of ``(formula_name, pattern_list)`` for
      direct question-text detection (used when the numerical solver's
      built-in ``_FORMULA_SIGNATURES`` doesn't cover this domain).
    """

    prefix: str
    concepts: dict[str, ConceptMetadata] = field(default_factory=dict)
    templates: dict[str, ConceptTemplate] = field(default_factory=dict)
    formula_to_concept: dict[str, str] = field(default_factory=dict)
    structure_types: dict[str, list[str]] = field(default_factory=dict)
    label_aliases: dict[str, str] = field(default_factory=dict)
    formula_patterns: list[tuple[str, list[Any]]] = field(default_factory=list, repr=False)
    _slot_groups: dict[str, list[str]] = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------------
    # Slot groups (built lazily)
    # ------------------------------------------------------------------

    def rebuild_slot_groups(self) -> None:
        groups: dict[str, list[str]] = {}
        for cid, meta in self.concepts.items():
            for slot in meta.output_slots:
                groups.setdefault(slot, []).append(cid)
        self._slot_groups = groups

    def find_alternatives(self, concept_id: str) -> list[str]:
        """Concepts producing the same output slots, excluding *concept_id*."""
        meta = self.concepts.get(concept_id)
        if not meta:
            return []
        if not self._slot_groups:
            self.rebuild_slot_groups()
        result: list[str] = []
        seen: set[str] = set()
        for slot in meta.output_slots:
            for alt_id in self._slot_groups.get(slot, ()):
                if alt_id != concept_id and alt_id not in seen:
                    seen.add(alt_id)
                    result.append(alt_id)
        return result

    # ------------------------------------------------------------------
    # Builder helpers
    # ------------------------------------------------------------------

    def add_concept(self, meta: ConceptMetadata) -> None:
        self.concepts[meta.concept_id] = meta

    def add_template(self, concept_id: str, template: ConceptTemplate) -> None:
        self.templates[concept_id] = template

    def add_formula_mapping(self, formula_name: str, concept_id: str) -> None:
        self.formula_to_concept[formula_name] = concept_id

    def add_label_alias(self, variant: str, canonical: str) -> None:
        self.label_aliases[variant] = canonical

    # ------------------------------------------------------------------
    # Bulk loader
    # ------------------------------------------------------------------

    def detect_formulas(self, question: str) -> list[str]:
        """Detect formula names from *question* using the domain's patterns."""
        import re as _re

        found: list[tuple[int, str]] = []
        for fname, patterns in self.formula_patterns:
            for p in patterns:
                if p.search(question) if hasattr(p, "search") else _re.search(p, question, _re.IGNORECASE):
                    found.append((0, fname))
                    break
        return [name for _, name in found]

    def load_from_module(
        self,
        concepts: dict[str, ConceptMetadata] | None = None,
        templates: dict["str", "ConceptTemplate"] | None = None,
        formula_map: dict[str, str] | None = None,
        structure_types: dict[str, list[str]] | None = None,
        label_aliases: dict[str, str] | None = None,
    ) -> None:
        """Load pre-built dictionaries into this registry."""
        if concepts:
            self.concepts.update(concepts)
        if templates:
            self.templates.update(templates)
        if formula_map:
            self.formula_to_concept.update(formula_map)
        if structure_types:
            self.structure_types.update(structure_types)
        if label_aliases:
            self.label_aliases.update(label_aliases)
        self.rebuild_slot_groups()
