"""Tests for contrib/garuda-low-ram-llm/merge_kernel_cmdline.py (loaded by file path)."""

import importlib.util
import tempfile
from pathlib import Path


def _load_merge_module():
    root = Path(__file__).resolve().parents[2]
    path = root / "contrib/garuda-low-ram-llm/merge_kernel_cmdline.py"
    spec = importlib.util.spec_from_file_location("_merge_kernel_cmdline", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_merge_tokens_replaces_same_key():
    m = _load_merge_module()
    out = m._merge_tokens("quiet a=1 b=2", ["a=9", "c=3"])
    parts = out.split()
    assert "a=9" in parts
    assert "a=1" not in out
    assert "b=2" in parts
    assert "c=3" in parts


def test_merge_tokens_bare_flag_once():
    m = _load_merge_module()
    out = m._merge_tokens("quiet ro", ["debug"])
    assert out.split() == ["quiet", "ro", "debug"]
    out2 = m._merge_tokens(out, ["debug"])
    assert out2.split().count("debug") == 1


def test_merge_dracut_and_grub_roundtrip():
    m = _load_merge_module()
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        repo = t / "repo"
        repo.mkdir()
        (repo / "kernel-cmdline-studyplan-tuning.txt").write_text(
            "transparent_hugepage=madvise zswap.max_pool_percent=20\n", encoding="utf-8"
        )
        dracut = t / "dracut-custom.conf"
        dracut.write_text(
            "compress='zstd'\n"
            'kernel_cmdline="root=UUID=x rw quiet transparent_hugepage=always zswap.max_pool_percent=25"\n',
            encoding="utf-8",
        )
        grub = t / "grub"
        grub.write_text(
            'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash transparent_hugepage=always"\n',
            encoding="utf-8",
        )
        additions = m._load_additions(repo)
        dracut.write_text(m.merge_dracut(dracut, additions), encoding="utf-8")
        grub.write_text(m.merge_grub_default(grub, additions), encoding="utf-8")
        dline = dracut.read_text(encoding="utf-8")
        assert "transparent_hugepage=madvise" in dline
        assert "transparent_hugepage=always" not in dline
        assert "zswap.max_pool_percent=20" in dline
        assert "zswap.max_pool_percent=25" not in dline
        assert "root=UUID=x" in dline
        gtext = grub.read_text(encoding="utf-8")
        assert "transparent_hugepage=madvise" in gtext
        assert "quiet" in gtext
        assert "splash" in gtext
