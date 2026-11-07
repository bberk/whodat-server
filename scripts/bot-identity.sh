#!/usr/bin/env bash
# Backwards-compatibility wrapper for scripts/agent-identity.sh.
# Forwards all arguments directly to scripts/agent-identity.sh.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
exec "$here/agent-identity.sh" "$@"
