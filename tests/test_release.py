"""UI resources, manifest and deterministic distributable contents."""

import hashlib
import importlib.util
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components/deepseek_ai"


def leaves(value, prefix=""):
    if isinstance(value, dict):
        return {key for name, child in value.items() for key in leaves(child, prefix + "/" + name)}
    return {prefix}


def test_translations_cover_config_subentries_and_entities():
    english = json.loads((COMPONENT / "strings.json").read_text())
    chinese = json.loads((COMPONENT / "translations/zh-Hans.json").read_text())
    assert leaves(english) == leaves(chinese)
    assert english == json.loads((COMPONENT / "translations/en.json").read_text())
    for value in (english, chinese):
        assert set(value["config_subentries"]) == {
            "conversation",
            "ai_task",
            "evaluation",
            "stt",
            "tts",
        }
        assert "reauth_confirm" in value["config"]["step"]
        assert "reconfigure" in value["config"]["step"]
        assert value["entity"]["button"]["reset_usage"]["name"]


def test_manifest_and_hacs_metadata():
    manifest = json.loads((COMPONENT / "manifest.json").read_text())
    hacs = json.loads((ROOT / "hacs.json").read_text())
    assert manifest["domain"] == COMPONENT.name == "deepseek_ai"
    assert manifest["integration_type"] == "service" and manifest["config_flow"]
    assert manifest["iot_class"] == "cloud_polling"
    assert manifest["requirements"] == ["jsonschema==4.26.0", "mutagen==1.48.1"]
    assert hacs["homeassistant"] == "2026.11.3" and hacs["zip_release"]
    assert hacs["filename"] == "deepseek_ai.zip"


def test_install_archives_are_complete_and_repeatable(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("package", ROOT / "scripts/package.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Build from an isolated copy so the test never modifies release artifacts.
    import shutil

    shutil.copytree(
        COMPONENT,
        tmp_path / "custom_components/deepseek_ai",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    for filename in ("LICENSE", "README.md"):
        shutil.copyfile(ROOT / filename, tmp_path / filename)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    module.build()
    hashes = (tmp_path / "dist/SHA256SUMS").read_text()
    for line in hashes.splitlines():
        digest, filename = line.split("  ")
        assert hashlib.sha256((tmp_path / "dist" / filename).read_bytes()).hexdigest() == digest
    for filename, prefix in (
        ("deepseek_ai.zip", ""),
        ("deepseek_ai-0.1.0-manual.zip", "custom_components/deepseek_ai/"),
    ):
        with zipfile.ZipFile(tmp_path / "dist" / filename) as archive:
            names = archive.namelist()
            assert prefix + "manifest.json" in names and prefix + "LICENSE" in names
            assert prefix + "translations/zh-Hans.json" in names
            assert not any(
                "__pycache__" in name or ".env" in name or "venv" in name for name in names
            )
            assert archive.testzip() is None
    module.build()
    assert (tmp_path / "dist/SHA256SUMS").read_text() == hashes
