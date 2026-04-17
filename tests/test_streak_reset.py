"""Tests for study streak load-time reset logic.

The streak must be reset to 0 when the app loads and the last study date
is more than 1 day ago (i.e., the user missed at least one day).
"""

import datetime
import json
import os
import types


def _make_streak_loader(config_home: str):
    """Return a callable that runs the load_streak_data logic on a mock object.

    This replicates the production logic from StudyPlanApp.load_streak_data
    to allow unit testing without importing the GTK application.
    """

    def load_streak_data(obj):
        streak_file = os.path.join(config_home, "streak.json")
        try:
            if os.path.exists(streak_file):
                try:
                    with open(streak_file, "r") as f:
                        data = json.load(f)
                        if data is not None and "last_study_date" in data:
                            try:
                                obj.last_study_date = datetime.date.fromisoformat(data["last_study_date"])
                            except ValueError:
                                obj.last_study_date = None
                        obj.study_streak = data.get("study_streak", 0)
                        # Reset streak if last study was more than 1 day ago (missed a day)
                        today = datetime.date.today()
                        if obj.last_study_date is not None and (today - obj.last_study_date).days > 1:
                            obj.study_streak = 0
                except json.JSONDecodeError:
                    obj.study_streak = 0
                except Exception:
                    obj.study_streak = 0
        except Exception:
            obj.study_streak = 0

    return load_streak_data


def _write_streak_file(config_home: str, last_study_date_iso: str, streak: int):
    os.makedirs(config_home, exist_ok=True)
    streak_file = os.path.join(config_home, "streak.json")
    with open(streak_file, "w") as f:
        json.dump({"last_study_date": last_study_date_iso, "study_streak": streak}, f)


def test_streak_reset_when_last_study_was_two_days_ago(tmp_path):
    """Streak should be reset to 0 when last study was 2 days ago."""
    config_home = str(tmp_path)
    two_days_ago = (datetime.date.today() - datetime.timedelta(days=2)).isoformat()
    _write_streak_file(config_home, two_days_ago, 29)

    obj = types.SimpleNamespace(last_study_date=None, study_streak=0)
    _make_streak_loader(config_home)(obj)

    assert obj.study_streak == 0, "Streak should be reset when last study was 2 days ago"


def test_streak_preserved_when_last_study_was_yesterday(tmp_path):
    """Streak should be preserved when last study was exactly yesterday."""
    config_home = str(tmp_path)
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    _write_streak_file(config_home, yesterday, 15)

    obj = types.SimpleNamespace(last_study_date=None, study_streak=0)
    _make_streak_loader(config_home)(obj)

    assert obj.study_streak == 15, "Streak should be preserved when last study was yesterday"


def test_streak_preserved_when_last_study_was_today(tmp_path):
    """Streak should be preserved when last study was today."""
    config_home = str(tmp_path)
    today = datetime.date.today().isoformat()
    _write_streak_file(config_home, today, 7)

    obj = types.SimpleNamespace(last_study_date=None, study_streak=0)
    _make_streak_loader(config_home)(obj)

    assert obj.study_streak == 7, "Streak should be preserved when last study was today"


def test_streak_reset_when_last_study_was_many_days_ago(tmp_path):
    """Streak should be reset to 0 when the gap is much larger than 1 day."""
    config_home = str(tmp_path)
    long_ago = (datetime.date.today() - datetime.timedelta(days=10)).isoformat()
    _write_streak_file(config_home, long_ago, 50)

    obj = types.SimpleNamespace(last_study_date=None, study_streak=0)
    _make_streak_loader(config_home)(obj)

    assert obj.study_streak == 0, "Streak should be reset when gap is 10 days"


def test_streak_zero_when_no_streak_file(tmp_path):
    """Streak stays at default 0 when no streak file exists."""
    config_home = str(tmp_path / "nonexistent")
    obj = types.SimpleNamespace(last_study_date=None, study_streak=0)
    _make_streak_loader(config_home)(obj)

    assert obj.study_streak == 0
