#!/bin/bash
#SBATCH --job-name=ugf-ckpt-bench
#SBATCH --partition=gpu-8
#SBATCH --exclude=n113,n118,n121,n122
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=01:00:00
#SBATCH --output=%j_ckpt_bench.out
#SBATCH --error=%j_ckpt_bench.err

# Generate a checkpoint's outputs on the 3 milestone benches, for a blinded
# head-to-head vs SFT-v2. Parameterized via env vars so any checkpoint (DPO,
# Stage-2 GRPO, ...) reuses it:
#   sbatch --export=ALL,CKPT=checkpoints/reasoner_dpo_v1/final.pt,TAG=dpo slurm/eval_ckpt_bench.sbatch
# Defaults target the Stage-1 DPO checkpoint. Same anti-rep decode as v3.

source /etc/profile
set -e
source ~/venvs/compression/bin/activate
cd ~/compression

CKPT=${CKPT:-checkpoints/reasoner_dpo_v1/final.pt}
TAG=${TAG:-dpo}
TS=$(date +%Y%m%d_%H%M%S)
DECODE="--repetition-penalty 1.2 --no-repeat-ngram-size 4 --temperature 0.8 --top-k 50 --top-p 0.9"

echo "Job $SLURM_JOB_ID on $(hostname); CKPT=$CKPT TAG=$TAG TS=$TS"
echo "GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader)"

run_bench () {
    echo "=== $1 ==="
    python3 -u -m eval.run_sft_v2_bench \
        --bench "$2" --reasoner "$CKPT" \
        --out "eval/results/${TAG}_${1}_norep_${TS}.jsonl" $DECODE
}

run_bench stress     eval/sets/stress_bench.jsonl
run_bench cx_patched eval/sets/holdout_bench_cx_patched.jsonl
run_bench holdout    eval/sets/holdout_bench.jsonl

echo "ALL DONE. TAG=$TAG TS=$TS"
mv ${SLURM_JOB_ID}_ckpt_bench.out logs/ 2>/dev/null || true
mv ${SLURM_JOB_ID}_ckpt_bench.err logs/ 2>/dev/null || true
