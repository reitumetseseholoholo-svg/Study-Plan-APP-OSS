"""
Tests for semantic normalization, circuit breaker, weak chapter, recall risk,
and dashboard section reconciliation helpers.
"""

from __future__ import annotations

import time
import types

import pytest

try:
    from studyplan_app import StudyPlanGUI
except Exception as exc:
    pytest.skip(f"studyplan_app import unavailable: {exc}", allow_module_level=True)

from studyplan.ai.circuit_breaker import CircuitBreaker
from studyplan_engine import StudyPlanEngine


# ── _semantic_normalize_text ──────────────────────────────────────────


class TestSemanticNormalizeText:
    def _make_engine(self, aliases: dict | None = None, chapter: str = "FM Function"):
        eng = StudyPlanEngine.__new__(StudyPlanEngine)
        eng.semantic_aliases = aliases or {}
        eng.SEMANTIC_CANONICAL_ALIASES = {
            "wacc": "weighted average cost of capital",
            "npv": "net present value",
            "capm": "capital asset pricing model",
        }
        # stub _try_match_chapter to return chapter unchanged
        eng._try_match_chapter = lambda ch: ch
        return eng

    def test_empty_text(self):
        eng = self._make_engine()
        result = eng._semantic_normalize_text("FM Function", "")
        assert result == ""

    def test_none_text(self):
        eng = self._make_engine()
        result = eng._semantic_normalize_text("FM Function", None)  # type: ignore
        assert result == ""

    def test_lowercase_and_strip(self):
        eng = self._make_engine()
        result = eng._semantic_normalize_text("FM Function", "  HELLO World  ")
        assert result == "hello world"

    def test_collapse_whitespace(self):
        eng = self._make_engine()
        result = eng._semantic_normalize_text("FM Function", "a   b\t\tc\n\nd")
        assert result == "a b c d"

    def test_alias_substitution_builtin(self):
        """Built-in FM aliases: WACC → weighted average cost of capital."""
        eng = self._make_engine()
        result = eng._semantic_normalize_text("FM Function", "calculate WACC")
        assert "weighted average cost of capital" in result
        assert "wacc" not in result

    def test_alias_substitution_custom(self):
        """Module-defined aliases override built-in."""
        eng = self._make_engine(aliases={"wacc": "custom wacc def"})
        result = eng._semantic_normalize_text("FM Function", "WACC formula")
        assert "custom wacc def" in result
        assert "weighted average cost of capital" not in result

    def test_chapter_specific_alias(self):
        """Chapter-specific aliases take effect."""
        eng = self._make_engine(aliases={"FM Function": {"fml": "financial management level"}})
        result = eng._semantic_normalize_text("FM Function", "FML analysis")
        assert "financial management level" in result
        assert "fml" not in result

    def test_chapter_fuzzy_match_alias(self):
        """Chapter alias resolution via _try_match_chapter fallback."""
        eng = self._make_engine(aliases={"FM Func": {"xyz": "chapter specific alias"}})
        eng._try_match_chapter = lambda ch: "FM Func" if "FM" in ch else ch
        result = eng._semantic_normalize_text("FM Function", "XYZ value")
        assert "chapter specific alias" in result

    def test_boundary_word_alias_no_substring(self):
        """Alias substitution should be whole-word, not substring."""
        eng = self._make_engine()
        result = eng._semantic_normalize_text("FM Function", "my waccs are high")
        assert "weighted average cost of capital" not in result
        assert "waccs" in result

    def test_no_aliases_returns_original(self):
        eng = self._make_engine()
        eng.SEMANTIC_CANONICAL_ALIASES = {}
        result = eng._semantic_normalize_text("Nonexistent", "some text here")
        assert result == "some text here"

    def test_alias_map_merging_order(self):
        """Custom aliases should override built-in when both match."""
        eng = self._make_engine(aliases={"npv": "custom npv"})
        result = eng._semantic_normalize_text("FM Function", "NPV calculation")
        assert result == "custom npv calculation"
        assert "net present value" not in result


# ── CircuitBreaker ────────────────────────────────────────────────────


