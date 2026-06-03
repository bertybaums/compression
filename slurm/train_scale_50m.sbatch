#!/bin/bash
#SBATCH --job-name=scale-50m
#SBATCH --partition=gpu-8
#SBATCH --exclude=n113,n118,n121,n122
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=1-00:00:00
#SBATCH --output=logs/%j_scale_50m.out
#SBATCH --error=logs/%j_scale_50m.err

# Scale study, low end (~52M). docs/scale-study-design-2026-06-03.md
# Pretrain (100K) -> SFT (30K) in sequence, v1 recipe, on one GPU.

source /etc/profile
set -e
source ~/venvs/compression/bin/activate
cd ~/compression

echo "Job $SLURM_JOB_ID on $(hostname)"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader

echo "=== Phase 1: pretrain (52M) ==="
python3 -u -m reasoner.train --config configs/reasoner_scale_50m_pretrain.yaml

echo "=== Phase 2: SFT (52M) ==="
python3 -u -m reasoner.train_sft \
    --config configs/reasoner_scale_50m_sft.yaml \
    --resume checkpoints/reasoner_scale_50m_pretrain/final.pt

echo "ALL DONE (scale 52M): checkpoints/reasoner_scale_50m_sft/final.pt"
