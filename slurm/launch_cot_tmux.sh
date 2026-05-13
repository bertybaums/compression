#!/bin/bash
# Launch UGF chain-of-thought generation in a tmux session on the fortyfive
# login node. Matches the established launch pattern from
# generate_reasoning.py (MR is reachable only from inside the campus
# network; the login node has internet; SLURM compute nodes do not).
#
# Resume-safe: kill+relaunch picks up where it left off via
# corpus/processed/cot_progress.json.

set -e

TS=$(date +%Y%m%d_%H%M%S)
LOG="logs/cot_gen_${TS}.log"

# Optional env overrides. Default 50K logic + 50K philosophy = 100K total.
LOGIC_N=${LOGIC_N:-50000}
PHILOSOPHY_N=${PHILOSOPHY_N:-50000}
PHILOSOPHY_TOPICS=${PHILOSOPHY_TOPICS:-corpus/processed/english_passages.jsonl}

mkdir -p logs corpus/processed

# Kill any prior session of the same name.
tmux kill-session -t cot 2>/dev/null || true

tmux new-session -d -s cot "
source ~/venvs/compression/bin/activate &&
cd ~/compression &&
ln -sfn cot_gen_${TS}.log logs/cot_gen_latest.log &&
python3 -u corpus/generation/generate_cot.py \
    --logic-n $LOGIC_N \
    --philosophy-n $PHILOSOPHY_N \
    --philosophy-topics $PHILOSOPHY_TOPICS \
    --output corpus/processed/ugf_cot.jsonl \
    --progress corpus/processed/cot_progress.json 2>&1 | tee $LOG
"

sleep 3
if tmux has-session -t cot 2>/dev/null; then
    echo "tmux session 'cot' is up. Log: $LOG (also: logs/cot_gen_latest.log)"
    echo "Monitor:   tmux attach -t cot         # or"
    echo "           tmux capture-pane -t cot -p -S -200"
    echo "           tail -f $LOG"
else
    echo "tmux session 'cot' failed to launch — check $LOG"
    exit 1
fi
