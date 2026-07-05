"""PDFFrontendPlugin — compiles PDF text chunks into CIR fragments.

Third frontend (after FM structured + Notes text). Attaches to the existing
PDF RAG import pipeline: extracted text chunks → heuristic parsing → CIR.

This is the first frontend that must handle noisy, implicit knowledge.
Unlike FM formulas (formal structure) or Notes text (explicit type markers),
PDF text requires heuristic extraction:
  - Formula detection via math expression patterns
  - Concept detection via capitalization and domain lexicon
  - Dependency extraction via cue phrases ("depends on", "requires")
  - Definition detection via "X is..." patterns
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from studyplan.provenance.kernel.performance import timed
from studyplan.provenance.cir import Identity, Artifact, Relation
from studyplan.provenance.lab.compilation.plugin import FrontendPlugin


# ── Heuristic patterns for ACCA FM textbook text ──────────

# Math expression: anything with = and math operators on either side
_FORMULA_PATTERN = re.compile(
    r"[A-Z][A-Za-z_]+(?:\s*\([^)]*\))?\s*=\s*.+?(?=[.]?\s|$)",
)
_MATH_OPS = re.compile(r"[+\-*/^()]")

# Dependency cue phrases
_DEP_CUES = re.compile(
    r"(?:depends?\s+(?:on|upon|entirely\s+on)|"
    r"requires?|"
    r"is\s+(?:calculated|derived|determined|computed)\s+(?:using|from|by)|"
    r"based\s+on|"
    r"uses?\s+(?:the\s+)?(?:concept|formula|method|principle)\s+of|"
    r"as\s+a\s+function\s+of)",
    re.IGNORECASE,
)

# Definition cue phrases
_DEF_CUES = re.compile(
    r"(?:^|\s)([A-Z][A-Za-z_/()]+)\s+(?:is\s+(?:a|an|the|defined\s+as)?\s*|"
    r"refers?\s+to|"
    r"represents?|"
    r"means?|"
    r"can\s+be\s+defined\s+as|"
    r"denotes?)",
    re.IGNORECASE,
)

# Known FM concepts (domain lexicon for ACCA FM)
_FM_CONCEPTS: frozenset[str] = frozenset(
    {
        "WACC",
        "CAPM",
        "NPV",
        "IRR",
        "ARR",
        "ROCE",
        "DCF",
        "APV",
        "EPS",
        "P/E",
        "D/E",
        "ROE",
        "ROI",
        "EBIT",
        "EBITDA",
        "FV",
        "PV",
        "PMT",
        "NPER",
        "RATE",
        "Cost of equity",
        "Cost of debt",
        "Cost of capital",
        "Beta",
        "Equity beta",
        "Asset beta",
        "Debt beta",
        "Risk-free rate",
        "Market return",
        "Market risk premium",
        "Dividend growth model",
        "Gordon growth model",
        "Modigliani-Miller",
        "MPT",
        "MM",
        "Working capital",
        "Operating cycle",
        "Cash conversion cycle",
        "Payback period",
        "Discounted payback",
        "Leasing",
        "Buy vs lease",
        "Sale and leaseback",
        "Portfolio theory",
        "Systematic risk",
        "Unsystematic risk",
        "Capital structure",
        "Gearing",
        "Financial risk",
        "Business risk",
        "Operating gearing",
        "Financial gearing",
        "Share price",
        "Dividend policy",
        "Shareholder wealth",
        "Agency theory",
        "Corporate governance",
        "Stakeholder",
        "EOQ",
        "JIT",
        "Inventory management",
        "Factoring",
        "Invoice discounting",
        "Trade credit",
        "Foreign exchange",
        "Hedging",
        "Forward contract",
        "Money market hedge",
        "Options",
        "Swaps",
        "Futures",
        "Interest rate risk",
        "Currency risk",
        "Translation risk",
        "Economic risk",
        "Transaction risk",
    }
)


# Known FM formula patterns (heuristic: contains = and math ops)
@timed("pdf_extraction", "looks_like_formula")
def _looks_like_formula(text: str) -> bool:
    m = _FORMULA_PATTERN.search(text)
    if not m:
        return False
    # Verify there's at least one math operator
    return bool(_MATH_OPS.search(m.group(0)))


@timed("pdf_extraction", "extract_concepts")
def _extract_concepts(text: str) -> list[str]:
    """Extract likely concept terms from text."""
    found: list[str] = []
    seen: set[str] = set()

    # Known FM concepts mentioned in chunk
    for concept in _FM_CONCEPTS:
        if concept.lower() in text.lower() and concept not in seen:
            found.append(concept)
            seen.add(concept)

    # Capitalized multi-word terms (potential concepts)
    for m in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b", text):
        term = m.group(1).strip()
        if len(term) > 3 and term not in seen:
            found.append(term)
            seen.add(term)

    return found


@timed("pdf_extraction", "extract_formulas")
def _extract_formulas(text: str) -> list[str]:
    """Extract formula expressions from text."""
    found: list[str] = []
    seen: set[str] = set()

    for m in _FORMULA_PATTERN.finditer(text):
        formula = m.group(0).strip()
        key = formula.lower()[:80]
        if key not in seen:
            found.append(formula)
            seen.add(key)

    return found


@timed("pdf_extraction", "extract_dependencies")
def _extract_dependencies(text: str, known_concepts: list[str]) -> list[tuple[str, str]]:
    """Extract (dependent, prerequisite) pairs from dependency cues."""
    deps: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for m in _DEP_CUES.finditer(text):
        # Look backward for the dependent concept (before the cue)
        before = text[: m.start()].strip()
        before_words = before.split()
        # Last capitalized term before cue
        dependent = ""
        for w in reversed(before_words):
            w_clean = w.strip(".,;:()\"'")
            if w_clean in _FM_CONCEPTS or (w_clean[0].isupper() if w_clean else False):
                dependent = w_clean
                break

        # Look forward for the prerequisite (after the cue)
        after = text[m.end() :].strip().split(".")[0].strip()
        after_words = after.split()
        prerequisite = ""
        for w in after_words:
            w_clean = w.strip(".,;:()\"'")
            if w_clean in _FM_CONCEPTS or (w_clean[0].isupper() if w_clean else False):
                prerequisite = w_clean
                break

        if dependent and prerequisite and (dependent, prerequisite) not in seen:
            deps.append((dependent, prerequisite))
            seen.add((dependent, prerequisite))

    return deps


@timed("pdf_extraction", "extract_definitions")
def _extract_definitions(text: str) -> list[tuple[str, str]]:
    """Extract (concept, definition_text) pairs."""
    defs: list[tuple[str, str]] = []
    seen: set[str] = set()

    for m in _DEF_CUES.finditer(text):
        concept = m.group(1).strip()
        # Get the rest of the sentence
        rest = text[m.end() :].strip().split(".")[0].strip()
        if concept and rest and len(rest) > 10:
            key = f"{concept}:{rest[:60]}"
            if key not in seen:
                defs.append((concept, rest))
                seen.add(key)

    return defs


def _looks_like_example(text: str) -> bool:
    """Check if text looks like an example."""
    lower = text.lower()
    return any(
        cue in lower
        for cue in [
            "example",
            "e.g.",
            "for instance",
            "illustration",
            "sample",
            "worked example",
            "demonstration",
        ]
    )


def _normalize_id(label: str) -> str:
    """Normalize a label into a valid CIR identity ID."""
    n = label.strip()
    n = re.sub(r"[^a-zA-Z0-9_]", "_", n)
    n = re.sub(r"_+", "_", n)
    n = n.strip("_")
    return n if n else f"concept_{hash(label) % 10000}"


# ── Plugin ─────────────────────────────────────────────────


@dataclass
class PdfChunk:
    """One parsed PDF chunk with extracted knowledge."""

    index: int
    text: str
    concepts: list[str] = field(default_factory=list)
    formulas: list[str] = field(default_factory=list)
    dependencies: list[tuple[str, str]] = field(default_factory=list)
    definitions: list[tuple[str, str]] = field(default_factory=list)
    has_example: bool = False


@timed("pdf_extraction", "parse_pdf_chunks")
def parse_pdf_chunks(chunks: list[dict[str, Any]]) -> list[PdfChunk]:
    """Parse PDF text chunks into structured knowledge blocks."""
    parsed: list[PdfChunk] = []

    for chunk in chunks:
        text = chunk.get("text", "")
        if not text.strip():
            continue

        concepts = _extract_concepts(text)
        formulas = _extract_formulas(text)
        dependencies = _extract_dependencies(text, concepts)
        definitions = _extract_definitions(text)

        parsed.append(
            PdfChunk(
                index=chunk.get("chunk_index", 0),
                text=text,
                concepts=concepts,
                formulas=formulas,
                dependencies=dependencies,
                definitions=definitions,
                has_example=_looks_like_example(text),
            )
        )

    return parsed


class PDFFrontendPlugin(FrontendPlugin):
    """FrontendPlugin that compiles PDF text chunks into CIR.

    Input: list of {chunk_index, text} dicts from _load_ai_tutor_rag_doc.
    Extracts concepts, formulas, definitions, examples, and dependencies
    using heuristic pattern matching.
    """

    @property
    def source_kind(self) -> str:
        return "pdf"

    @timed("pdf_extraction", "parse")
    def parse(self, source: Any) -> list[PdfChunk]:
        if isinstance(source, list):
            return parse_pdf_chunks(source)
        raise TypeError(f"PDFFrontendPlugin expects list[dict], got {type(source).__name__}")

    @timed("pdf_extraction", "extract_identities")
    def extract_identities(self, parsed: list[PdfChunk]) -> list[Identity]:
        identities: list[Identity] = []
        seen: set[str] = set()

        for chunk in parsed:
            for concept in chunk.concepts:
                cid = _normalize_id(concept)
                if cid not in seen:
                    identities.append(Identity(id=cid, type="concept", label=concept))
                    seen.add(cid)

            for formula_text in chunk.formulas:
                # Extract formula name (LHS of =)
                lhs = formula_text.split("=")[0].strip()
                name = lhs.split("(")[0].strip() if "(" in lhs else lhs
                fid = _normalize_id(name)
                if fid not in seen:
                    identities.append(Identity(id=fid, type="formula", label=name))
                    seen.add(fid)

            for dep in chunk.dependencies:
                for term in dep:
                    tid = _normalize_id(term)
                    if tid not in seen:
                        identities.append(Identity(id=tid, type="concept", label=term))
                        seen.add(tid)

            for defn in chunk.definitions:
                did = _normalize_id(defn[0])
                if did not in seen:
                    identities.append(Identity(id=did, type="concept", label=defn[0]))
                    seen.add(did)

        return identities

    @timed("pdf_extraction", "extract_artifacts")
    def extract_artifacts(self, parsed: list[PdfChunk]) -> list[Artifact]:
        artifacts: list[Artifact] = []
        seen: set[str] = set()

        for chunk in parsed:
            # Definitions → definition artifacts
            for concept, def_text in chunk.definitions:
                cid = _normalize_id(concept)
                aid = f"pdf.{chunk.index}.def.{_normalize_id(concept)}"
                if aid not in seen:
                    artifacts.append(
                        Artifact(
                            id=aid,
                            type="definition",
                            target_identity=cid,
                            source_id=f"chunk:{chunk.index}",
                            content_preview=def_text[:200],
                        )
                    )
                    seen.add(aid)

            # Formulas → explanation artifacts (the expression text)
            for formula_text in chunk.formulas:
                lhs = formula_text.split("=")[0].strip()
                name = lhs.split("(")[0].strip() if "(" in lhs else lhs
                fid = _normalize_id(name)
                aid = f"pdf.{chunk.index}.formula.{fid}"
                if aid not in seen:
                    artifacts.append(
                        Artifact(
                            id=aid,
                            type="explanation",
                            target_identity=fid,
                            source_id=f"chunk:{chunk.index}",
                            content_preview=formula_text[:200],
                        )
                    )
                    seen.add(aid)

            # Concepts mentioned → explanation artifacts with chunk text
            for concept in chunk.concepts:
                cid = _normalize_id(concept)
                aid = f"pdf.{chunk.index}.explain.{cid}"
                if aid not in seen:
                    artifacts.append(
                        Artifact(
                            id=aid,
                            type="explanation",
                            target_identity=cid,
                            source_id=f"chunk:{chunk.index}",
                            content_preview=chunk.text[:200],
                        )
                    )
                    seen.add(aid)

            # Examples → example artifacts
            if chunk.has_example:
                aid = f"pdf.{chunk.index}.example"
                if aid not in seen:
                    # Find the example sentence
                    lines = chunk.text.split("\n")
                    example_lines = [l for l in lines if _looks_like_example(l)]
                    example_text = " ".join(example_lines)[:200] if example_lines else chunk.text[:200]
                    # Attach to first mentioned concept
                    target = _normalize_id(chunk.concepts[0]) if chunk.concepts else "unknown"
                    artifacts.append(
                        Artifact(
                            id=aid,
                            type="example",
                            target_identity=target,
                            source_id=f"chunk:{chunk.index}",
                            content_preview=example_text[:200],
                        )
                    )
                    seen.add(aid)

        return artifacts

    @timed("pdf_extraction", "extract_relations")
    def extract_relations(self, parsed: list[PdfChunk]) -> list[Relation]:
        relations: list[Relation] = []
        seen: set[tuple[str, str, str]] = set()

        for chunk in parsed:
            for dep in chunk.dependencies:
                dependent = _normalize_id(dep[0])
                prerequisite = _normalize_id(dep[1])
                key = ("assumes", dependent, prerequisite)
                if key not in seen:
                    relations.append(
                        Relation(
                            type="assumes",
                            source=dependent,
                            target=prerequisite,
                        )
                    )
                    seen.add(key)

            for formula_text in chunk.formulas:
                lhs = formula_text.split("=")[0].strip()
                name = lhs.split("(")[0].strip() if "(" in lhs else lhs
                fid = _normalize_id(name)

                # Right-hand side concepts are "assumed" by this formula
                rhs = formula_text.split("=", 1)[1].strip() if "=" in formula_text else ""
                for concept in _extract_concepts(rhs):
                    tid = _normalize_id(concept)
                    key = ("assumes", fid, tid)
                    if key not in seen:
                        relations.append(
                            Relation(
                                type="assumes",
                                source=fid,
                                target=tid,
                            )
                        )
                        seen.add(key)

            # Definitions create "defines" relations
            for concept, _ in chunk.definitions:
                cid = _normalize_id(concept)
                aid = f"pdf.{chunk.index}.def.{cid}"
                key = ("defines", aid, cid)
                if key not in seen:
                    relations.append(
                        Relation(
                            type="defines",
                            source=aid,
                            target=cid,
                        )
                    )
                    seen.add(key)

        return relations
