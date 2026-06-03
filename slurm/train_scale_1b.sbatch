#!/bin/bash
#SBATCH --job-name=scale-1b
#SBATCH --partition=gpu-8-long
#SBATCH --exclude=n113,n118,n121,n122
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=7-00:00:00
#SBATCH --output=logs/%j_scale_1b.out
#SBATCH --error=logs/%j_scale_1b.err

# Scale study, high end (~1.03B). docs/scale-study-design-2026-06-03.md
# Pretrain (100K) -> SFT (30K) in sequence, v1 recipe, batch 4 / accum 16 (eff 64).
# The long pole: ~4-6 GPU-days. gpu-8-long. Watch the first steps for OOM
# (gradient_checkpointing is a no-op here; if it OOMs, drop batch_size to 2 /
# grad_accum 32 and resubmit -- the pretrain checkpoints resume).

source /etc/profile
set -e
source ~/venvs/compression/bin/activate
cd ~/compression

echo "Job $SLURM_JOB_ID on $(hostname)"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader

echo "=== Phase 1: pretrain (1B) ==="
python3 -u -m reasoner.train --config configs/reasoner_scale_1b_pretrain.yaml

echo "=== Phase 2: SFT (1B) ==="
python3 -u -m reasoner.train_sft \
    --config configs/reasoner_scale_1b_sft.yaml \
    --resume checkpoints/reasoner_scale_1b_pretrain/final.pt

echo "ALL DONE (scale 1B): checkpoints/reasoner_scale_1b_sft/final.pt"
