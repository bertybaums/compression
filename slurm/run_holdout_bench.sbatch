#!/bin/bash
#SBATCH --job-name=ugf-holdout-bench
#SBATCH --partition=gpu-8
#SBATCH --exclude=n113,n118,n121,n122
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=0-02:00:00
#SBATCH --output=logs/%j_holdout_bench.out
#SBATCH --error=logs/%j_holdout_bench.err

# Layer-2 evaluation on the corpus heldout: feed each held-out (topic,
# content_type) prompt through SFT Reasoner and translate the UGF response
# back to English. Skips Translator(English -> UGF) because the holdout
# prompts are already in the corpus-prompt format the Reasoner trained on.

source /etc/profile
set -e

source ~/venvs/compression/bin/activate

cd ~/compression

echo "Job $SLURM_JOB_ID starting on $(hostname)"
echo "GPU: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader)"

python3 -u -m eval.run_logic_bench \
    --bench eval/sets/holdout_bench.jsonl \
    --reasoner checkpoints/reasoner_sft_v1/final.pt \
    --translator checkpoints/translator/best \
    --skip-translate-en2ugf