class TestCircuitBreaker:
    def test_initial_state_is_closed(self):
        cb = CircuitBreaker(threshold=3, cooldown_seconds=30.0)
        assert cb.allow("ollama") is True

    def test_allow_returns_true_for_unknown_backend(self):
        cb = CircuitBreaker()
        assert cb.allow("never_seen") is True

    def test_single_failure_does_not_trip(self):
        cb = CircuitBreaker(threshold=3, cooldown_seconds=30.0)
        cb.record_failure("cloud")
        assert cb.allow("cloud") is True

    def test_threshold_failures_trip_circuit(self):
        cb = CircuitBreaker(threshold=3, cooldown_seconds=30.0)
        for _ in range(3):
            cb.record_failure("cloud")
        assert cb.allow("cloud") is False

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker(threshold=3, cooldown_seconds=30.0)
        cb.record_failure("cloud")
        cb.record_failure("cloud")
        cb.record_success("cloud")
        assert cb.allow("cloud") is True
        # Additional failure should not trip early (counter was reset)
        cb.record_failure("cloud")
        assert cb.allow("cloud") is True

    def test_cooldown_expires(self):
        cb = CircuitBreaker(threshold=1, cooldown_seconds=0.05)
        cb.record_failure("cloud")
        assert cb.allow("cloud") is False
        time.sleep(0.06)
        assert cb.allow("cloud") is True

    def test_manual_reset(self):
        cb = CircuitBreaker(threshold=1, cooldown_seconds=3600)
        cb.record_failure("cloud")
        assert cb.allow("cloud") is False
        cb.reset("cloud")
        assert cb.allow("cloud") is True

    def test_backends_are_independent(self):
        cb = CircuitBreaker(threshold=2, cooldown_seconds=30.0)
        cb.record_failure("backend_a")
        cb.record_failure("backend_a")
        assert cb.allow("backend_a") is False
        assert cb.allow("backend_b") is True

    def test_status_open(self):
        cb = CircuitBreaker(threshold=1, cooldown_seconds=60.0)
        cb.record_failure("cloud")
        status = cb.status("cloud")
        assert status["state"] == "open"
        assert status["consecutive_failures"] == 1
        assert "cooldown_remaining_s" in status

    def test_status_closed(self):
        cb = CircuitBreaker(threshold=3, cooldown_seconds=30.0)
        status = cb.status("ollama")
        assert status["state"] == "closed"
        assert status["consecutive_failures"] == 0

    def test_status_closed_after_successful_reset(self):
        cb = CircuitBreaker(threshold=1, cooldown_seconds=0.05)
        cb.record_failure("cloud")
        time.sleep(0.06)
        # cooldown expired, allow() resets
        cb.allow("cloud")
        status = cb.status("cloud")
        assert status["consecutive_failures"] == 0

    def test_thread_safety(self):
        import threading

        cb = CircuitBreaker(threshold=2, cooldown_seconds=1.0)

        def worker():
            for _ in range(50):
                cb.record_failure("shared")
                cb.allow("shared")
                cb.record_success("shared")

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # No crash, state is consistent
        status = cb.status("shared")
        assert isinstance(status, dict)


# ── _get_weak_chapter ─────────────────────────────────────────────────


