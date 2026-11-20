#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
export SEED_VC_DIR="$PROJECT_ROOT/modelsrc/seed-vc"
export SEED_VC_PYTHON="$PROJECT_ROOT/.venvs/seed/bin/python"
export DEMUCS_PYTHON="$PROJECT_ROOT/.venvs/demucs/bin/python"
export VOICE_HOST="${VOICE_HOST:-127.0.0.1}"
export VOICE_PORT="${VOICE_PORT:-8010}"
exec "$SEED_VC_PYTHON" -B -m workers.voice_server
