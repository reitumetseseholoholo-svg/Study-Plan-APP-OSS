"""Tests for the GGUF model registry."""

import json
import os
import struct
import tempfile

from studyplan.ai.gguf_registry import (
    GgufModel,
    GgufRegistry,
    GgufRegistryConfig,
    _build_model_entry,
    _infer_architecture,
    _infer_instruct,
    _infer_param_billions,
    _infer_quant,
    _is_gguf,
    _resolve_ollama_manifest_to_gguf,
)


_FAKE_GGUF_COUNTER = 0


def _write_fake_gguf(path: str, size: int = 4096) -> None:
    global _FAKE_GGUF_COUNTER
    _FAKE_GGUF_COUNTER += 1
    with open(path, "wb") as f:
        f.write(b"GGUF")
        tag = f"model_{_FAKE_GGUF_COUNTER}_{os.path.basename(path)}".encode()
        f.write(tag)
        remaining = size - 4 - len(tag)
        if remaining > 0:
            f.write(b"\x00" * remaining)


class TestInferArchitecture:
    def test_llama(self):
        assert _infer_architecture("Llama-3.2-3B-Instruct-Q4_0.gguf") == "llama"

    def test_qwen(self):
        assert _infer_architecture("Qwen2.5-1.5B-Instruct-Q4_K_M.gguf") == "qwen"

    def test_phi(self):
        assert _infer_architecture("Phi-3-mini-4k-instruct.Q4_0.gguf") == "phi"

    def test_gemma(self):
        assert _infer_architecture("gemma-2-2b-it-Q4_K_M.gguf") == "gemma"

    def test_deepseek(self):
        assert _infer_architecture("DeepSeek-R1-Distill-Qwen-1.5B-Q4_0.gguf") == "deepseek"

    def test_unknown(self):
        assert _infer_architecture("mystery-model.gguf") == "unknown"


class TestInferQuant:
    def test_q4_0(self):
        assert _infer_quant("Llama-3.2-3B-Instruct-Q4_0.gguf") == "q4_0"

    def test_q4_k_m(self):
        assert _infer_quant("Qwen2.5-1.5B-Instruct-Q4_K_M.gguf") == "q4_k_m"

    def test_no_quant(self):
        assert _infer_quant("some-model.gguf") == "unknown"


class TestInferParams:
    def test_1_5b(self):
        assert _infer_param_billions("Qwen2.5-1.5B-Instruct") == 1.5

    def test_3b(self):
        assert _infer_param_billions("Llama-3.2-3B-Instruct") == 3.0

    def test_no_params(self):
        assert _infer_param_billions("mystery") == 0.0


class TestInferInstruct:
    def test_instruct(self):
        assert _infer_instruct("Llama-3.2-3B-Instruct-Q4_0") is True

    def test_chat(self):
        assert _infer_instruct("some-model-chat.gguf") is True

    def test_it(self):
        assert _infer_instruct("gemma-2-2b-it-Q4_K_M") is True

    def test_base(self):
        assert _infer_instruct("llama-3.2-3b-q4") is False


class TestIsGguf:
    def test_valid(self):
        with tempfile.NamedTemporaryFile(suffix=".gguf", delete=False) as f:
            f.write(b"GGUF" + b"\x00" * 100)
            path = f.name
        try:
            assert _is_gguf(path) is True
        finally:
            os.unlink(path)

    def test_invalid(self):
        with tempfile.NamedTemporaryFile(suffix=".gguf", delete=False) as f:
            f.write(b"NOPE" + b"\x00" * 100)
            path = f.name
        try:
            assert _is_gguf(path) is False
        finally:
            os.unlink(path)

    def test_missing(self):
        assert _is_gguf("/nonexistent/path.gguf") is False


class TestBuildModelEntry:
    def test_basic(self):
        with tempfile.NamedTemporaryFile(suffix=".gguf", delete=False) as f:
            _write_fake_gguf(f.name, 4096)
            path = f.name
        try:
            m = _build_model_entry(
                path=path,
                filename="Qwen2.5-1.5B-Instruct-Q4_K_M.gguf",
                source="gpt4all",
                size_bytes=986048768,
            )
            assert m.architecture == "qwen"
            assert m.param_billions == 1.5
            assert m.quant_tag == "q4_k_m"
            assert m.is_instruct is True
            assert m.source == "gpt4all"
            assert m.content_hash
        finally:
            os.unlink(path)


