#!/usr/bin/env python3
"""Decide whether CI should build, and for which arches.

Writes GitHub Actions outputs:
  grokbot_version
  skip          (true if both arch RPMs already exist, unless FORCE)
  matrix        JSON object with an `include` list of {arch, runner}
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from detect import detect_grokbot_version, github_release_assets  # noqa: E402

ARCHES = (
    {"arch": "x86_64", "runner": "ubuntu-24.04"},
    {"arch": "aarch64", "runner": "ubuntu-24.04-arm"},
)


def rpm_present(assets: list[str], version: str, arch: str) -> bool:
    suffix = f".{arch}.rpm"
    prefix = f"grok-bot-{version}-"
    return any(name.startswith(prefix) and name.endswith(suffix) for name in assets)


def main() -> int:
    override = os.environ.get("GROKBOT_VERSION") or None
    if override == "":
        override = None
    force = os.environ.get("FORCE", "").lower() in {"1", "true", "yes"}
    version = detect_grokbot_version(override)
    tag = f"v{version}"
    assets = github_release_assets(tag) or []

    include: list[dict[str, str]] = []
    for row in ARCHES:
        if not force and rpm_present(assets, version, row["arch"]):
            print(f"skip {row['arch']}: {tag} already has an RPM")
            continue
        include.append(row)

    skip = not include
    matrix = {"include": include}
    outputs = {
        "grokbot_version": version,
        "skip": "true" if skip else "false",
        "matrix": json.dumps(matrix, separators=(",", ":")),
    }
    out_path = os.environ.get("GITHUB_OUTPUT")
    if out_path:
        with open(out_path, "a", encoding="utf-8") as fh:
            for key, value in outputs.items():
                if re.search(r"[\n\r]", value):
                    raise SystemExit(f"refusing to write multiline output {key}")
                fh.write(f"{key}={value}\n")
    for key, value in outputs.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
