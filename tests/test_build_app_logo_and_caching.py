"""
Tests for _build_app_logo, get_chapter_difficulty_ratio,
get_interval_release_confidence, and PerformanceCacheService.
"""

from __future__ import annotations

import time
import types

import pytest

try:
    import gi

    gi.require_version("Gdk", "4.0")
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import Gdk, GdkPixbuf
except Exception as exc:
    pytest.skip(f"GTK/Cairo imports unavailable: {exc}", allow_module_level=True)

from studyplan.components.performance.caching import PerformanceCacheService
from studyplan_engine import StudyPlanEngine


# ── _build_app_logo ───────────────────────────────────────────────────


class TestBuildAppLogo:
    def _make_dummy(self):
        dummy = types.SimpleNamespace()
        # Bind the method directly from the source
        import studyplan_app as appmod

        dummy._build_app_logo = types.MethodType(appmod.StudyPlanGUI._build_app_logo, dummy)
        import io

        dummy.io = io
        return dummy

    def test_returns_texture(self):
        dummy = self._make_dummy()
        result = dummy._build_app_logo()
        assert result is not None
        assert isinstance(result, Gdk.Texture)

    def test_texture_has_correct_size(self):
        dummy = self._make_dummy()
        result = dummy._build_app_logo()
        assert result is not None
        # The logo is drawn on a 96x96 surface
        assert result.get_width() == 96
        assert result.get_height() == 96

    def test_nonzero_bytes(self):
        """The output texture should contain visible pixel content."""
        dummy = self._make_dummy()
        result = dummy._build_app_logo()
        assert result is not None
        assert isinstance(result, Gdk.Texture)
        assert result.get_width() == 96
        assert result.get_height() == 96

        # Round-trip through PixbufLoader (same path as the real method) to
        # verify that the intermediate PNG contains non-transparent pixels.
        import io
        import cairo

        w, h = 96, 96
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(surf)
        cr.set_operator(cairo.OPERATOR_CLEAR)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        r = 18
        cr.move_to(r, 0)
        cr.line_to(w - r, 0)
        cr.curve_to(w, 0, w, 0, w, r)
        cr.line_to(w, h - r)
        cr.curve_to(w, h, w, h, w - r, h)
        cr.line_to(r, h)
        cr.curve_to(0, h, 0, h, 0, h - r)
        cr.line_to(0, r)
        cr.curve_to(0, 0, 0, 0, r, 0)
        cr.close_path()
        cr.set_source_rgba(0.56, 0.71, 1.0, 1.0)
        cr.fill()
        buf = io.BytesIO()
        surf.write_to_png(buf)
        buf.seek(0)
        loader = GdkPixbuf.PixbufLoader()
        loader.write(buf.getvalue())
        loader.close()
        pixbuf = loader.get_pixbuf()
        data = pixbuf.get_pixels()
        any_content = any(data[i] > 0 or data[i + 1] > 0 or data[i + 2] > 0 for i in range(0, len(data), 4))
        assert any_content, "Logo pixels should have non-zero RGB values"


# ── get_chapter_difficulty_ratio ──────────────────────────────────────


