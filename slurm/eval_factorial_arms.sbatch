#!/bin/bash
#SBATCH --job-name=factorial-eval
#SBATCH --partition=gpu-8
#SBATCH --exclude=n113,n118,n121,n122
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=02:00:00
#SBATCH --output=logs/%j_factorial_eval.out
#SBATCH --error=logs/%j_factorial_eval.err

# Eval the form x prompt-diversity factorial arms on the 3 milestone benches.
# docs/form-retrain-clean-design-2026-06-03.md (THIRD AMENDMENT)
#
#   ARM A (essay, 380 prompts) -- already trained AND evaluated June 2 as the
#                                 enbase UGF arm: eval/results/enbase_ugf_n_*.
#                                 Not re-run here; reuse those results.
#   ARM B (form,  380 prompts) -- checkpoints/reasoner_form_n_sft/final.pt
#   ARM C (form,  diverse)     -- checkpoints/reasoner_formdiv_n_sft/final.pt
#
# Decode flags and bench files are copied verbatim from eval_baseline_arms.sbatch
# so ARM B/C results are directly comparable to ARM A's without re-running it.
# Arms are judged in isolation downstream (blinded), as with the enbase/scale runs.
#
# Usage:
#   sbatch slurm/eval_factorial_arms.sbatch B      # ARM B only (default)
#   sbatch slurm/eval_factorial_arms.sbatch C      # ARM C only
#   sbatch slurm/eval_factorial_arms.sbatch BC     # both

source /etc/profile
set -e
source ~/venvs/compression/bin/activate
cd ~/compression

ARMS="${1:-B}"
TS=$(date +%Y%m%d_%H%M%S)
DECODE="--repetition-penalty 1.2 --no-repeat-ngram-size 4 --temperature 0.8 --top-k 50 --top-p 0.9 --max-new-tokens 400"
VOCAB=wordlist/vocab_final.json     # UGF -- same vocab as ARM A

echo "Job $SLURM_JOB_ID on $(hostname); TS=$TS; ARMS=$ARMS"
nvidia-smi --query-gpu=name --format=csv,noheader

run () {  # arm ckpt benchname benchfile
  echo "=== $1 / $3 ==="
  python3 -u -m eval.run_sft_v2_bench --bench "$4" \
      --reasoner "$2" --vocab-path "$VOCAB" \
      --out "eval/results/factorial_${1}_${3}_${TS}.jsonl" $DECODE
}

for b in "stress:eval/sets/stress_bench.jsonl" \
         "holdout:eval/sets/holdout_bench.jsonl" \
         "cx_patched:eval/sets/holdout_bench_cx_patched.jsonl"; do
  bn=${b%%:*}; bf=${b##*:}
  case "$ARMS" in
    *B*) run form_n    checkpoints/reasoner_form_n_sft/final.pt    "$bn" "$bf" ;;
  esac
  case "$ARMS" in
    *C*) run formdiv_n checkpoints/reasoner_formdiv_n_sft/final.pt "$bn" "$bf" ;;
  esac
done

echo "ALL DONE factorial eval; TS=$TS"
echo "outputs: eval/results/factorial_*_${TS}.jsonl"
echo "ARM A comparison: eval/results/enbase_ugf_n_*_20260602_081559.jsonl"
