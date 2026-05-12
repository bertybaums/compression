#!/bin/bash
#SBATCH --job-name=forms-gen
#SBATCH --partition=cpu-l
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=2-00:00:00
#SBATCH --output=logs/%j_forms_gen.out
#SBATCH --error=logs/%j_forms_gen.err

# Form-diverse corpus generation: extract (UGF prompt, UGF response) training
# pairs from canonical philosophical texts (Plato, Hume, Aquinas, Sextus, ...)
# via teacher distillation. CPU-only — all compute happens at MR endpoints.
#
# Default config uses the v1 teacher ensemble (gpt-oss-120b + qwen3.6-27b)
# with the token-bucket-shared 200 rpm cap. Path A target (continuation SFT):
# ~50K compliant pairs; Path B target (full retrain): ~500K.
#
# Resume-safe: if killed mid-run, re-launching picks up from
# corpus/processed/forms_progress.json.

source /etc/profile
set -e

source ~/venvs/compression/bin/activate

cd ~/compression

echo "Job $SLURM_JOB_ID starting on $(hostname)"
echo "Time: $(date)"

# Make sure source-pair JSONLs exist. The parsers are deterministic; if a JSONL
# is missing, regenerate it. (They live in corpus/poc/ but produce data this
# script consumes.)
if [ ! -s corpus/poc/meno_pairs.jsonl ]; then
  echo "Generating Meno pairs..."
  python3 corpus/poc/parse_meno.py --all
fi
if [ ! -s corpus/poc/hume_pairs.jsonl ]; then
  echo "Generating Hume pairs..."
  python3 corpus/poc/parse_hume.py --all
fi
if [ ! -s corpus/poc/aquinas_pairs.jsonl ]; then
  echo "Generating Aquinas pairs..."
  python3 corpus/poc/parse_aquinas.py --all
fi
if [ ! -s corpus/poc/sextus_pairs.jsonl ]; then
  echo "Generating Sextus pairs..."
  python3 corpus/poc/parse_sextus.py --all
fi

echo "--- Source pair counts ---"
wc -l corpus/poc/meno_pairs.jsonl corpus/poc/hume_pairs.jsonl \
      corpus/poc/aquinas_pairs.jsonl corpus/poc/sextus_pairs.jsonl

# Optional: cap pairs per source for a Path A run. Comment out for Path B.
LIMIT_PER_SOURCE=${FORMS_LIMIT_PER_SOURCE:-}
LIMIT_ARG=""
if [ -n "$LIMIT_PER_SOURCE" ]; then
  LIMIT_ARG="--limit-per-source $LIMIT_PER_SOURCE"
fi

# Use PYTHONUNBUFFERED so SLURM logs see live progress prints.
export PYTHONUNBUFFERED=1

python3 corpus/generation/generate_forms.py \
  --sources corpus/generation/forms_sources.yaml \
  --output corpus/processed/ugf_forms_corpus.jsonl \
  --progress corpus/processed/forms_progress.json \
  $LIMIT_ARG

echo "Done at $(date)"
echo "Output: corpus/processed/ugf_forms_corpus.jsonl"
wc -l corpus/processed/ugf_forms_corpus.jsonl
