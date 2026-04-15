#!/bin/bash
# Setup script for the compression project on fortyfive HPC.
# Run this on the LOGIN NODE (needs internet for pip installs).
#
# Usage: bash slurm/setup_env.sh

source /etc/profile
set -e

module load python/3.11.11

VENV_DIR="$HOME/venvs/compression"

if [ -d "$VENV_DIR" ]; then
    echo "Venv already exists at $VENV_DIR"
    echo "To recreate: rm -rf $VENV_DIR && bash slurm/setup_env.sh"
    source "$VENV_DIR/bin/activate"
else
    echo "Creating venv at $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
    source "$VENV_DIR/bin/activate"
    pip install --upgrade pip
fi

echo "Installing dependencies..."
pip install aiohttp pyyaml python-dotenv tqdm transformers tokenizers sentencepiece
pip install torch --index-url https://download.pytorch.org/whl/cu124

echo ""
echo "Done. Venv ready at $VENV_DIR"
echo "Python: $(python3 --version)"
echo "Activate with: source $VENV_DIR/bin/activate"