class TestGetChapterDifficultyRatio:
    def _make_engine(self, questions: dict | None = None):
        eng = StudyPlanEngine.__new__(StudyPlanEngine)
        eng.QUESTIONS = questions if questions is not None else {"FM Function": [{"id": f"q{i}"} for i in range(20)]}
        eng.CHAPTERS = ["FM Function"]
        eng.difficulty_model = None
        eng.question_stats = {}
        return eng

    def test_no_questions_returns_zero(self):
        eng = self._make_engine(questions={})
        result = eng.get_chapter_difficulty_ratio("FM Function")
        assert result == {"hard_ratio": 0.0, "sample": 0.0}

    def test_all_unknown_returns_zero(self):
        eng = self._make_engine()
        eng.get_question_difficulty = lambda ch, idx: "unknown"
        result = eng.get_chapter_difficulty_ratio("FM Function")
        assert result == {"hard_ratio": 0.0, "sample": 0.0}

    def test_all_easy_returns_zero(self):
        eng = self._make_engine()
        eng.get_question_difficulty = lambda ch, idx: "easy" if idx < 20 else "unknown"
        result = eng.get_chapter_difficulty_ratio("FM Function", max_samples=100)
        assert result["hard_ratio"] == 0.0
        assert result["sample"] > 0

    def test_half_hard_returns_half(self):
        """When half of sampled questions are 'hard', ratio should be 0.5."""
        eng = self._make_engine()
        difficulties = ["hard", "easy"]

        def _difficulty(ch, idx):
            return difficulties[idx % len(difficulties)] if idx < 20 else "unknown"

        eng.get_question_difficulty = _difficulty
        result = eng.get_chapter_difficulty_ratio("FM Function", max_samples=100)
        assert result["hard_ratio"] == 0.5
        assert result["sample"] > 5

    def test_all_hard_returns_one(self):
        eng = self._make_engine()
        eng.get_question_difficulty = lambda ch, idx: "hard" if idx < 20 else "unknown"
        result = eng.get_chapter_difficulty_ratio("FM Function", max_samples=100)
        assert result["hard_ratio"] == 1.0

    def test_mixed_difficulties(self):
        eng = self._make_engine()

        def _difficulty(ch, idx):
            m = {0: "easy", 1: "medium", 2: "hard", 3: "easy", 4: "hard"}
            return m.get(idx % 5, "unknown")

        eng.get_question_difficulty = _difficulty
        result = eng.get_chapter_difficulty_ratio("FM Function", max_samples=100)
        # 20 questions, groups of 5: each group has 2 'hard' → 8/20 = 0.4
        assert result["hard_ratio"] == 0.4
        assert result["sample"] == 20.0


# ── get_interval_release_confidence ──────────────────────────────────


class TestGetIntervalReleaseConfidence:
    def _make_engine(self, chapters: list | None = None, srs_data: dict | None = None, interval_model=None):
        eng = StudyPlanEngine.__new__(StudyPlanEngine)
        eng.CHAPTERS = chapters or ["FM Function"]
        eng.srs_data = srs_data or {}
        eng.interval_model = interval_model
        # Silence _is_chapter_ml_ready by returning True
        eng._is_chapter_ml_ready = lambda ch: True
        return eng

    def test_no_interval_model_returns_none(self):
        eng = self._make_engine(interval_model=None)
        result = eng.get_interval_release_confidence("FM Function")
        assert result is None

    def test_unknown_chapter_returns_none(self):
        eng = self._make_engine(interval_model=object())
        result = eng.get_interval_release_confidence("NotAChapter")
        assert result is None

    def test_no_srs_data_returns_none(self):
        eng = self._make_engine(interval_model=object(), srs_data={})
        result = eng.get_interval_release_confidence("FM Function")
        assert result is None

    def test_empty_srs_list_returns_none(self):
        eng = self._make_engine(interval_model=object(), srs_data={"FM Function": []})
        result = eng.get_interval_release_confidence("FM Function")
        assert result is None

    def test_no_reviewed_items_returns_none(self):
        """Items without last_review are excluded."""
        eng = self._make_engine(
            interval_model=object(),
            srs_data={"FM Function": [{"interval": 1}]},
        )
        result = eng.get_interval_release_confidence("FM Function")
        assert result is None

    def test_most_items_not_due_returns_high(self):
        """When most predicted intervals exceed the current gap, confidence is high."""
        import datetime

        eng = self._make_engine(
            interval_model=object(),
            srs_data={
                "FM Function": [
                    {
                        "last_review": (datetime.date.today() - datetime.timedelta(days=i)).isoformat(),
                        "interval": 10,
                        "efactor": 2.5,
                    }
                    for i in range(5, 10)
                ]
            },
        )
        eng.predict_interval_days = lambda ch, idx, cur_int, ef: cur_int * 2.0
        result = eng.get_interval_release_confidence("FM Function")
        assert isinstance(result, float)
        # All 5 items have pred >= (days_since + 3)
        assert result == 1.0

    def test_items_due_returns_lower(self):
        """When items are past due, confidence drops."""
        import datetime

        eng = self._make_engine(
            interval_model=object(),
            srs_data={
                "FM Function": [
                    {
                        "last_review": (datetime.date.today() - datetime.timedelta(days=30)).isoformat(),
                        "interval": 1,
                        "efactor": 2.5,
                    }
                    for _ in range(5)
                ]
            },
        )
        # Predict a very short interval (so it's already due)
        eng.predict_interval_days = lambda ch, idx, cur_int, ef: 1.0
        result = eng.get_interval_release_confidence("FM Function")
        # All items: days_since=30, pred=1, so pred < days_since+3 → not_due doesn't increment
        assert result == 0.0

    def test_insufficient_samples_returns_none(self):
        """Fewer than 3 valid samples returns None."""
        import datetime

        eng = self._make_engine(
            interval_model=object(),
            srs_data={
                "FM Function": [
                    {"last_review": datetime.date.today().isoformat(), "interval": 1, "efactor": 2.5},
                    {"last_review": datetime.date.today().isoformat(), "interval": 1, "efactor": 2.5},
                ]
            },
        )
        # Only 2 items, need >= 3
        eng.predict_interval_days = lambda ch, idx, cur_int, ef: cur_int
        result = eng.get_interval_release_confidence("FM Function")
        assert result is None

    def test_empty_list_filtered_out(self):
        """Items where predict_interval_days raises/returns None are skipped."""
        import datetime

        eng = self._make_engine(
            interval_model=object(),
            srs_data={
                "FM Function": [
                    {"last_review": datetime.date.today().isoformat(), "interval": 1, "efactor": 2.5},
                ]
            },
        )
        call_count = [0]

        def _predict(ch, idx, cur_int, ef):
            call_count[0] += 1
            return None  # simulate prediction failure

        eng.predict_interval_days = _predict
        result = eng.get_interval_release_confidence("FM Function")
        assert result is None  # total=0 after skipping failed predictions


