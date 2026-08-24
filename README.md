# Unofficial Grok Bot Fedora RPMs

GitHub Actions in this repo watch for new **Grok Bot** desktop releases, pull
the matching **Cursor** Linux RPM for native Node addons, wrap everything in
official Electron for Linux, and publish an RPM.

This is **not** an official xAI / Anysphere / Cursor build. Use it at your own
risk.

## What the workflow does

On a daily schedule (and on manual dispatch):

1. Detect the current Grok Bot version from [x.ai/bot](https://x.ai/bot) (or
   probe the Cursor CDN).
2. Skip an architecture if GitHub already has `grok-bot-{version}-*.{arch}.rpm`
   unless you tick **force**.
3. In a Fedora container, for `x86_64` and `aarch64`:
   - Download the macOS DMG (the `app.asar` is arch-independent JavaScript).
   - Download Electron for Linux at the version baked into that DMG.
   - Download the Cursor Linux RPM for this arch and copy:
     `tree-chunk-napi`, `cursor-proclist`, `tree-sitter`, `tree-sitter-bash`,
     `whichlang`.
   - Fetch a `better-sqlite3` prebuild that matches Electron's ABI (Cursor's
     copy is built for a different Electron).
   - Stub `sand-op-launcher` / `sand-webauthn-signer` (Darwin-only helpers;
     passkeys will not work).
   - `rpmbuild` an RPM that installs to `/usr/libexec/grok-bot`.
4. Attach both RPMs to a GitHub release tagged `v{version}`.

## Install

From a [release](../../releases):

```bash
sudo dnf install ./grok-bot-*-$(uname -m).rpm
```

`chrome-sandbox` is installed setuid root. If you unpack the payload by hand,
pass `--no-sandbox` (the `/usr/bin/grok-bot` wrapper does this automatically
when the sandbox is not setuid).

## Build locally

Needs: `python3`, `rpm-build`, `rpm2cpio`, `cpio`, `unzip`, `7z`, `gcc`,
`npx` (for `@electron/asar`).

```bash
python3 scripts/build.py --arch "$(uname -m)"
```

Useful flags:

- `--grokbot-version 0.24.0` — pin the app version
- `--skip-rpm` — stage `dist/payload` without running `rpmbuild`
- `--cursor-rpm-url URL` — override the Cursor RPM (CI uses the download API)

## Publish this repo to GitHub

Scripts only — no DMGs or RPMs in git.

```bash
cd grok-bot-fedora
git init
git add .
git commit -m "Initial unofficial Grok Bot Fedora RPM packager."
gh repo create grok-bot-fedora --public --source=. --remote=origin --push
```

Then enable Actions on the repo and run **Build unofficial Grok Bot RPM** once
by hand (or wait for the daily cron).

## Layout

```
.github/workflows/build-rpm.yml   # schedule + matrix + release
scripts/detect.py                 # version scrape / Cursor API
scripts/ci_plan.py                # skip if RPMs already exist
scripts/fetch.py                  # download + extract
scripts/natives.py                # find .node files in the Cursor RPM
scripts/build.py                  # orchestrator
packaging/grok-bot.spec
packaging/grok-bot-wrapper.sh
```

Git tracks **scripts only**. DMGs, Electron zips, Cursor RPMs, and built RPMs
stay in `downloads/` / `dist/` and are gitignored.
