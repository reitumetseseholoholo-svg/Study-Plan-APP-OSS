"""
RAG-amplified module reconfiguration.

Uses syllabus and study guide PDFs (already in RAG) to update module structure
in a lightweight way: learning outcomes, main syllabus sections, aliases,
importance weights. AI models can reconfigure the module from RAG context
with schema-validated output.

See MODULE_RECONFIG_PLAN.md for the full design.
"""

from studyplan.module_reconfig.reconfig import (
    DEFAULT_AUTO_APPLY_CONFIDENCE_THRESHOLD,
    DEFAULT_PENDING_RECONFIG_CONFIDENCE_LOW,
    RECONFIG_CHECKPOINT_VERSION,
    analyze_outcome_count_regressions,
    cap_chunks_by_path,
    chapter_outcome_counts,
    compute_reconfig_confidence,
    compute_target_chapters_for_reconfig,
    load_reconfig_checkpoint,
    reconfig_outcome_totals_and_changed_chapters,
    reconfig_run_fingerprint,
    reconfigure_from_rag,
    retrieve_from_chunks_by_path,
    should_auto_reconfigure,
    validate_capabilities_and_aliases,
    validate_module_config,
    validate_syllabus_structure,
)

__all__ = [
    "DEFAULT_AUTO_APPLY_CONFIDENCE_THRESHOLD",
    "DEFAULT_PENDING_RECONFIG_CONFIDENCE_LOW",
    "RECONFIG_CHECKPOINT_VERSION",
    "analyze_outcome_count_regressions",
    "cap_chunks_by_path",
    "chapter_outcome_counts",
    "compute_reconfig_confidence",
    "compute_target_chapters_for_reconfig",
    "load_reconfig_checkpoint",
    "reconfig_outcome_totals_and_changed_chapters",
    "reconfig_run_fingerprint",
    "reconfigure_from_rag",
    "retrieve_from_chunks_by_path",
    "should_auto_reconfigure",
    "validate_capabilities_and_aliases",
    "validate_module_config",
    "validate_syllabus_structure",
]
