"""Deterministic HACS asset and manual-install archive, with SHA-256 manifest."""

import hashlib
import json
import os
import subprocess
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def archive_date(manifest_path: Path) -> tuple[int, int, int, int, int, int]:
    """Reproducible per revision, without reusing the old release's pyc stamp."""
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch is None:
        try:
            epoch = subprocess.check_output(
                ["git", "-C", str(ROOT), "log", "-1", "--format=%ct"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
        except OSError, subprocess.SubprocessError:
            epoch = str(int(manifest_path.stat().st_mtime))
    stamp = datetime.fromtimestamp(max(315532800, int(epoch)), UTC)
    return stamp.year, stamp.month, stamp.day, stamp.hour, stamp.minute, stamp.second


def build():
    source = ROOT / "custom_components/deepseek_ai"
    manifest = json.loads((source / "manifest.json").read_text())
    assert manifest["domain"] == "deepseek_ai"
    version = manifest["version"]
    date_time = archive_date(source / "manifest.json")
    assert manifest["config_flow"] and manifest["requirements"]
    for path in (source / "translations").glob("*.json"):
        assert json.loads(path.read_text())["title"] == "DeepSeek AI"
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    files = sorted(
        path
        for path in source.rglob("*")
        if path.is_file() and path.suffix in (".py", ".json") and "__pycache__" not in path.parts
    )
    for filename, prefix in (
        ("deepseek_ai.zip", ""),
        (f"deepseek_ai-{version}-manual.zip", "custom_components/deepseek_ai/"),
    ):
        with zipfile.ZipFile(output / filename, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in ("LICENSE", "README.md"):
                info = zipfile.ZipInfo(prefix + name, date_time=date_time)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, (ROOT / name).read_bytes())
            for path in files:
                info = zipfile.ZipInfo(
                    prefix + path.relative_to(source).as_posix(), date_time=date_time
                )
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, path.read_bytes())
    with zipfile.ZipFile(
        output / f"deepseek-ha-{version}-source.zip", "w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        for path in sorted(ROOT.rglob("*")):
            relative = path.relative_to(ROOT)
            if relative == Path("test-results.xml"):
                continue
            if not path.is_file() or any(
                (part.startswith(".") and part not in {".github", ".gitignore"})
                or part in {"dist", "__pycache__", "_ha-core"}
                for part in relative.parts
            ):
                continue
            info = zipfile.ZipInfo("deepseek-ha/" + relative.as_posix(), date_time=date_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
    sums = [
        hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name
        for path in sorted(
            [
                output / "deepseek_ai.zip",
                output / f"deepseek_ai-{version}-manual.zip",
                output / f"deepseek-ha-{version}-source.zip",
            ]
        )
    ]
    (output / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    print("\n".join(sums))


if __name__ == "__main__":
    build()
