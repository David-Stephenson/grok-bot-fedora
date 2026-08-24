#!/usr/bin/env python3
"""Build an unofficial Grok Bot RPM for Fedora.

Pipeline:
  1. Detect Grok Bot + Cursor versions (or take CLI overrides).
  2. Download the macOS DMG (app.asar is arch-independent JS).
  3. Download Electron for linux-${arch} at the version baked into the DMG.
  4. Download the Cursor Linux RPM for this arch and pull native .node addons.
  5. Fetch a better-sqlite3 prebuild matching Electron's NODE_MODULE_VERSION.
  6. Stage /usr/libexec/grok-bot and run rpmbuild.
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import shutil
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

from detect import GROKBOT_DMG, detect_cursor, detect_grokbot_version, http_json  # noqa: E402
from fetch import download, extract_archive, run, which_or_die  # noqa: E402
from natives import extract_natives, napi_triple  # noqa: E402

ELECTRON_ABI_FALLBACK = {
    "37": "136",
    "38": "139",
    "39": "140",
    "40": "143",
    "41": "145",
    "42": "146",
}
ELECTRON_ZIP = (
    "https://github.com/electron/electron/releases/download/"
    "v{version}/electron-v{version}-linux-{e_arch}.zip"
)
ELECTRON_HEADERS = (
    "https://artifacts.electronjs.org/headers/dist/v{version}/node-v{version}-headers.tar.gz"
)
BETTER_SQLITE_RELEASES = "https://api.github.com/repos/WiseLibs/better-sqlite3/releases"
NODE_ABI_REGISTRY = "https://raw.githubusercontent.com/electron/node-abi/main/abi_registry.json"
CURSOR_NATIVE_KEYS = (
    "tree-chunk-napi",
    "cursor-proclist",
    "tree-sitter",
    "tree-sitter-bash",
    "whichlang",
)


def electron_arch(rpm_arch: str) -> str:
    return {"aarch64": "arm64", "x86_64": "x64"}[rpm_arch]


def cursor_platform(rpm_arch: str) -> str:
    return {"aarch64": "linux-arm64", "x86_64": "linux-x64"}[rpm_arch]


_ELECTRON_VERSION_RE = re.compile(rb"Electron/(\d+\.\d+\.\d+)")
_SEMVER_RE = re.compile(r"^(\d+\.\d+\.\d+)")


def _semver(value: object) -> str | None:
    if isinstance(value, (int, float)):
        value = str(value)
    if not isinstance(value, str):
        return None
    match = _SEMVER_RE.match(value.strip())
    return match.group(1) if match else None


def parse_plist_version(plist: Path) -> str | None:
    """Read CFBundleShortVersionString from XML or binary Info.plist."""
    data = plist.read_bytes()
    parsed: object | None = None
    try:
        parsed = plistlib.loads(data)
    except Exception:
        parsed = None
    if isinstance(parsed, dict):
        for key in ("CFBundleShortVersionString", "CFBundleVersion"):
            version = _semver(parsed.get(key))
            if version:
                return version
    text = data.decode("utf-8", "replace")
    match = re.search(
        r"<key>CFBundleShortVersionString</key>\s*<string>([0-9.]+)</string>",
        text,
    )
    if match:
        return _semver(match.group(1))
    match = re.search(r"<key>CFBundleVersion</key>\s*<string>([0-9.]+)</string>", text)
    if match:
        return _semver(match.group(1))
    return None


def _electron_version_in_file(path: Path) -> str | None:
    """Scan a Mach-O / blob for an embedded Electron/X.Y.Z ident."""
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size <= 0:
        return None
    with path.open("rb") as fh:
        prev = b""
        while True:
            chunk = fh.read(1 << 20)
            if not chunk:
                break
            buf = prev + chunk
            match = _ELECTRON_VERSION_RE.search(buf)
            if match:
                return match.group(1).decode()
            prev = buf[-24:]
    return None


def parse_electron_framework_version(extracted_dmg: Path) -> str:
    hits = list(extracted_dmg.rglob("Electron Framework.framework/**/Info.plist"))
    hits.sort(key=lambda p: (0 if p.parent.name == "Resources" else 1, len(str(p))))
    for plist in hits:
        version = parse_plist_version(plist)
        if version:
            print(f"  Electron {version} (from {plist.relative_to(extracted_dmg)})")
            return version

    binaries = [
        p
        for p in extracted_dmg.rglob("Electron Framework.framework/**/Electron Framework")
        if p.is_file()
    ]
    for binary in binaries:
        version = _electron_version_in_file(binary)
        if version:
            print(f"  Electron {version} (from {binary.relative_to(extracted_dmg)})")
            return version

    raise SystemExit(
        "Could not determine Electron version from the DMG "
        "(no CFBundleShortVersionString / Electron/X.Y.Z ident)"
    )


def extract_png_from_icns(icns: Path, dest: Path) -> bool:
    data = icns.read_bytes()
    if data[:4] != b"icns":
        return False
    best: bytes | None = None
    i = 8
    while i + 8 <= len(data):
        size = int.from_bytes(data[i + 4 : i + 8], "big")
        if size <= 8:
            break
        blob = data[i + 8 : i + size]
        if blob[:8] == b"\x89PNG\r\n\x1a\n" and (best is None or len(blob) > len(best)):
            best = blob
        i += size
    if not best:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(best)
    return True


def compile_napi_stub(headers: Path, dest: Path, cc: str) -> None:
    cands = list(headers.rglob("node_api.h"))
    if not cands:
        raise SystemExit("node_api.h missing from Electron headers")
    include = cands[0].parent
    src = REPO / "packaging" / "napi-stub.c"
    dest.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            cc,
            "-shared",
            "-fPIC",
            "-O2",
            "-DNAPI_VERSION=8",
            f"-I{include}",
            "-o",
            str(dest),
            str(src),
        ]
    )


def electron_abi(electron_version: str) -> str:
    """Map an Electron version (e.g. 42.1.0) to NODE_MODULE_VERSION."""
    registry: list[dict] = []
    try:
        data = http_json(NODE_ABI_REGISTRY)
        if isinstance(data, list):
            registry = data
    except Exception as exc:
        print(f"warning: node-abi registry fetch failed ({exc})")

    major = electron_version.split(".")[0]
    for row in registry:
        if row.get("runtime") == "electron" and str(row.get("target")) == electron_version:
            return str(row["abi"])
    for row in reversed(registry):
        if row.get("runtime") == "electron" and str(row.get("target", "")).split(".")[0] == major:
            return str(row["abi"])
    if major in ELECTRON_ABI_FALLBACK:
        return ELECTRON_ABI_FALLBACK[major]
    raise SystemExit(f"No node-abi entry for Electron {electron_version}")


def pick_better_sqlite_asset(electron_version: str, rpm_arch: str) -> tuple[str, str]:
    """Return (tag, asset_url) for a linux prebuild matching this Electron."""
    abi = electron_abi(electron_version)
    e_arch = electron_arch(rpm_arch)
    needle = f"electron-v{abi}-linux-{e_arch}"
    releases = http_json(
        BETTER_SQLITE_RELEASES + "?per_page=20",
        accept="application/vnd.github+json",
    )
    if isinstance(releases, dict):
        raise SystemExit(f"Unexpected GitHub API payload: {releases}")
    for rel in releases:
        for asset in rel.get("assets", []):
            name = asset.get("name", "")
            if needle in name and name.endswith(".tar.gz"):
                return rel["tag_name"], asset["browser_download_url"]
    raise SystemExit(f"No better-sqlite3 asset matching {needle}")


def stage_electron(electron_dir: Path, payload: Path) -> None:
    payload.mkdir(parents=True, exist_ok=True)
    for item in electron_dir.iterdir():
        dest = payload / item.name
        if item.name == "resources":
            dest.mkdir(exist_ok=True)
            for res in item.iterdir():
                if res.name == "default_app.asar":
                    continue
                target = dest / res.name
                if res.is_dir():
                    shutil.copytree(res, target, dirs_exist_ok=True)
                else:
                    shutil.copy2(res, target)
            continue
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dest)
    electron_bin = payload / "electron"
    electron_bin.chmod(electron_bin.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def find_asar(extracted_dmg: Path) -> tuple[Path, Path | None]:
    asars = [p for p in extracted_dmg.rglob("app.asar") if p.is_file()]
    if not asars:
        raise SystemExit("app.asar not found in DMG")
    asar = asars[0]
    unpacked = asar.with_name("app.asar.unpacked")
    return asar, unpacked if unpacked.is_dir() else None


def extract_asar(asar: Path, unpacked: Path | None, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    work = dest.parent / "asar-in"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    shutil.copy2(asar, work / "app.asar")
    if unpacked:
        shutil.copytree(unpacked, work / "app.asar.unpacked", dirs_exist_ok=True)
    npx = shutil.which("npx")
    try:
        if npx:
            run(["npx", "--yes", "@electron/asar", "extract", str(work / "app.asar"), str(dest)])
            return
    except Exception as exc:
        print(f"asar extract via npx failed ({exc}); falling back to 7z")
    seven = which_or_die("7z", "7zz")
    run([seven, "x", "-y", f"-o{dest}", str(asar)])
    if unpacked:
        shutil.copytree(unpacked, dest, dirs_exist_ok=True)


def install_natives(
    app_root: Path,
    cursor_natives: dict[str, Path],
    stub: Path | None,
    sqlite_node: Path | None,
    rpm_arch: str,
) -> None:
    napi = napi_triple(rpm_arch)
    e_arch = electron_arch(rpm_arch)

    dests = {
        "tree-chunk-napi": app_root
        / "dist/deps/@anysphere/tree-chunk-napi"
        / f"tree-chunk-napi.linux-{napi}-gnu.node",
        "cursor-proclist": app_root / "dist/deps/cursor-proclist/build/Release/cursor_proclist.node",
        "tree-sitter": app_root / "dist/deps/tree-sitter/build/Release/tree_sitter_runtime_binding.node",
        "tree-sitter-bash": app_root / "dist/deps/tree-sitter-bash/build/Release/tree_sitter_bash_binding.node",
        "whichlang": app_root / "dist/deps/whichlang-node" / f"whichlang-node.linux-{napi}-gnu.node",
    }

    def copy(src: Path, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        dest.chmod(0o755)
        print(f"  installed {dest.relative_to(app_root)}")

    for key, dest in dests.items():
        src = cursor_natives.get(key)
        if src:
            copy(src, dest)
            if key == "tree-sitter-bash":
                copy(
                    src,
                    app_root / f"dist/deps/tree-sitter-bash/prebuilds/linux-{e_arch}/tree-sitter-bash.node",
                )
        elif stub:
            copy(stub, dest)
            print(f"  stubbed {key}")
        else:
            raise SystemExit(f"missing native {key} and no N-API stub was built")

    if sqlite_node:
        copy(sqlite_node, app_root / "dist/deps/better-sqlite3/build/Release/better_sqlite3.node")

    helper_stub = REPO / "packaging" / "helper-stub.sh"
    native_dir = app_root / "dist/native"
    native_dir.mkdir(parents=True, exist_ok=True)
    for helper in ("sand-op-launcher", "sand-webauthn-signer"):
        dest = native_dir / helper
        shutil.copy2(helper_stub, dest)
        dest.chmod(0o755)


def strip_foreign_binaries(app_root: Path) -> None:
    """Remove Mach-O / PE leftovers so dlopen cannot pick them up."""
    for path in app_root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in {".node", ".dylib"} and not path.name.startswith("sand-"):
            continue
        try:
            head = path.read_bytes()[:4]
        except OSError:
            continue
        if head in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"MZ\x90\x00") or head[:2] == b"MZ":
            print(f"  removing foreign binary {path.relative_to(app_root)}")
            path.unlink()


def write_metadata(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def rpmbuild_payload(
    payload: Path, meta: dict, outdir: Path, rpm_arch: str, icon: Path | None
) -> Path:
    spec = REPO / "packaging" / "grok-bot.spec"
    wrapper = REPO / "packaging" / "grok-bot-wrapper.sh"
    desktop = REPO / "packaging" / "grok-bot.desktop"
    topdir = outdir / "rpmbuild"
    for sub in ("BUILD", "RPMS", "SOURCES", "SPECS", "SRPMS", "BUILDROOT"):
        (topdir / sub).mkdir(parents=True, exist_ok=True)

    defines = [
        "-D",
        f"_topdir {topdir}",
        "-D",
        f"grokbot_version {meta['grokbot_version']}",
        "-D",
        f"grokbot_release {meta.get('release', '1')}",
        "-D",
        f"payload_dir {payload}",
        "-D",
        f"wrapper {wrapper}",
        "-D",
        f"desktop {desktop}",
        "-D",
        f"_arch {rpm_arch}",
        "-D",
        f"_target_cpu {rpm_arch}",
    ]
    if icon and icon.exists():
        defines.extend(["-D", f"icon {icon}", "-D", "has_icon 1"])
    else:
        defines.extend(["-D", "has_icon 0"])

    run(["rpmbuild", "-bb", *defines, str(spec)])
    rpms = list((topdir / "RPMS").rglob("*.rpm"))
    if not rpms:
        raise SystemExit("rpmbuild produced no RPM")
    dest = outdir / rpms[0].name
    shutil.copy2(rpms[0], dest)
    print(f"RPM {dest}")
    return dest


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--arch", choices=("aarch64", "x86_64"), default=os.uname().machine)
    p.add_argument("--grokbot-version", default=None)
    p.add_argument("--cursor-rpm-url", default=None)
    p.add_argument("--out", type=Path, default=REPO / "dist")
    p.add_argument("--cache", type=Path, default=REPO / "downloads")
    p.add_argument("--skip-rpm", action="store_true")
    p.add_argument("--release", default="1")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.arch != os.uname().machine:
        print(
            f"warning: building --arch {args.arch} on {os.uname().machine}; "
            "native addons must match the RPM arch",
            file=sys.stderr,
        )

    cache: Path = args.cache
    work = args.out / "work"
    payload = args.out / "payload"
    cache.mkdir(parents=True, exist_ok=True)
    if payload.exists():
        shutil.rmtree(payload)
    payload.mkdir(parents=True)
    work.mkdir(parents=True, exist_ok=True)

    grok_ver = detect_grokbot_version(args.grokbot_version)
    print(f"Grok Bot {grok_ver}")

    cursor = detect_cursor(cursor_platform(args.arch))
    rpm_url = args.cursor_rpm_url or cursor["rpmUrl"]
    if not rpm_url:
        raise SystemExit("No Cursor RPM URL (pass --cursor-rpm-url)")
    print(f"Cursor {cursor.get('version')} RPM {rpm_url}")

    dmg = download(GROKBOT_DMG.format(version=grok_ver), cache / f"Grok_Bot_{grok_ver}.dmg")
    dmg_dir = work / "dmg"
    if dmg_dir.exists():
        shutil.rmtree(dmg_dir)
    extract_archive(dmg, dmg_dir)

    electron_ver = parse_electron_framework_version(dmg_dir)
    print(f"Electron {electron_ver}")

    ez = download(
        ELECTRON_ZIP.format(version=electron_ver, e_arch=electron_arch(args.arch)),
        cache / f"electron-v{electron_ver}-linux-{electron_arch(args.arch)}.zip",
    )
    e_dir = work / "electron"
    if e_dir.exists():
        shutil.rmtree(e_dir)
    extract_archive(ez, e_dir)
    stage_electron(e_dir, payload)

    cursor_rpm = download(rpm_url, cache / Path(rpm_url.split("?", 1)[0]).name)
    cursor_root = work / "cursor-rpm"
    if cursor_root.exists():
        shutil.rmtree(cursor_root)
    extract_archive(cursor_rpm, cursor_root)
    natives = extract_natives(cursor_root, args.arch)
    need_stub = any(key not in natives for key in CURSOR_NATIVE_KEYS)
    stub_path: Path | None = None
    if need_stub:
        headers_tar = download(
            ELECTRON_HEADERS.format(version=electron_ver),
            cache / f"electron-headers-{electron_ver}.tar.gz",
        )
        headers_dir = work / "headers"
        if headers_dir.exists():
            shutil.rmtree(headers_dir)
        extract_archive(headers_tar, headers_dir)
        stub_path = work / "napi-stub.node"
        cc = which_or_die("gcc", "cc")
        compile_napi_stub(headers_dir, stub_path, cc)

    tag, sqlite_url = pick_better_sqlite_asset(electron_ver, args.arch)
    sqlite_tar = download(sqlite_url, cache / Path(sqlite_url.split("?", 1)[0]).name)
    sqlite_dir = work / "better-sqlite3"
    if sqlite_dir.exists():
        shutil.rmtree(sqlite_dir)
    extract_archive(sqlite_tar, sqlite_dir)
    sqlite_nodes = list(sqlite_dir.rglob("better_sqlite3.node"))
    if not sqlite_nodes:
        raise SystemExit("better_sqlite3.node missing from prebuild tarball")

    asar, unpacked = find_asar(dmg_dir)
    app_dir = payload / "resources" / "app"
    extract_asar(asar, unpacked, app_dir)
    if unpacked:
        shutil.copytree(unpacked, app_dir, dirs_exist_ok=True)

    install_natives(app_dir, natives, stub_path, sqlite_nodes[0], args.arch)
    strip_foreign_binaries(app_dir)

    icon_out = args.out / "grok-bot.png"
    icns = list(dmg_dir.rglob("icon.icns"))
    has_icon = bool(icns) and extract_png_from_icns(icns[0], icon_out)
    if has_icon:
        shutil.copy2(icon_out, payload / "grok-bot.png")

    meta = {
        "grokbot_version": grok_ver,
        "electron_version": electron_ver,
        "cursor_version": cursor.get("version"),
        "cursor_rpm": rpm_url,
        "better_sqlite3": tag,
        "arch": args.arch,
        "release": args.release,
    }
    write_metadata(args.out / "metadata.json", meta)
    print(json.dumps(meta, indent=2))

    if args.skip_rpm:
        print(f"staged payload at {payload}")
        return 0

    rpmbuild_payload(payload, meta, args.out, args.arch, icon_out if has_icon else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
