#!/bin/bash
#SBATCH --job-name=formdiv-n-sft
#SBATCH --partition=gpu-8
#SBATCH --exclude=n113,n118,n121,n122
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=2-00:00:00
#SBATCH --output=logs/%j_formdiv_n_sft.out
#SBATCH --error=logs/%j_formdiv_n_sft.err

# ARM C of the form x prompt-diversity factorial: SFT on the diverse-prompt form
# corpus. Mirrors ARM B exactly (same pretrain init, vocab, hyperparameters, 30K
# steps); only the corpus differs, so B vs C isolates prompt diversity at fixed
# response form.
#
# See docs/form-retrain-clean-design-2026-06-03.md (THIRD AMENDMENT).

source /etc/profile
set -e

source ~/venvs/compression/bin/activate

cd ~/compression

echo "Job $SLURM_JOB_ID starting on $(hostname)"
echo "GPU: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader)"

# Guard: ARM C is only a treatment if its prompts are actually diverse. Arms A/B
# score 0.0009 prompt:example. Refuse to burn a GPU on a corpus that is secretly
# the same experiment as ARM B.
echo "=== prompt-diversity gate ==="
python3 -u -m corpus.generation.audit_prompt_diversity \
    corpus/processed/ugf_formdiv_n.jsonl --warn-ratio 0.05
echo "gate passed: corpus is prompt-informative"

python3 -u -m reasoner.train_sft \
    --config configs/reasoner_formdiv_n_sft.yaml \
    --resume checkpoints/reasoner_ugf_n_pretrain/final.pt
