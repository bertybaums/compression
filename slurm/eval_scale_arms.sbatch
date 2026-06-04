#!/bin/bash
#SBATCH --job-name=scale-eval
#SBATCH --partition=gpu-8
#SBATCH --exclude=n113,n118,n121,n122
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=06:00:00
#SBATCH --output=logs/%j_scale_eval.out
#SBATCH --error=logs/%j_scale_eval.err

# Eval the 3 scale-study sizes (52M / 200M=v1 / 1B) on the 3 benches.
# docs/scale-study-design-2026-06-03.md. All UGF vocab (run_sft_v2_bench default).
# Matched anti-rep decode. Outputs eval/results/scale_<arm>_<bench>_<TS>.jsonl
# for blinded isolation judging downstream.

source /etc/profile
set -e
source ~/venvs/compression/bin/activate
cd ~/compression

TS=$(date +%Y%m%d_%H%M%S)
DECODE="--repetition-penalty 1.2 --no-repeat-ngram-size 4 --temperature 0.8 --top-k 50 --top-p 0.9 --max-new-tokens 400"

echo "Job $SLURM_JOB_ID on $(hostname); TS=$TS"
nvidia-smi --query-gpu=name --format=csv,noheader

M50=checkpoints/reasoner_scale_50m_sft/final.pt
M200=checkpoints/reasoner_sft_v1/final.pt
M1B=checkpoints/reasoner_scale_1b_sft/final.pt

run () {  # arm ckpt benchname benchfile
  echo "=== $1 / $3 ==="
  python3 -u -m eval.run_sft_v2_bench --bench "$4" --reasoner "$2" \
      --out "eval/results/scale_${1}_${3}_${TS}.jsonl" $DECODE
}

for b in "stress:eval/sets/stress_bench.jsonl" \
         "holdout:eval/sets/holdout_bench.jsonl" \
         "cx_patched:eval/sets/holdout_bench_cx_patched.jsonl"; do
  bn=${b%%:*}; bf=${b##*:}
  run 50m  "$M50"  "$bn" "$bf"
  run 200m "$M200" "$bn" "$bf"
  run 1b   "$M1B"  "$bn" "$bf"
done

echo "ALL DONE scale eval; TS=$TS"
echo "outputs: eval/results/scale_*_${TS}.jsonl"
