#!/bin/bash
#SBATCH --job-name=ugf-reasoner
#SBATCH --partition=gpu-8
#SBATCH --exclude=n113,n118,n121,n122
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=2-00:00:00
#SBATCH --output=logs/%j_reasoner.out
#SBATCH --error=logs/%j_reasoner.err

# Reasoner training (200M variant): from-scratch transformer.
# Estimated wall time on A6000: ~12-24h for 100K steps at ~1s/step.
# Excludes nodes known to be slow / bf16-incapable (per translator job).

source /etc/profile
set -e

source ~/venvs/compression/bin/activate

cd ~/compression

echo "Job $SLURM_JOB_ID starting on $(hostname)"
echo "GPU: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader)"

python3 -u reasoner/train.py --config configs/reasoner.yaml
