#!/usr/bin/env bash
set -euo pipefail
: "${GITHUB_ACTOR:?Set GITHUB_ACTOR (for example demo-user)}"
if [[ -n "${DOCTL_CONTEXT:-}" ]]; then
  exec doctl --context "$DOCTL_CONTEXT" harness-runtime connections create --actor "$GITHUB_ACTOR"
fi
exec doctl harness-runtime connections create --actor "$GITHUB_ACTOR"
