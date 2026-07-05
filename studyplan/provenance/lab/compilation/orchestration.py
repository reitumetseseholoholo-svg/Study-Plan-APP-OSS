"""CIRBuilder — global CIR compilation orchestrator.

The CIRBuilder manages the full multi-frontend compilation pipeline::

    register_frontend("fm_formula", FMPlugin())
    register_frontend("pdf", PDFPlugin())

    sources = {
        "fm_formula": fm_knowledge_base,
        "pdf": pdf_document,
    }

    ir = builder.build(sources)
    # ir is a canonical, validated, pass-optimized CognitiveIR

Follows the LLVM toolchain analogy:
    FrontendPlugin = clang (compiler frontend)
    CIRFragment    = .o   (object file)
    CIRMerger      = ld   (linker)
    Pass pipeline  = opt  (optimizer)
"""

from __future__ import annotations

from typing import Any

from studyplan.provenance.cir import CognitiveIR
from studyplan.provenance.lab.compilation.plugin import FrontendPlugin
from studyplan.provenance.lab.compilation.merger import CIRMerger, MergeReport
from studyplan.provenance.lab.compilation.resolver import LookalikeStrategy


class CIRBuilder:
    """Orchestrates the multi-frontend CIR compilation pipeline.

    Usage::

        builder = CIRBuilder()
        builder.register_frontend("fm_formula", FMPlugin())
        ir = builder.build({"fm_formula": fm_kb})
    """

    def __init__(self, strategy: LookalikeStrategy | None = None):
        self._frontends: dict[str, FrontendPlugin] = {}
        self.merger = CIRMerger(strategy)

    def register_frontend(
        self,
        source_kind: str,
        plugin: FrontendPlugin,
    ) -> None:
        """Register a frontend plugin for a source kind.

        Raises ValueError if source_kind already registered.
        """
        if source_kind in self._frontends:
            raise ValueError(
                f"Frontend already registered for source kind '{source_kind}': {self._frontends[source_kind]}"
            )
        if plugin.source_kind != source_kind:
            raise ValueError(
                f"Plugin source_kind '{plugin.source_kind}' does not match registration key '{source_kind}'"
            )
        self._frontends[source_kind] = plugin

    def unregister_frontend(self, source_kind: str) -> None:
        """Remove a registered frontend."""
        self._frontends.pop(source_kind, None)

    @property
    def registered_kinds(self) -> list[str]:
        return list(self._frontends.keys())

    def has_frontend(self, source_kind: str) -> bool:
        return source_kind in self._frontends

    def build(
        self,
        sources: dict[str, Any],
        source_ids: dict[str, str] | None = None,
    ) -> CognitiveIR:
        """Build canonical CIR from multiple source inputs.

        Args:
            sources: {source_kind: source_data}
            source_ids: optional {source_kind: source_id} for provenance.

        Returns:
            Canonical, validated, pass-optimized CognitiveIR.

        Raises:
            ValueError: if a source kind has no registered frontend.
        """
        unknown = [k for k in sources if k not in self._frontends]
        if unknown:
            registered = list(self._frontends.keys())
            raise ValueError(f"No frontend registered for source kind(s): {unknown}. Registered: {registered}")

        source_ids = source_ids or {}

        fragments = []
        for kind, data in sources.items():
            plugin = self._frontends[kind]
            sid = source_ids.get(kind, f"{kind}:default")
            fragment = plugin.compile_to_cir(data, source_id=sid)
            fragments.append(fragment)

        if not fragments:
            return CognitiveIR(
                metadata={"merged": True, "fragment_count": 0},
            )

        ir = self.merger.merge(fragments)
        return ir

    def build_all(
        self,
        source_list: list[tuple[str, Any, str]],
    ) -> CognitiveIR:
        """Build from a list of (source_kind, data, source_id) tuples.

        Convenience method that wraps ``build()`` with dict construction.
        """
        sources = {}
        source_ids = {}
        for kind, data, sid in source_list:
            sources[kind] = data
            source_ids[kind] = sid
        return self.build(sources, source_ids)

    @property
    def last_report(self) -> MergeReport | None:
        return self.merger.last_report
