#!/bin/bash
#SBATCH --job-name=ugf-reasoner
#SBATCH --partition=gpu-8
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=5-00:00:00
#SBATCH --output=logs/%j_reasoner.out
#SBATCH --error=logs/%j_reasoner.err

# Reasoner training: 1.5B from-scratch transformer, ~3-5 days on A6000

source /etc/profile
set -e

module load python/3.11.11
source ~/venvs/compression/bin/activate

cd ~/compression

echo "Job $SLURM_JOB_ID starting on $(hostname)"
echo "GPU: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader)"

python3 reasoner/train.py --config configs/reasoner.yaml