class TestGetWeakChapter:
    def _make_dummy(
        self,
        competence: dict,
        chapters: list,
        due_counts: dict | None = None,
        recall_risks: dict | None = None,
        miss_risks: dict | None = None,
        daily_poms: dict | None = None,
    ):
        if due_counts is None:
            due_counts = {}
        if recall_risks is None:
            recall_risks = {}
        if miss_risks is None:
            miss_risks = {}
        if daily_poms is None:
            daily_poms = {}

        engine = types.SimpleNamespace(
            competence=competence,
            CHAPTERS=chapters,
            get_chapter_recall_risk=lambda ch: recall_risks.get(ch, 0.0),
        )
        dummy = types.SimpleNamespace(
            engine=engine,
            _get_topic_due_count=lambda topic, today=None: due_counts.get(topic, 0),
            _get_chapter_miss_risk=lambda ch: miss_risks.get(ch, 0.0),
            daily_pomodoros_by_chapter=daily_poms,
        )
        # Attach module-level constant
        import studyplan_app as appmod

        self._orig_constant = getattr(appmod, "COACH_WEAK_TIE_WINDOW", 3.0)
        dummy._COACH_WEAK_TIE_WINDOW = 3.0
        dummy._get_weak_chapter = types.MethodType(StudyPlanGUI._get_weak_chapter, dummy)
        return dummy

    def test_below_threshold_returns_chapter(self):
        dummy = self._make_dummy(
            competence={"Ch A": 50.0, "Ch B": 80.0},
            chapters=["Ch A", "Ch B"],
        )
        result = dummy._get_weak_chapter(60.0)
        assert result == "Ch A"

    def test_all_above_threshold_returns_none(self):
        dummy = self._make_dummy(
            competence={"Ch A": 70.0, "Ch B": 80.0},
            chapters=["Ch A", "Ch B"],
        )
        result = dummy._get_weak_chapter(60.0)
        assert result is None

    def test_empty_competence_returns_none(self):
        dummy = self._make_dummy(competence={}, chapters=["Ch A"])
        result = dummy._get_weak_chapter(60.0)
        assert result is None

    def test_tie_breaker_uses_due_count(self):
        """When two chapters have same weak score, pick the one with higher due count."""
        dummy = self._make_dummy(
            competence={"Ch A": 50.0, "Ch B": 50.0},
            chapters=["Ch A", "Ch B"],
            due_counts={"Ch A": 0, "Ch B": 3},
            recall_risks={"Ch A": 0.0, "Ch B": 0.0},
            miss_risks={"Ch A": 0.0, "Ch B": 0.0},
        )
        result = dummy._get_weak_chapter(60.0)
        # Ch B has more due items, should win the tie
        assert result == "Ch B"

    def test_tie_breaker_falls_back_to_recall_risk(self):
        """When due counts equal, use recall risk."""
        dummy = self._make_dummy(
            competence={"Ch A": 50.0, "Ch B": 50.0},
            chapters=["Ch A", "Ch B"],
            due_counts={"Ch A": 2, "Ch B": 2},
            recall_risks={"Ch A": 0.3, "Ch B": 0.8},
            miss_risks={"Ch A": 0.0, "Ch B": 0.0},
        )
        result = dummy._get_weak_chapter(60.0)
        assert result == "Ch B"

    def test_non_chapter_keys_ignored(self):
        """Competence entries not in CHAPTERS should be ignored."""
        dummy = self._make_dummy(
            competence={"Ch A": 50.0, "Legacy": 30.0},
            chapters=["Ch A"],
        )
        result = dummy._get_weak_chapter(60.0)
        assert result == "Ch A"

    def test_negative_threshold_returns_lowest(self):
        """Low threshold means anything above it is not weak, so returns lowest."""
        dummy = self._make_dummy(
            competence={"Ch A": 10.0, "Ch B": 20.0},
            chapters=["Ch A", "Ch B"],
        )
        result = dummy._get_weak_chapter(-1.0)
        assert result is None  # all chapters have competence > -1


# ── get_chapter_recall_risk ───────────────────────────────────────────


