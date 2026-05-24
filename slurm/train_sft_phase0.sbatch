#!/bin/bash
#SBATCH --job-name=ugf-sft-phase0
#SBATCH --partition=gpu-8
#SBATCH --exclude=n113,n118,n121,n122
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=06:00:00
#SBATCH --output=%j_sft_phase0.out
#SBATCH --error=%j_sft_phase0.err

# Form-diverse pilot SFT (Phase 0). Parameterized by CONFIG so both arms reuse it:
#   sbatch --export=ALL,CONFIG=configs/reasoner_sft_phase0_form.yaml  slurm/train_sft_phase0.sbatch
#   sbatch --export=ALL,CONFIG=configs/reasoner_sft_phase0_essay.yaml slurm/train_sft_phase0.sbatch
# Both init from the same pretrain checkpoint. Design: docs/form-diverse-retrain-design-2026-05-24.md

source /etc/profile
set -e
source ~/venvs/compression/bin/activate
cd ~/compression

CONFIG=${CONFIG:-configs/reasoner_sft_phase0_form.yaml}
echo "Job $SLURM_JOB_ID on $(hostname); CONFIG=$CONFIG"
echo "GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader)"

python3 -u -m reasoner.train_sft \
    --config "$CONFIG" \
    --resume checkpoints/reasoner_pretrain_v1/final.pt

mv ${SLURM_JOB_ID}_sft_phase0.out logs/ 2>/dev/null || true
mv ${SLURM_JOB_ID}_sft_phase0.err logs/ 2>/dev/null || true
