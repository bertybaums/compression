#!/bin/bash
#SBATCH --job-name=ugf-cx-patched
#SBATCH --partition=gpu-8
#SBATCH --exclude=n113,n118,n121,n122
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=0-01:00:00
#SBATCH --output=logs/%j_cx_patched.out
#SBATCH --error=logs/%j_cx_patched.err

# Re-run the SFT Reasoner on the 50-item counterexample_analysis subset
# of the holdout, with the truncation bug fixed (full definitions
# restored from cx-bot via eval/patch_holdout_definitions.py).
#
# Skips Translator(En->UGF) because the patched topics are in the same
# corpus-prompt format the holdout used.

source /etc/profile
set -e

source ~/venvs/compression/bin/activate

cd ~/compression

echo "Job $SLURM_JOB_ID starting on $(hostname)"
echo "GPU: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader)"

TS=$(date +%Y%m%d_%H%M%S)
OUT="eval/results/holdout_cx_patched_reasoner_${TS}.jsonl"

python3 -u -m eval.run_logic_bench \
    --bench eval/sets/holdout_bench_cx_patched.jsonl \
    --reasoner checkpoints/reasoner_sft_v1/final.pt \
    --translator checkpoints/translator/best \
    --skip-translate-en2ugf \
    --out "$OUT"

echo "Done. Output: $OUT"
ls -la "$OUT"