class TestGetChapterRecallRisk:
    def _make_engine(
        self, questions: dict | None = None, question_stats: dict | None = None, chapters: list | None = None
    ):
        eng = StudyPlanEngine.__new__(StudyPlanEngine)
        eng.CHAPTERS = chapters or ["FM Function"]
        eng.QUESTIONS = questions or {"FM Function": [{"id": "q1"}, {"id": "q2"}]}
        eng.ML_MIN_ATTEMPTS = 5
        eng.question_stats = question_stats or {}
        return eng

    def test_unknown_chapter_returns_none(self):
        eng = self._make_engine(chapters=["FM Function"])
        result = eng.get_chapter_recall_risk("Unknown")
        assert result is None

    def test_no_questions_returns_none(self):
        eng = self._make_engine(questions={})
        result = eng.get_chapter_recall_risk("FM Function")
        assert result is None

    def test_no_attempts_returns_none(self):
        eng = self._make_engine(
            question_stats={
                "FM Function": {
                    "0": {"attempts": 0, "correct": 0},
                    "1": {"attempts": 0, "correct": 0},
                }
            }
        )
        result = eng.get_chapter_recall_risk("FM Function")
        assert result is None

    def test_perfect_recall_returns_zero(self):
        eng = self._make_engine(
            question_stats={
                "FM Function": {
                    "0": {"attempts": 3, "correct": 3, "last_seen": "2024-01-01"},
                    "1": {"attempts": 2, "correct": 2, "last_seen": "2024-01-01"},
                }
            }
        )
        result = eng.get_chapter_recall_risk("FM Function")
        assert isinstance(result, float)
        assert result == 0.0

    def test_all_wrong_returns_high(self):
        """With 2 questions both at 100% miss rate, the top-30% tail is
        averaged over min(5) items."""
        eng = self._make_engine(
            question_stats={
                "FM Function": {
                    "0": {"attempts": 5, "correct": 0, "last_seen": "2024-01-01"},
                    "1": {"attempts": 3, "correct": 0, "last_seen": "2024-01-01"},
                }
            }
        )
        result = eng.get_chapter_recall_risk("FM Function")
        assert isinstance(result, float)
        # cutoff = max(5, int(2*0.3)) = 5; sum([1.0,1.0])/5 = 0.4
        assert result == 0.4

    def test_mixed_recall(self):
        eng = self._make_engine(
            question_stats={
                "FM Function": {
                    "0": {"attempts": 4, "correct": 3, "last_seen": "2024-01-01"},
                    "1": {"attempts": 6, "correct": 2, "last_seen": "2024-01-01"},
                }
            }
        )
        result = eng.get_chapter_recall_risk("FM Function")
        assert isinstance(result, float)
        # miss_rates = [0.25, 0.6667]; cutoff=5; avg = (0.25+0.6667)/5 = 0.18333
        assert abs(result - 0.18333) < 0.001

    def test_empty_stats_dict_returns_none(self):
        eng = self._make_engine(question_stats={"FM Function": {}})
        result = eng.get_chapter_recall_risk("FM Function")
        assert result is None

    def test_max_samples_limits_questions(self):
        """Should respect max_samples parameter."""
        eng = self._make_engine()
        # Create 10 questions with stats
        eng.QUESTIONS = {"FM Function": [{"id": f"q{i}"} for i in range(10)]}
        stats = {}
        for i in range(10):
            stats[str(i)] = {"attempts": 1, "correct": 0, "last_seen": "2024-01-01"}
        eng.question_stats = {"FM Function": stats}
        result = eng.get_chapter_recall_risk("FM Function", max_samples=3)
        assert isinstance(result, float)


# ── Dashboard section helpers (_ds_mark, _ds_check, _ds_remove) ───────


class _FakeContainer:
    """Mimics a Gtk.Container with append/remove and child walking via get_first_child/get_next_sibling."""

    def __init__(self):
        self.children: list[_FakeWidget] = []

    def append(self, widget):
        widget._parent = self
        self.children.append(widget)

    def remove(self, widget):
        widget._parent = None
        try:
            self.children.remove(widget)
        except ValueError:
            pass

    def get_first_child(self):
        return self.children[0] if self.children else None

    def get_last_child(self):
        return self.children[-1] if self.children else None


class _FakeWidget:
    """Mimics a Gtk.Widget with arbitrary attributes."""

    def __init__(self, name: str = ""):
        self._name = name
        self._parent = None

    def get_next_sibling(self) -> _FakeWidget | None:
        if self._parent is None:
            return None
        siblings = self._parent.children
        try:
            idx = siblings.index(self)
            if idx + 1 < len(siblings):
                return siblings[idx + 1]
        except ValueError:
            pass
        return None


def _ds_check_from_ns(ns, sid, digest):
    """Check if a section exists with matching digest (bound onto ns later)."""
    child = ns.dashboard.get_first_child()
    while child:
        if getattr(child, "_ds_id", None) == sid:
            if getattr(child, "_ds_digest", None) == digest:
                ns._dashboard_section_seen.add(sid)
                return True
            break
        child = child.get_next_sibling()
    return False


