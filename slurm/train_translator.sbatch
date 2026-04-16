#!/bin/bash
#SBATCH --job-name=ugf-translator
#SBATCH --partition=gpu-8
#SBATCH --exclude=n113,n118,n121,n122
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=48:00:00
#SBATCH --output=logs/%j_translator.out
#SBATCH --error=logs/%j_translator.err

# Translator training: T5-small fine-tuning, ~2 hours on A6000

source /etc/profile
set -e

source ~/venvs/compression/bin/activate

cd ~/compression

echo "Job $SLURM_JOB_ID starting on $(hostname)"
echo "GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader)"

python3 translator/train.py --config configs/translator.yaml
