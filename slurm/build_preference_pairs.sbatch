#!/bin/bash
#SBATCH --job-name=ugf-dpo-pairs
#SBATCH --partition=gpu-8
#SBATCH --exclude=n113,n118,n121,n122
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=08:00:00
#SBATCH --output=%j_dpo_pairs.out
#SBATCH --error=%j_dpo_pairs.err

# Mine Stage-1 DPO preference pairs: SFT-v2 rollouts (GPU) scored by the
# Nemotron jury (MR — reachable from compute nodes, as the v3 RL job proved),
# paired against P4 references. Prereq: corpus/processed/p4_refs.jsonl exists
# (from reasoner.build_p4_refs). Design: docs/dpo-stage1-design-2026-05-22.md

source /etc/profile
set -e
source ~/venvs/compression/bin/activate
cd ~/compression

echo "Job $SLURM_JOB_ID on $(hostname)"
echo "GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader)"

python3 -u -m reasoner.build_preference_pairs \
    --reasoner checkpoints/reasoner_sft_v2/final.pt \
    --prompts corpus/processed/rl_train_prompts.jsonl \
    --p4-refs corpus/processed/p4_refs.jsonl \
    --out corpus/processed/dpo_pairs.jsonl \
    --n-rollouts 6

mv ${SLURM_JOB_ID}_dpo_pairs.out logs/ 2>/dev/null || true
mv ${SLURM_JOB_ID}_dpo_pairs.err logs/ 2>/dev/null || true
