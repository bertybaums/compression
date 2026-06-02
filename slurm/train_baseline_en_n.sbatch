#!/bin/bash
#SBATCH --job-name=enbase-en-n
#SBATCH --partition=gpu-8
#SBATCH --exclude=n113,n118,n121,n122
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=4-00:00:00
#SBATCH --output=logs/%j_enbase_en_n.out
#SBATCH --error=logs/%j_enbase_en_n.err

# 200M English-vocab baseline -- English arm (the variable).
# docs/english-baseline-design-2026-05-24.md
#
# Runs Phase 1 (100K pretrain) THEN Phase 2 (30K SFT) on one GPU, in sequence
# (set -e: SFT only runs if pretrain succeeded). Matched 1:1 with
# train_baseline_ugf_n.sbatch -- launch both, one per GPU, only the vocab differs.
# The English model is larger (~234M vs ~197M; 40K-vocab softmax) -> slightly
# slower per step; 4-day cap still has ample slack.

source /etc/profile
set -e
source ~/venvs/compression/bin/activate
cd ~/compression

echo "Job $SLURM_JOB_ID on $(hostname)"
echo "GPU: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader)"

echo "=== Phase 1: pretrain (English-N) ==="
python3 -u -m reasoner.train --config configs/reasoner_en_n_pretrain.yaml

echo "=== Phase 2: SFT (English-N) ==="
python3 -u -m reasoner.train_sft \
    --config configs/reasoner_en_n_sft.yaml \
    --resume checkpoints/reasoner_en_n_pretrain/final.pt

echo "ALL DONE (English-N): checkpoints/reasoner_en_n_sft/final.pt"
