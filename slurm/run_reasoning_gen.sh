#!/bin/bash
# Run UGF reasoning trace generation on fortyfive login node inside tmux.
# Same as parallel gen — runs on login node for internet access.
#
# Usage:
#   tmux new -s compression-reasoning  (or reuse existing session)
#   bash slurm/run_reasoning_gen.sh
#   # Ctrl-B D to detach

source /etc/profile
set -e

module load python/3.11.11
source "$HOME/venvs/compression/bin/activate"

cd "$HOME/compression"

echo "Starting UGF reasoning trace generation..."
echo "Log: logs/reasoning_generation.log"
echo ""

python3 corpus/generation/generate_reasoning.py 2>&1 | tee logs/reasoning_generation.log
