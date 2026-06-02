#!/bin/bash
#SBATCH --job-name=enbase-eval
#SBATCH --partition=gpu-8
#SBATCH --exclude=n113,n118,n121,n122
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=02:00:00
#SBATCH --output=logs/%j_enbase_eval.out
#SBATCH --error=logs/%j_enbase_eval.err

# Eval both arms of the 200M English-vocab baseline on the 3 milestone benches.
# docs/english-baseline-design-2026-05-24.md
# Matched anti-rep decode (same as the SFT-v2/DPO milestone evals). Each arm uses
# its OWN vocab via --vocab-path (MUST match the checkpoint's vocab_size).
# Outputs: eval/results/enbase_<arm>_<bench>_<TS>.jsonl  (judged in isolation downstream).

source /etc/profile
set -e
source ~/venvs/compression/bin/activate
cd ~/compression

TS=$(date +%Y%m%d_%H%M%S)
DECODE="--repetition-penalty 1.2 --no-repeat-ngram-size 4 --temperature 0.8 --top-k 50 --top-p 0.9 --max-new-tokens 400"

echo "Job $SLURM_JOB_ID on $(hostname); TS=$TS"
nvidia-smi --query-gpu=name --format=csv,noheader

UGF=checkpoints/reasoner_ugf_n_sft/final.pt;  UGFV=wordlist/vocab_final.json
EN=checkpoints/reasoner_en_n_sft/final.pt;    ENV=wordlist/vocab_english_40k.json

run () {  # arm ckpt vocab benchname benchfile
  echo "=== $1 / $4 ==="
  python3 -u -m eval.run_sft_v2_bench --bench "$5" \
      --reasoner "$2" --vocab-path "$3" \
      --out "eval/results/enbase_${1}_${4}_${TS}.jsonl" $DECODE
}

for b in "stress:eval/sets/stress_bench.jsonl" \
         "holdout:eval/sets/holdout_bench.jsonl" \
         "cx_patched:eval/sets/holdout_bench_cx_patched.jsonl"; do
  bn=${b%%:*}; bf=${b##*:}
  run ugf_n "$UGF"  "$UGFV" "$bn" "$bf"
  run en_n  "$EN"   "$ENV"  "$bn" "$bf"
done

echo "ALL DONE enbase eval; TS=$TS"
echo "outputs: eval/results/enbase_*_${TS}.jsonl"
