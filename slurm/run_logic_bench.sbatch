#!/bin/bash
#SBATCH --job-name=ugf-logic-bench
#SBATCH --partition=gpu-8
#SBATCH --exclude=n113,n118,n121,n122
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=0-02:00:00
#SBATCH --output=logs/%j_logic_bench.out
#SBATCH --error=logs/%j_logic_bench.err

# Layer-2 evaluation: run the 115-item logic textbook benchmark through
# the full English -> Translator -> Reasoner_SFT -> Translator -> English
# pipeline. Output: eval/results/logic_bench_<timestamp>.jsonl with
# per-item intermediate UGF and final English responses.

source /etc/profile
set -e

source ~/venvs/compression/bin/activate

cd ~/compression

echo "Job $SLURM_JOB_ID starting on $(hostname)"
echo "GPU: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader)"

python3 -u -m eval.run_logic_bench \
    --bench eval/sets/logic_textbook_bench.jsonl \
    --reasoner checkpoints/reasoner_sft_v1/final.pt \
    --translator checkpoints/translator/best
