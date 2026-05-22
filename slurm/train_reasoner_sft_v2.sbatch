#!/bin/bash
#SBATCH --job-name=ugf-reasoner-sft-v2
#SBATCH --partition=gpu-8
#SBATCH --exclude=n113,n118,n121,n122
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=1-00:00:00
#SBATCH --output=logs/%j_reasoner_sft_v2.out
#SBATCH --error=logs/%j_reasoner_sft_v2.err

# Reasoner SFT v2 (purist think-answer): explicit reasoning/answer separation
# trained with the pure-UGF phrasal marker "So my answer is:". Reverses v1's
# format-anchoring recipe. Design doc: docs/sft-v2-design-2026-05-18.md
#
# Estimated wall time on A6000: ~1.5-2.5h (20K steps, smaller corpus than v1).
#
# Path conventions strict-separated from v1:
#   - config: configs/reasoner_sft_v2.yaml
#   - checkpoints: checkpoints/reasoner_sft_v2/
#   - logs: logs/reasoner_sft_v2/
#   - SLURM job logs: logs/<jobid>_reasoner_sft_v2.{out,err}
#
# Resumes from the pretrain checkpoint (NOT v1-SFT): clean experimental
# control. v1-SFT remains on disk as a comparator artefact.

source /etc/profile
set -e

source ~/venvs/compression/bin/activate

cd ~/compression

echo "Job $SLURM_JOB_ID starting on $(hostname)"
echo "GPU: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader)"

python3 -u -m reasoner.train_sft \
    --config configs/reasoner_sft_v2.yaml \
    --resume checkpoints/reasoner_pretrain_v1/final.pt
