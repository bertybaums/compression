#!/bin/bash
# One-time setup for the structured-output Translator experiment.
# Run this on the fortyfive LOGIN NODE (has internet); the compute node does not.
#
# Creates ~/venvs/structured-translator, installs deps, and pre-downloads
# the base model weights so the SLURM job can run offline.

source /etc/profile
set -e

VENV=$HOME/venvs/structured-translator
MODEL="${MODEL:-openai/gpt-oss-20b}"

if [ ! -d "$VENV" ]; then
    echo "Creating venv at $VENV..."
    python3 -m venv "$VENV"
fi

source "$VENV/bin/activate"

pip install --upgrade pip

# PyTorch with CUDA 12.4 (matches cluster CUDA install per CLAUDE.md).
pip install --index-url https://download.pytorch.org/whl/cu124 \
    torch torchvision torchaudio

# Transformers stack. accelerate is needed for device_map="auto".
pip install \
    "transformers>=4.45" \
    accelerate \
    safetensors \
    sentencepiece \
    tokenizers \
    huggingface_hub \
    tiktoken

echo
echo "Pre-downloading $MODEL to $HOME/.cache/huggingface ..."
python3 - <<EOF
from huggingface_hub import snapshot_download
path = snapshot_download(repo_id="$MODEL")
print(f"Downloaded to: {path}")
EOF

echo
echo "Setup complete. To submit the benchmark:"
echo "  cd ~/compression && sbatch slurm/run_structured_translator_bench.sbatch"
