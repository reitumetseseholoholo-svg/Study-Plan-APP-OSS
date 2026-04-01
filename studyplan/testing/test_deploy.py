from deploy import _discover_smoke_test_paths


def test_discover_smoke_test_paths_includes_existing_paths(tmp_path):
    release = tmp_path / "release"
    (release / "tests").mkdir(parents=True)
    (release / "studyplan" / "testing").mkdir(parents=True)

    assert _discover_smoke_test_paths(release) == ("tests", "studyplan/testing")


def test_discover_smoke_test_paths_skips_missing_paths(tmp_path):
    release = tmp_path / "release"
    (release / "tests").mkdir(parents=True)

    assert _discover_smoke_test_paths(release) == ("tests",)
