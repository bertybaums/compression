#!/bin/bash
#SBATCH --job-name=structured-translator
#SBATCH --partition=gpu-8
#SBATCH --exclude=n113,n118,n121,n122
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=0-04:00:00
#SBATCH --output=logs/%j_structured_translator.out
#SBATCH --error=logs/%j_structured_translator.err

# Run the EN->UGF logic-textbook benchmark through the structured-output
# Translator (base model + hard UGF mask, no training). Output schema
# matches the trained-T5 May-5 outputs for direct comparison.

source /etc/profile
set -e

source ~/venvs/structured-translator/bin/activate

cd ~/compression

echo "Job $SLURM_JOB_ID starting on $(hostname)"
echo "GPU: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader)"

# Use the pre-downloaded model snapshot to avoid hitting HF Hub on the compute
# node (which has no internet). Set HF_HOME to where setup_structured_translator.sh
# cached the weights.
export HF_HOME=$HOME/.cache/huggingface
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

MODEL="${MODEL:-openai/gpt-oss-20b}"
TS=$(date +%Y%m%d_%H%M%S)
OUT="eval/results/logic_bench_structured_${TS}.jsonl"

python3 -u -m eval.run_structured_translator_bench \
    --bench eval/sets/logic_textbook_bench.jsonl \
    --model "$MODEL" \
    --out "$OUT" \
    --max-new-tokens 300 \
    --temperature 0.7

echo "Done. Results: $OUT"
