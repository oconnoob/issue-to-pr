#!/usr/bin/env bash
set -euo pipefail
: "${1:?Usage: scripts/probe-sandbox.sh SESSION_ID}"
if [[ -n "${DOCTL_CONTEXT:-}" ]]; then
  exec doctl --context "$DOCTL_CONTEXT" harness-runtime exec "$1" -- sh -c \
    'for tool in git python3 curl gh; do command -v "$tool" || true; done'
fi
exec doctl harness-runtime exec "$1" -- sh -c \
  'for tool in git python3 curl gh; do command -v "$tool" || true; done'
