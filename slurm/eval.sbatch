#!/bin/bash
#SBATCH --job-name=ugf-eval
#SBATCH --partition=gpu-8
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=8:00:00
#SBATCH --output=logs/%j_eval.out
#SBATCH --error=logs/%j_eval.err

# Evaluation pipeline: needs GPU for BERTScore, NLI, sentence-transformers
# Also needs internet on login node to pre-cache model weights before submitting

source /etc/profile
set -e

module load python/3.11.11
source ~/venvs/compression/bin/activate

cd ~/compression

echo "Job $SLURM_JOB_ID starting on $(hostname)"
echo "GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader)"

# Run all tests (adjust paths as needed)
python3 eval/round_trip.py \
  --test all \
  --eval-set eval/sets/eval_combined.jsonl \
  --translator-path checkpoints/translator/best \
  --reasoner-path checkpoints/reasoner/final.pt \
  --llm-judge \
  --output eval/results/full_eval_$(date +%Y%m%d).json

# Generate report
python3 eval/analyze.py eval/results/full_eval_$(date +%Y%m%d).json \
  --report eval/reports/report-$(date +%Y-%m-%d).md
