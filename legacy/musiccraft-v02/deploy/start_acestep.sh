#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT/modelsrc/ACE-Step-1.5"
export ACESTEP_API_HOST="${ACESTEP_API_HOST:-127.0.0.1}"
export ACESTEP_API_PORT="${ACESTEP_API_PORT:-8001}"
# No concurrent models required; start one service at a time on smaller GPUs.
exec uv run acestep-api
