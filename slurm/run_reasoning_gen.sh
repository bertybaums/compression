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

source "$HOME/venvs/compression/bin/activate"

cd "$HOME/compression"

TS=$(date +%Y%m%d_%H%M%S)
LOG="logs/reasoning_generation_${TS}.log"
mkdir -p logs

echo "Starting UGF reasoning trace generation..."
echo "Log: $LOG"
echo "(symlink: logs/reasoning_generation_latest.log -> $LOG)"
ln -sfn "$(basename "$LOG")" logs/reasoning_generation_latest.log
echo ""

python3 corpus/generation/generate_reasoning.py "$@" 2>&1 | tee "$LOG"