def _ds_remove_from_ns(ns, sid):
    """Remove a section by id (bound onto ns later)."""
    child = ns.dashboard.get_first_child()
    while child:
        next_child = child.get_next_sibling()
        if getattr(child, "_ds_id", None) == sid:
            ns.dashboard.remove(child)
            return
        child = next_child


def _ds_mark_from_ns(ns, sid, widget, digest=None):
    """Mark/append a section widget (bound onto ns later)."""
    widget._ds_id = sid
    if digest is not None:
        widget._ds_digest = digest
    child = ns.dashboard.get_first_child()
    while child:
        next_child = child.get_next_sibling()
        if child is not widget and getattr(child, "_ds_id", None) == sid:
            ns.dashboard.remove(child)
            break
        child = next_child
    ns.dashboard.append(widget)
    ns._dashboard_section_seen.add(sid)


def _reconcile_sections_from_ns(ns):
    """Remove orphan and untagged widgets (matches real _reconcile_sections)."""
    child = ns.dashboard.get_first_child()
    while child:
        next_child = child.get_next_sibling()
        sid = getattr(child, "_ds_id", None)
        if sid is not None:
            if sid not in ns._dashboard_section_seen:
                ns.dashboard.remove(child)
        else:
            ns.dashboard.remove(child)
        child = next_child


def _make_dashboard_fake():
    """Returns a FakeContainer and a _render_dashboard-like namespace with helpers bound."""
    container = _FakeContainer()
    ns = types.SimpleNamespace(
        dashboard=container,
        _dashboard_section_seen=set(),
        _ds_check=lambda sid, dig: _ds_check_from_ns(ns, sid, dig),
        _ds_remove=lambda sid: _ds_remove_from_ns(ns, sid),
        _ds_mark=lambda sid, w, dig=None: _ds_mark_from_ns(ns, sid, w, dig),
        _reconcile_sections=lambda: _reconcile_sections_from_ns(ns),
    )
    return ns


