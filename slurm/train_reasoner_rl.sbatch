#!/bin/bash
#SBATCH --job-name=ugf-reasoner-rl
#SBATCH --partition=gpu-8
#SBATCH --exclude=n113,n118,n121,n122
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=0-12:00:00
#SBATCH --output=%j_reasoner_rl.out
#SBATCH --error=%j_reasoner_rl.err

# Reasoner RL v1 (GRPO). Self-play with Nemotron judge + SFT anchor.
# Design doc: docs/rl-design-2026-05-18.md
# Estimated wall time: 100-step smoke test ~3-4h (mostly judge calls).

source /etc/profile
set -e
source ~/venvs/compression/bin/activate
cd ~/compression

# Move slurm logs into the project logs dir.
mkdir -p logs/reasoner_rl_v1

echo "Job $SLURM_JOB_ID starting on $(hostname)"
echo "GPU: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader)"

python3 -u -m reasoner.train_rl \
    --config configs/reasoner_rl_v1.yaml \
    --resume checkpoints/reasoner_sft_v2/final.pt

mv ${SLURM_JOB_ID}_reasoner_rl.out logs/ 2>/dev/null || true
mv ${SLURM_JOB_ID}_reasoner_rl.err logs/ 2>/dev/null || true
