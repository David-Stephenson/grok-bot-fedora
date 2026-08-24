#!/usr/bin/env python3
"""Detect published Grok Bot and Cursor versions."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

GROKBOT_DMG = (
    "https://downloads.cursor.com/grokbot/stable/darwin-arm64/"
    "{version}/Grok_Bot_{version}.dmg"
)
CURSOR_API = "https://www.cursor.com/api/download?platform={platform}&releaseTrack=stable"


def _headers(*, accept: str = "*/*", github: bool = False) -> dict[str, str]:
    headers = {"User-Agent": USER_AGENT, "Accept": accept}
    if github:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
    return headers


def http_json(url: str, *, accept: str = "application/json") -> Any:
    github = "api.github.com" in url
    req = urllib.request.Request(url, headers=_headers(accept=accept, github=github))
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def http_text(url: str) -> str:
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", "replace")


def http_head_ok(url: str) -> bool:
    req = urllib.request.Request(url, method="HEAD", headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return 200 <= resp.status < 400
    except urllib.error.HTTPError as exc:
        # Some CDNs reject HEAD; a ranged GET still proves the object exists.
        if exc.code in (403, 405):
            return http_range_ok(url)
        return False
    except urllib.error.URLError:
        return False


def http_range_ok(url: str) -> bool:
    headers = _headers()
    headers["Range"] = "bytes=0-0"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status in (200, 206)
    except urllib.error.HTTPError:
        return False
    except urllib.error.URLError:
        return False


def scrape_grokbot_version() -> str | None:
    """Pull Grok_Bot_X.Y.Z.dmg out of the public marketing pages."""
    for url in ("https://x.ai/bot", "https://cursor.com/bot/onboarding"):
        try:
            html = http_text(url)
        except urllib.error.URLError:
            continue
        match = re.search(r"Grok_Bot_(\d+\.\d+\.\d+)\.dmg", html)
        if match:
            return match.group(1)
        match = re.search(r"darwin-arm64/(\d+\.\d+\.\d+)/Grok_Bot_", html)
        if match:
            return match.group(1)
    return None


def probe_grokbot_version(floor: str = "0.24.0") -> str | None:
    """Walk recent 0.N.P versions on the CDN when HTML scraping is blocked."""
    major, minor, patch = (int(p) for p in floor.split("."))
    found: str | None = None
    for m in range(minor, minor + 12):
        for p in range(0, 12):
            version = f"{major}.{m}.{p}"
            if http_head_ok(GROKBOT_DMG.format(version=version)):
                found = version
    return found


def detect_grokbot_version(override: str | None = None) -> str:
    if override:
        return override
    env = os.environ.get("GROKBOT_VERSION")
    if env:
        return env
    scraped = scrape_grokbot_version()
    if scraped:
        return scraped
    probed = probe_grokbot_version()
    if probed:
        return probed
    raise SystemExit("Could not detect a Grok Bot version. Pass --grokbot-version.")


def detect_cursor(platform: str, override: str | None = None) -> dict[str, Any]:
    """platform is linux-arm64 or linux-x64."""
    if override:
        return {"version": override, "rpmUrl": None}
    data = http_json(CURSOR_API.format(platform=platform))
    if not data.get("rpmUrl"):
        raise SystemExit(f"Cursor API for {platform} did not return rpmUrl: {data}")
    return data


def github_release_assets(tag: str) -> list[str] | None:
    """Asset names for an existing GitHub release, or None if the tag is absent."""
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        return None
    url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    req = urllib.request.Request(url, headers=_headers(accept="application/vnd.github+json", github=True))
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    return [asset["name"] for asset in data.get("assets", [])]


if __name__ == "__main__":
    print(detect_grokbot_version())