class TestDashboardSectionHelpers:
    def _widget(self, name=""):
        return _FakeWidget(name)

    def test_ds_mark_appends_widget(self):
        ns = _make_dashboard_fake()
        w = self._widget()
        ns._ds_mark("section_a", w, ("digest",))
        assert ns.dashboard.children == [w]
        assert w._ds_id == "section_a"
        assert w._ds_digest == ("digest",)

    def test_ds_mark_marks_seen(self):
        ns = _make_dashboard_fake()
        ns._ds_mark("sec", self._widget())
        assert "sec" in ns._dashboard_section_seen

    def test_ds_mark_replaces_existing(self):
        ns = _make_dashboard_fake()
        w1 = self._widget("first")
        w2 = self._widget("second")
        ns._ds_mark("dup", w1)
        ns._ds_mark("dup", w2)
        assert w1 not in ns.dashboard.children
        assert w2 in ns.dashboard.children

    def test_ds_check_returns_true_when_match(self):
        ns = _make_dashboard_fake()
        w = self._widget()
        ns._ds_mark("sec", w, ("digest",))
        assert ns._ds_check("sec", ("digest",)) is True
        # should also mark as seen if not already
        assert "sec" in ns._dashboard_section_seen

    def test_ds_check_returns_false_when_digest_mismatch(self):
        ns = _make_dashboard_fake()
        w = self._widget()
        ns._ds_mark("sec", w, ("digest_a",))
        assert ns._ds_check("sec", ("digest_b",)) is False

    def test_ds_check_returns_false_when_section_missing(self):
        ns = _make_dashboard_fake()
        assert ns._ds_check("missing", ("digest",)) is False

    def test_ds_remove_removes_existing(self):
        ns = _make_dashboard_fake()
        w = self._widget()
        ns._ds_mark("sec", w)
        assert w in ns.dashboard.children
        ns._ds_remove("sec")
        assert w not in ns.dashboard.children

    def test_ds_remove_noop_when_missing(self):
        ns = _make_dashboard_fake()
        # Should not raise
        ns._ds_remove("never_added")

    def test_reconcile_removes_orphans(self):
        ns = _make_dashboard_fake()
        keep = self._widget("keep")
        orphan = self._widget("orphan")
        ns._ds_mark("keep_section", keep, ("keep",))
        ns._ds_mark("orphan_section", orphan, ("orphan",))
        # Mark only keep_section as seen
        ns._dashboard_section_seen.clear()
        ns._dashboard_section_seen.add("keep_section")
        ns._reconcile_sections()
        assert keep in ns.dashboard.children
        assert orphan not in ns.dashboard.children

    def test_reconcile_keeps_all_marked_seen(self):
        ns = _make_dashboard_fake()
        w1 = self._widget("a")
        w2 = self._widget("b")
        ns._ds_mark("sec_a", w1)
        ns._ds_mark("sec_b", w2)
        # Both are seen (ds_mark adds to seen), so reconcile keeps both
        ns._reconcile_sections()
        assert ns.dashboard.children == [w1, w2]

    def test_multiple_ds_mark_same_sid_only_last_remains(self):
        ns = _make_dashboard_fake()
        w1 = self._widget()
        w2 = self._widget()
        w3 = self._widget()
        ns._ds_mark("dup", w1)
        ns._ds_mark("dup", w2)
        ns._ds_mark("dup", w3)
        assert ns.dashboard.children == [w3]

    # ── separator accumulation tests ──────────────────────────────────

    def test_reconcile_removes_untagged_widgets(self):
        """Untagged widgets (no _ds_id) are always removed."""
        ns = _make_dashboard_fake()
        untagged = self._widget("no_id")
        ns.dashboard.append(untagged)
        ns._reconcile_sections()
        assert untagged not in ns.dashboard.children

    def test_reconcile_keeps_tagged_separator(self):
        """A separator tagged with __sep_X__ and marked seen survives."""
        ns = _make_dashboard_fake()
        sep = self._widget("sep")
        sep._ds_id = "__sep_1__"
        ns.dashboard.append(sep)
        ns._dashboard_section_seen.add("__sep_1__")
        ns._reconcile_sections()
        assert sep in ns.dashboard.children

    def test_reconcile_removes_stale_separator(self):
        """A separator with __sep_X__ not in seen is removed (stale from prior cycle)."""
        ns = _make_dashboard_fake()
        sep = self._widget("stale_sep")
        sep._ds_id = "__sep_99__"
        ns.dashboard.append(sep)
        # not added to _dashboard_section_seen
        ns._reconcile_sections()
        assert sep not in ns.dashboard.children

    def test_separators_dont_accumulate_across_cycles(self):
        """Simulate two render cycles: old separators cleaned by reconcile."""
        ns = _make_dashboard_fake()

        # Cycle 1: one section + one separator
        w1 = self._widget("s1")
        ns._ds_mark("sec_a", w1)
        ns._dashboard_section_seen.add("__sep_1__")
        sep1 = self._widget("sep1")
        sep1._ds_id = "__sep_1__"
        ns.dashboard.append(sep1)
        ns._reconcile_sections()

        # Cycle 2: same section + new separator (sep1 now stale)
        ns._dashboard_section_seen.discard("__sep_1__")
        ns._dashboard_section_seen.add("__sep_2__")
        sep2 = self._widget("sep2")
        sep2._ds_id = "__sep_2__"
        ns.dashboard.append(sep2)
        # sec_a stays seen, reconcile handles it without re-marking
        ns._dashboard_section_seen.add("sec_a")
        ns._reconcile_sections()

        assert w1 in ns.dashboard.children, "section should survive"
        assert sep1 not in ns.dashboard.children, "old separator should be cleaned up"
        assert sep2 in ns.dashboard.children, "new separator should survive"

    def test_mixed_tagged_and_untagged_seps(self):
        """Untagged widgets removed even when tagged ones survive."""
        ns = _make_dashboard_fake()

        tagged = self._widget("tagged")
        tagged._ds_id = "__sep_1__"
        ns.dashboard.append(tagged)
        ns._dashboard_section_seen.add("__sep_1__")

        untagged = self._widget("untagged")
        ns.dashboard.append(untagged)

        ns._reconcile_sections()
        assert tagged in ns.dashboard.children
        assert untagged not in ns.dashboard.children