class TestOllamaManifestResolution:
    def test_resolves_blob_by_digest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            blobs_dir = os.path.join(tmpdir, "blobs")
            os.makedirs(blobs_dir)
            blob_path = os.path.join(blobs_dir, "sha256-abc123")
            _write_fake_gguf(blob_path)

            manifest = {
                "schemaVersion": 2,
                "layers": [
                    {
                        "mediaType": "application/vnd.ollama.image.model",
                        "digest": "sha256:abc123",
                        "size": 4096,
                    }
                ],
            }
            manifest_path = os.path.join(tmpdir, "manifest.json")
            with open(manifest_path, "w") as f:
                json.dump(manifest, f)

            result = _resolve_ollama_manifest_to_gguf(manifest_path, blobs_dir)
            assert result == blob_path

    def test_resolves_from_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            gguf_path = os.path.join(tmpdir, "model.gguf")
            _write_fake_gguf(gguf_path)

            manifest = {
                "schemaVersion": 2,
                "layers": [
                    {
                        "mediaType": "application/vnd.ollama.image.model",
                        "digest": "sha256:xyz",
                        "from": gguf_path,
                        "size": 4096,
                    }
                ],
            }
            manifest_path = os.path.join(tmpdir, "manifest.json")
            with open(manifest_path, "w") as f:
                json.dump(manifest, f)

            result = _resolve_ollama_manifest_to_gguf(manifest_path, tmpdir)
            assert result == gguf_path

    def test_returns_none_for_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = {"schemaVersion": 2, "layers": []}
            manifest_path = os.path.join(tmpdir, "manifest.json")
            with open(manifest_path, "w") as f:
                json.dump(manifest, f)
            assert _resolve_ollama_manifest_to_gguf(manifest_path, tmpdir) is None


class TestGgufRegistryScanning:
    def test_scans_gpt4all_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_fake_gguf(os.path.join(tmpdir, "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"))
            _write_fake_gguf(os.path.join(tmpdir, "Llama-3.2-3B-Instruct-Q4_0.gguf"))
            with open(os.path.join(tmpdir, "not-a-model.txt"), "w") as f:
                f.write("nope")

            cfg = GgufRegistryConfig(
                gpt4all_dir=tmpdir,
                ollama_manifests_dir="/nonexistent",
                ollama_blobs_dir="/nonexistent",
            )
            registry = GgufRegistry(config=cfg)
            catalog = registry.catalog()
            assert len(catalog) == 2
            names = {m.name for m in catalog}
            assert any("qwen" in n for n in names)
            assert any("llama" in n for n in names)

    def test_deduplicates_identical_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            gpt4all_dir = os.path.join(tmpdir, "gpt4all")
            extra_dir = os.path.join(tmpdir, "extra")
            os.makedirs(gpt4all_dir)
            os.makedirs(extra_dir)

            data = b"GGUF" + b"\x42" * 4092  # identical content in both dirs
            with open(os.path.join(gpt4all_dir, "model-1b-q4_0.gguf"), "wb") as f:
                f.write(data)
            with open(os.path.join(extra_dir, "model-1b-q4_0-copy.gguf"), "wb") as f:
                f.write(data)

            cfg = GgufRegistryConfig(
                gpt4all_dir=gpt4all_dir,
                ollama_manifests_dir="/nonexistent",
                ollama_blobs_dir="/nonexistent",
                extra_dirs=[extra_dir],
            )
            registry = GgufRegistry(config=cfg)
            catalog = registry.catalog()
            assert len(catalog) == 1

    def test_ttl_caching(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_fake_gguf(os.path.join(tmpdir, "test-model-1b-q4_0.gguf"))
            cfg = GgufRegistryConfig(
                gpt4all_dir=tmpdir,
                ollama_manifests_dir="/nonexistent",
                ollama_blobs_dir="/nonexistent",
                ttl_seconds=300,
            )
            registry = GgufRegistry(config=cfg)
            c1 = registry.catalog()
            _write_fake_gguf(os.path.join(tmpdir, "another-model-2b-q4_0.gguf"))
            c2 = registry.catalog()
            assert len(c1) == len(c2) == 1

            c3 = registry.catalog(force_refresh=True)
            assert len(c3) == 2

    def test_empty_dir(self):
        cfg = GgufRegistryConfig(
            gpt4all_dir="/nonexistent",
            ollama_manifests_dir="/nonexistent",
            ollama_blobs_dir="/nonexistent",
        )
        registry = GgufRegistry(config=cfg)
        assert registry.catalog() == []

    def test_find_by_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_fake_gguf(os.path.join(tmpdir, "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"))
            cfg = GgufRegistryConfig(
                gpt4all_dir=tmpdir,
                ollama_manifests_dir="/nonexistent",
                ollama_blobs_dir="/nonexistent",
            )
            registry = GgufRegistry(config=cfg)
            m = registry.find_by_name("qwen2.5-1.5b-instruct-q4_k_m")
            assert m is not None
            assert m.architecture == "qwen"
