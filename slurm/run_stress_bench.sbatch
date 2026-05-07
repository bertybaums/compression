#!/bin/bash
#SBATCH --job-name=ugf-stress-bench
#SBATCH --partition=gpu-8
#SBATCH --exclude=n113,n118,n121,n122
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=0-01:00:00
#SBATCH --output=logs/%j_stress_bench.out
#SBATCH --error=logs/%j_stress_bench.err

# Layer-4 stress benchmark on the SFT Reasoner. 30 hand-crafted UGF-hard
# prompts targeting concepts likely to test the vocabulary restriction's
# limits (modal, deontic, supervenience, use_mention, intensional,
# self_reference, vagueness, counterfactual, abstract, phenomenal).
#
# Uses --skip-translate-en2ugf because each item has a hand-translated
# ugf_query — bypasses Translator(En->UGF) noise on this stress set.

source /etc/profile
set -e

source ~/venvs/compression/bin/activate

cd ~/compression

echo "Job $SLURM_JOB_ID starting on $(hostname)"
echo "GPU: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader)"

TS=$(date +%Y%m%d_%H%M%S)
OUT="eval/results/stress_bench_reasoner_${TS}.jsonl"

python3 -u -m eval.run_logic_bench \
    --bench eval/sets/stress_bench.jsonl \
    --reasoner checkpoints/reasoner_sft_v1/final.pt \
    --translator checkpoints/translator/best \
    --skip-translate-en2ugf \
    --out "$OUT"

echo "Done. Output: $OUT"
ls -la "$OUT"
