#!/bin/bash
#SBATCH --job-name=ugf-rl-v3-bench
#SBATCH --partition=gpu-8
#SBATCH --exclude=n113,n118,n121,n122
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=01:00:00
#SBATCH --output=%j_rl_v3_bench.out
#SBATCH --error=%j_rl_v3_bench.err

# Generate RL-v3-final outputs on the 3 milestone benches, for the
# RL-final vs SFT-v2 head-to-head (pre-registered Step 3 of the RL eval).
# Same anti-rep decode the SFT-v2 milestone used: rep penalty 1.2, no-repeat 4-gram.

source /etc/profile
set -e
source ~/venvs/compression/bin/activate
cd ~/compression

echo "Job $SLURM_JOB_ID on $(hostname)"
echo "GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader)"

CKPT=checkpoints/reasoner_rl_v3/final.pt
TS=$(date +%Y%m%d_%H%M%S)
DECODE="--repetition-penalty 1.2 --no-repeat-ngram-size 4 --temperature 0.8 --top-k 50 --top-p 0.9"

run_bench () {
    local name=$1 bench=$2
    echo "=== $name ($bench) ==="
    python3 -u -m eval.run_sft_v2_bench \
        --bench "$bench" \
        --reasoner "$CKPT" \
        --out "eval/results/rl_v3_${name}_norep_${TS}.jsonl" \
        $DECODE
}

run_bench stress     eval/sets/stress_bench.jsonl
run_bench cx_patched eval/sets/holdout_bench_cx_patched.jsonl
run_bench holdout    eval/sets/holdout_bench.jsonl

echo "ALL DONE. TS=${TS}"
mv ${SLURM_JOB_ID}_rl_v3_bench.out logs/ 2>/dev/null || true
mv ${SLURM_JOB_ID}_rl_v3_bench.err logs/ 2>/dev/null || true
