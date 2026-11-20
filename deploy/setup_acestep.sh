#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
command -v uv >/dev/null || { echo "Install uv from its official instructions first."; exit 1; }
command -v git >/dev/null || exit 1
cd "$PROJECT_ROOT"
mkdir -p modelsrc
if [ ! -d modelsrc/ACE-Step-1.5/.git ]; then
  git clone https://github.com/ace-step/ACE-Step-1.5.git modelsrc/ACE-Step-1.5
fi
cd modelsrc/ACE-Step-1.5
uv sync
git rev-parse HEAD > ../../modelsrc/acestep-revision.txt
printf '%s\n' 'Installed. Run bash deploy/start_acestep.sh from the MusicCraft project root.'
