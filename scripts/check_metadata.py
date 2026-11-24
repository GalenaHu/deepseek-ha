"""Run metadata plugins from the exact supported HA source against real HA."""

import argparse
import runpy
import sys
from pathlib import Path

import homeassistant
from homeassistant.const import __version__ as HA_VERSION


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ha-source", required=True, type=Path)
    parser.add_argument("--ha-version", default="2026.11.2", choices=("2026.11.2", "2026.11.3"))
    args = parser.parse_args()
    if HA_VERSION != args.ha_version:
        parser.error(f"Install homeassistant=={args.ha_version} for metadata validation")
    source = args.ha_source.resolve()
    if not (source / "script/hassfest/__main__.py").is_file():
        parser.error("HA source must include script/hassfest and packages/hassfest")
    # homeassistant is already imported from the installed target dependency.
    sys.path[:0] = [str(source / "packages/hassfest"), str(source)]
    sys.argv = [
        "hassfest",
        "--action",
        "validate",
        "--integration-path",
        str(Path(__file__).resolve().parents[1] / "custom_components/deepseek_ai"),
        "--core-path",
        str(Path(homeassistant.__file__).resolve().parents[1]),
        "--plugins",
        "manifest,json,config_schema,integration_type,translations,config_flow",
    ]
    runpy.run_module("script.hassfest", run_name="__main__")


if __name__ == "__main__":
    main()
