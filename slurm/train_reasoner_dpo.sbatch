#!/bin/bash
#SBATCH --job-name=ugf-reasoner-dpo
#SBATCH --partition=gpu-8
#SBATCH --exclude=n113,n118,n121,n122
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=04:00:00
#SBATCH --output=%j_reasoner_dpo.out
#SBATCH --error=%j_reasoner_dpo.err

# Reasoner Stage-1 preference tuning (DPO / APO-zero).
# Prereq: corpus/processed/dpo_pairs.jsonl (from slurm/build_preference_pairs.sbatch).
# Inits from SFT-v2; 1 epoch. Design: docs/dpo-stage1-design-2026-05-22.md

source /etc/profile
set -e
source ~/venvs/compression/bin/activate
cd ~/compression

mkdir -p logs/reasoner_dpo_v1

echo "Job $SLURM_JOB_ID on $(hostname)"
echo "GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader)"

python3 -u -m reasoner.train_dpo \
    --config configs/reasoner_dpo_v1.yaml \
    --resume checkpoints/reasoner_sft_v2/final.pt

mv ${SLURM_JOB_ID}_reasoner_dpo.out logs/ 2>/dev/null || true
mv ${SLURM_JOB_ID}_reasoner_dpo.err logs/ 2>/dev/null || true