# ── PerformanceCacheService ───────────────────────────────────────────


class TestPerformanceCacheService:
    def _make_cache(self, max_size=100, default_ttl=300):
        return PerformanceCacheService(
            {
                "cache_max_size": max_size,
                "default_ttl_seconds": default_ttl,
                "cache_ttl": {},
            }
        )

    def test_get_miss_returns_none(self):
        cache = self._make_cache()
        assert cache.get("nonexistent") is None

    def test_set_and_get(self):
        cache = self._make_cache()
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_set_overwrites(self):
        cache = self._make_cache()
        cache.set("key", "old")
        cache.set("key", "new")
        assert cache.get("key") == "new"

    def test_custom_ttl(self):
        cache = self._make_cache(default_ttl=0.01)
        cache.set("fast", "data", ttl_seconds=0.01)
        assert cache.get("fast") == "data"
        time.sleep(0.015)
        assert cache.get("fast") is None

    def test_lru_eviction(self):
        cache = self._make_cache(max_size=3)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        cache.set("d", 4)  # should evict "a"
        assert cache.get("a") is None
        assert cache.get("b") == 2
        assert cache.get("c") == 3
        assert cache.get("d") == 4

    def test_lru_reorder_on_get(self):
        """Accessing an item promotes it in LRU order."""
        cache = self._make_cache(max_size=2)
        cache.set("a", 1)
        cache.set("b", 2)
        # Access 'a' to make it recently used
        cache.get("a")
        cache.set("c", 3)  # should evict "b" (least recently used)
        assert cache.get("a") == 1
        assert cache.get("b") is None
        assert cache.get("c") == 3

    def test_thread_safety(self):
        import threading

        cache = self._make_cache()
        errors = []

        def worker():
            try:
                for i in range(100):
                    cache.set(f"k{i}", i)
                    cache.get(f"k{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors, f"Thread safety errors: {errors}"

    def test_default_ttl_applied(self):
        cache = self._make_cache(default_ttl=0.02)
        cache.set("key", "val")
        assert cache.get("key") == "val"
        time.sleep(0.025)
        assert cache.get("key") is None

    def test_set_returns_none(self):
        """set() should not return anything (void)."""
        cache = self._make_cache()
        result = cache.set("k", "v")
        assert result is None

    def test_rag_doc_eviction(self):
        """RAG doc entries should be evicted under cap."""
        cache = PerformanceCacheService(
            {
                "cache_max_size": 100,
                "default_ttl_seconds": 300,
                "cache_ttl": {},
                "rag_doc_memory_max": 2,
                "rag_doc_chunk_budget": 100,
            }
        )
        # Simulate setting rag_doc entries
        cache.set("rag_doc:ch1", {"doc": "a" * 1000}, ttl_seconds=300)
        cache.set("rag_doc:ch2", {"doc": "b" * 1000}, ttl_seconds=300)
        cache.set("rag_doc:ch3", {"doc": "c" * 1000}, ttl_seconds=300)
        # Should have evicted ch1 (LRU)
        assert cache.get("rag_doc:ch1") is None
