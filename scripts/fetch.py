#!/usr/bin/env python3
"""Download helpers with a browser User-Agent (the Cursor CDN 403s HEAD/curl defaults)."""

from __future__ import annotations

import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

from detect import USER_AGENT


def download(url: str, dest: Path, *, label: str | None = None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  cache hit {dest.name} ({dest.stat().st_size} bytes)")
        return dest
    print(f"  GET {label or dest.name}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=600) as resp, tmp.open("wb") as fh:
        shutil.copyfileobj(resp, fh)
    tmp.replace(dest)
    print(f"  wrote {dest} ({dest.stat().st_size} bytes)")
    return dest


def run(cmd: list[str], *, cwd: Path | None = None) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def which_or_die(*names: str) -> str:
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    raise SystemExit(f"Need one of {names} on PATH")


def extract_archive(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    name = archive.name.lower()
    if name.endswith(".zip"):
        run(["unzip", "-qo", str(archive), "-d", str(dest)])
        return
    if name.endswith(".tar.gz") or name.endswith(".tgz"):
        run(["tar", "-xzf", str(archive), "-C", str(dest)])
        return
    if name.endswith(".rpm"):
        # rpm2cpio | cpio into dest
        dest.mkdir(parents=True, exist_ok=True)
        rpm2cpio = which_or_die("rpm2cpio")
        cpio = which_or_die("cpio")
        with subprocess.Popen([rpm2cpio, str(archive)], stdout=subprocess.PIPE) as proc:
            subprocess.run(
                [cpio, "-idmu", "--quiet"],
                cwd=dest,
                stdin=proc.stdout,
                check=True,
            )
            if proc.wait() != 0:
                raise SystemExit("rpm2cpio failed")
        return
    if name.endswith(".dmg"):
        seven = which_or_die("7z", "7zz")
        run([seven, "x", "-y", f"-o{dest}", str(archive)])
        return
    raise SystemExit(f"Don't know how to extract {archive}")
