#!/bin/bash
# Run parallel corpus generation on fortyfive login node inside tmux.
# This is NOT a SLURM job — it runs on the login node because it needs
# internet access for MindRouter API calls.
#
# Usage:
#   tmux new -s compression
#   bash slurm/run_parallel_gen.sh
#   # Then Ctrl-B D to detach. Reattach with: tmux attach -t compression
#
# Check progress:
#   python3 -c "import json; print(json.dumps(json.load(open('corpus/processed/parallel_progress.json'))['stats'], indent=2))"

source /etc/profile
set -e

module load python/3.11.11
source "$HOME/venvs/compression/bin/activate"

cd "$HOME/compression"

echo "Starting parallel corpus generation..."
echo "Passages to translate: $(wc -l < corpus/processed/english_passages.jsonl)"
echo "Already completed: $(python3 -c "import json,pathlib; p=pathlib.Path('corpus/processed/parallel_progress.json'); print(len(json.load(open(p)).get('completed_ids',[])) if p.exists() else 0)")"
echo ""
echo "Log: logs/parallel_generation.log"
echo "Press Ctrl-C to stop (progress is saved, will resume on restart)"
echo ""

python3 corpus/generation/generate_parallel.py 2>&1 | tee logs/parallel_generation.log
