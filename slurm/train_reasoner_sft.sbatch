#!/bin/bash
#SBATCH --job-name=ugf-reasoner-sft
#SBATCH --partition=gpu-8
#SBATCH --exclude=n113,n118,n121,n122
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=1-00:00:00
#SBATCH --output=logs/%j_reasoner_sft.out
#SBATCH --error=logs/%j_reasoner_sft.err

# Reasoner Phase-2 SFT: prompt-masked supervised fine-tuning starting from
# the Phase-1 pretrain checkpoint. Estimated wall time on A6000: ~2-3h.
# Path conventions strict-separated from pretrain:
#   - config: configs/reasoner_sft.yaml
#   - checkpoints: checkpoints/reasoner_sft_v1/
#   - logs: logs/reasoner_sft/
#   - SLURM job logs: logs/<jobid>_reasoner_sft.{out,err}
# The pretrain artifacts at checkpoints/reasoner_pretrain_v1/ are NOT touched.

source /etc/profile
set -e

source ~/venvs/compression/bin/activate

cd ~/compression

echo "Job $SLURM_JOB_ID starting on $(hostname)"
echo "GPU: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader)"

python3 -u -m reasoner.train_sft \
    --config configs/reasoner_sft.yaml \
    --resume checkpoints/reasoner_pretrain_v1/final.pt
