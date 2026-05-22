#!/bin/bash
#SBATCH --job-name=ugf-reasoner-rl-v3
#SBATCH --partition=gpu-8
#SBATCH --exclude=n113,n118,n121,n122
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=1-00:00:00
#SBATCH --output=%j_reasoner_rl_v3.out
#SBATCH --error=%j_reasoner_rl_v3.err

# Reasoner RL v3 — continuation of v2 from its step-100 checkpoint.
# 250 more steps. Design doc: docs/rl-design-2026-05-18.md
# Estimated wall time: ~20-22h (250 steps × ~300s).

source /etc/profile
set -e
source ~/venvs/compression/bin/activate
cd ~/compression

mkdir -p logs/reasoner_rl_v3

echo "Job $SLURM_JOB_ID starting on $(hostname)"
echo "GPU: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader)"

python3 -u -m reasoner.train_rl \
    --config configs/reasoner_rl_v3.yaml \
    --resume checkpoints/reasoner_rl_v2/final.pt

mv ${SLURM_JOB_ID}_reasoner_rl_v3.out logs/ 2>/dev/null || true
mv ${SLURM_JOB_ID}_reasoner_rl_v3.err logs/ 2>/dev/null || true
