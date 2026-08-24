#!/usr/bin/env python3
"""Locate native Node addons inside an extracted Cursor RPM tree."""

from __future__ import annotations

import sys
from pathlib import Path

# (logical name, glob under the extracted RPM root)
NATIVE_GLOBS: dict[str, tuple[str, ...]] = {
    "tree-chunk-napi": (
        "**/tree-chunk-napi.linux-{napi}-gnu.node",
        "**/tree-chunk-napi.linux-{napi}-musl.node",
    ),
    "cursor-proclist": (
        "**/cursor_proclist.node",
    ),
    "tree-sitter": (
        "**/tree_sitter_runtime_binding.node",
    ),
    "tree-sitter-bash": (
        "**/tree_sitter_bash_binding.node",
        "**/tree-sitter-bash.node",
    ),
    "whichlang": (
        "**/whichlang-node.linux-{napi}-gnu.node",
        "**/whichlang-node.linux-{napi}-musl.node",
    ),
}


def napi_triple(arch: str) -> str:
    """arch is rpm arch: aarch64 or x86_64."""
    return {"aarch64": "arm64", "x86_64": "x64"}[arch]


def find_one(root: Path, patterns: tuple[str, ...], napi: str) -> Path:
    matches: list[Path] = []
    for pattern in patterns:
        matches.extend(root.glob(pattern.format(napi=napi)))
    matches = [m for m in matches if m.is_file()]
    if not matches:
        raise FileNotFoundError(f"no files matching {patterns} under {root}")
    # Prefer gnu over musl, and agent-exec copies over other duplicates.
    matches.sort(key=lambda p: ("musl" in p.name, "cursor-agent-exec" not in str(p), len(str(p))))
    return matches[0]


def extract_natives(cursor_root: Path, arch: str) -> dict[str, Path]:
    napi = napi_triple(arch)
    found: dict[str, Path] = {}
    missing: list[str] = []
    for name, patterns in NATIVE_GLOBS.items():
        try:
            found[name] = find_one(cursor_root, patterns, napi)
            print(f"  cursor native {name}: {found[name]}")
        except FileNotFoundError:
            missing.append(name)
            print(f"  cursor native {name}: MISSING")
    if missing:
        print(
            "warning: Cursor RPM did not contain: "
            + ", ".join(missing)
            + " — those will be N-API stubs",
            file=sys.stderr,
        )
    return found
