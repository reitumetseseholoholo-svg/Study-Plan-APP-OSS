"""GTK4 UI components for ACCA Study Plan App."""

from __future__ import annotations

__all__ = [
    "StudyPlanMainWindow",
    "PracticeSessionWindow",
    "CognitiveDashboard",
    "HintSystemWidget",
    "ConfidenceCalibratorWidget",
    "TransferAnalyzerWidget",
    "run_application",
]

_GTK_IMPORT_ERROR: Exception | None = None

try:
    from .main_window import StudyPlanMainWindow, run_application
    from .practice_session import PracticeSessionWindow
    from .cognitive_dashboard import CognitiveDashboard
    from .hint_system import HintSystemWidget
    from .confidence_calibrator import ConfidenceCalibratorWidget
    from .transfer_analyzer import TransferAnalyzerWidget
except Exception as exc:  # pragma: no cover - import-time GTK availability varies by environment.
    _GTK_IMPORT_ERROR = exc


def __getattr__(name: str):
    if name in __all__ and _GTK_IMPORT_ERROR is not None:
        raise ImportError("GTK4 UI components are unavailable in this environment.") from _GTK_IMPORT_ERROR
    raise AttributeError(name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
