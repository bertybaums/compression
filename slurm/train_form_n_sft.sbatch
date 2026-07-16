#!/bin/bash
#SBATCH --job-name=form-n-sft
#SBATCH --partition=gpu-8
#SBATCH --exclude=n113,n118,n121,n122
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=2-00:00:00
#SBATCH --output=logs/%j_form_n_sft.out
#SBATCH --error=logs/%j_form_n_sft.err

# ARM B of the form x prompt-diversity factorial: SFT on the form corpus
# (ugf_form_n.jsonl, generated June 9). Mirrors ARM A exactly -- ARM A is
# already trained at checkpoints/reasoner_ugf_n_sft/final.pt (June 2) -- so
# the only difference between the arms is response form.
#
# Resumes from the SAME pretrain checkpoint ARM A used.
# See docs/form-retrain-clean-design-2026-06-03.md (THIRD AMENDMENT) for why a
# null here must NOT be read as a structural limit of essay distillation.

source /etc/profile
set -e

source ~/venvs/compression/bin/activate

cd ~/compression

echo "Job $SLURM_JOB_ID starting on $(hostname)"
echo "GPU: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader)"

python3 -u -m reasoner.train_sft \
    --config configs/reasoner_form_n_sft.yaml \
    --resume checkpoints/reasoner_ugf_n_pretrain/final.pt
