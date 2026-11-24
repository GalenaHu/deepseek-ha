"""Deterministic HACS asset and manual-install archive, with SHA-256 manifest."""

import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build():
    source = ROOT / "custom_components/deepseek_ai"
    manifest = json.loads((source / "manifest.json").read_text())
    assert manifest["domain"] == "deepseek_ai" and manifest["version"] == "0.1.0"
    assert manifest["config_flow"] and manifest["requirements"]
    for path in (source / "translations").glob("*.json"):
        assert json.loads(path.read_text())["title"] == "DeepSeek AI"
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    files = sorted(path for path in source.rglob("*") if path.is_file() and path.suffix in (".py", ".json") and "__pycache__" not in path.parts)
    for filename, prefix in (("deepseek_ai.zip", ""), ("deepseek_ai-0.1.0-manual.zip", "custom_components/deepseek_ai/")):
        with zipfile.ZipFile(output / filename, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in files:
                info = zipfile.ZipInfo(prefix + path.relative_to(source).as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, path.read_bytes())
    sums = [hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name for path in sorted(output.glob("*.zip"))]
    (output / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    print("\n".join(sums))


if __name__ == "__main__":
    build()

