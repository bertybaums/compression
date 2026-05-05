#!/bin/bash
#SBATCH --job-name=ugf-translate-back
#SBATCH --partition=gpu-8
#SBATCH --exclude=n113,n118,n121,n122
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=0-01:00:00
#SBATCH --output=logs/%j_ugf2en.out
#SBATCH --error=logs/%j_ugf2en.err

# UGF -> English translator pass on a JSONL of comparator outputs.
# Pass the input path as the first arg.
# Estimated <10 min for 115 items on A6000.

source /etc/profile
set -e

source ~/venvs/compression/bin/activate

cd ~/compression

INPUT="${1:-eval/results/comparator_logic_textbook_20260505_143019.jsonl}"

echo "Job $SLURM_JOB_ID starting on $(hostname)"
echo "GPU: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader)"
echo "Input: $INPUT"

python3 -u -m eval.translate_ugf_to_english \
    --input "$INPUT" \
    --translator checkpoints/translator/best
