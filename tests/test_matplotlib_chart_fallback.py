from __future__ import annotations

import types

from studyplan_app import StudyPlanGUI


def test_build_matplotlib_chart_widget_prefers_gtk_canvas(monkeypatch):
    import studyplan_app as appmod

    class _FakeCanvas:
        def __init__(self, fig):
            self.fig = fig
            self.tooltip = None
            self.size = None

        def set_tooltip_text(self, text):
            self.tooltip = text

        def set_size_request(self, width, height):
            self.size = (width, height)

    monkeypatch.setattr(appmod, "FigureCanvas", _FakeCanvas)

    fig = object()
    widget = StudyPlanGUI._build_matplotlib_chart_widget(
        types.SimpleNamespace(),
        fig,
        width=320,
        height=200,
        tooltip="chart",
    )

    assert isinstance(widget, _FakeCanvas)
    assert widget.fig is fig
    assert widget.tooltip == "chart"
    assert widget.size == (320, 200)


def test_build_matplotlib_chart_widget_raises_without_gtk_canvas(monkeypatch):
    import studyplan_app as appmod

    monkeypatch.setattr(appmod, "FigureCanvas", None)
    monkeypatch.setattr(appmod, "_MATPLOTLIB_BACKEND_ERROR", "")

    try:
        StudyPlanGUI._build_matplotlib_chart_widget(
            types.SimpleNamespace(),
            object(),
            width=430,
            height=240,
            tooltip="chart",
        )
    except RuntimeError as exc:
        assert "Charts disabled for GTK stability" in str(exc)
    else:
        raise AssertionError("expected chart widget builder to fail without GTK canvas")
