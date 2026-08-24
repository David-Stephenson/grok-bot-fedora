#!/usr/bin/bash
# Launch Grok Bot (unofficial Linux build). Prefer the RPM-installed
# chrome-sandbox when it is setuid root; otherwise Chromium will not start
# without --no-sandbox.
set -euo pipefail

ROOT="/usr/libexec/grok-bot"
ELECTRON="${ROOT}/electron"
SANDBOX="${ROOT}/chrome-sandbox"

export ELECTRON_OZONE_PLATFORM_HINT="${ELECTRON_OZONE_PLATFORM_HINT:-auto}"

extra=()
if [[ ! -u "${SANDBOX}" ]]; then
  extra+=(--no-sandbox)
fi

exec "${ELECTRON}" "${extra[@]}" "${ROOT}/resources/app" "$@"
