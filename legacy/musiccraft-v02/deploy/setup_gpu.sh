#!/usr/bin/env bash
# Run ON a rented Ubuntu GPU machine. This script is not run by the local studio.
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${MUSICCRAFT_GPU_PYTHON:-python3.10}"
command -v "$PYTHON_BIN" >/dev/null || { echo "Install Python 3.10 and python3.10-venv first."; exit 1; }
command -v ffmpeg >/dev/null || { echo "Install ffmpeg first: sudo apt-get install ffmpeg"; exit 1; }
command -v git >/dev/null || { echo "Install git first."; exit 1; }
command -v nvidia-smi >/dev/null || { echo "An NVIDIA GPU and driver are required."; exit 1; }
cd "$PROJECT_ROOT"
mkdir -p modelsrc .venvs
if [ ! -d modelsrc/seed-vc/.git ]; then
  git clone https://github.com/Plachtaa/seed-vc.git modelsrc/seed-vc
fi
"$PYTHON_BIN" -m venv .venvs/seed
"$PYTHON_BIN" -m venv .venvs/demucs
.venvs/seed/bin/python -m pip install --upgrade pip
.venvs/demucs/bin/python -m pip install --upgrade pip
for venv in seed demucs; do
  ".venvs/$venv/bin/python" -m pip install torch==2.4.0 torchvision==0.19.0 torchaudio==2.4.0 --index-url https://download.pytorch.org/whl/cu121
done
# The upstream requirements contain conflicting nightly/stable Torch entries and GUI
# extras. Keep inference dependencies, using the explicit Torch set above.
"$PYTHON_BIN" - <<'PY'
from pathlib import Path
skip={"torch","torchvision","torchaudio","gradio","sounddevice","FreeSimpleGUI"}
rows=[]
for line in Path('modelsrc/seed-vc/requirements.txt').read_text().splitlines():
    if not line.strip() or line.startswith('#'):continue
    name=line.split('==')[0].split('>=')[0].split()[0]
    if name not in skip:rows.append(line)
Path('.venvs/seed-requirements.txt').write_text('\n'.join(rows)+'\n')
PY
.venvs/seed/bin/python -m pip install -r .venvs/seed-requirements.txt
.venvs/demucs/bin/python -m pip install 'numpy<2' demucs==4.0.1
SEED_REVISION="$(git -C modelsrc/seed-vc rev-parse HEAD)"
printf '%s\n' "$SEED_REVISION" > .venvs/seed-vc-revision.txt
.venvs/seed/bin/python -c 'import torch; assert torch.cuda.is_available(), "CUDA unavailable"; print(torch.cuda.get_device_name())'
printf '\n%s\n' 'Setup finished. Model weights download during first inference; allow time to warm up.'
printf '%s\n' 'Next: bash deploy/start_voice.sh'
