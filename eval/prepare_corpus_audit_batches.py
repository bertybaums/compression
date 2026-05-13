"""
Prepare audit batches for the Translator-training corpus.

Targets: corpus/processed/parallel_corpus.jsonl (the EN↔UGF pairs the trained
T5 Translator was trained on). Each record has fields:

    {id, english, ugf, metadata, validation_attempts, compliant}

For the audit, we sample a stratified subset and translate to the standard
translator-judge input schema {id, english_source, ugf_translation}, then
write batches under judge_input_translator/ alongside the live-translator
batches so they get scored with the same rubric.

Default sample: 300 records, stratified by track (in metadata).

Usage:
    python -m eval.prepare_corpus_audit_batches \\
        --corpus corpus/processed/parallel_corpus.jsonl \\
        --n 300 \\
        --label corpus_parallel
"""

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

ROOT = Path("/Users/bbaum/Documents/_RCDS/compression/eval")
OUT = ROOT / "judge_input_translator"
JUDGE_OUT = ROOT / "judge_output_translator"
BATCH_SIZE = 40


def stratify_sample(records: list[dict], n_target: int, strat_key: str, seed: int = 42) -> list[dict]:
    """Sample proportionally per stratum, but with a minimum of 1 per stratum.
    Records without the key go into 'unknown'."""
    rng = random.Random(seed)
    buckets: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        key = str(r.get("metadata", {}).get(strat_key, "unknown"))
        buckets[key].append(r)

    total = sum(len(b) for b in buckets.values())
    sample: list[dict] = []
    for key, bucket in buckets.items():
        share = max(1, round(n_target * len(bucket) / total))
        rng.shuffle(bucket)
        sample.extend(bucket[: min(share, len(bucket))])
    rng.shuffle(sample)
    return sample[:n_target]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--corpus",
        default="corpus/processed/parallel_corpus.jsonl",
        help="Path to corpus file (parallel_corpus.jsonl-style schema).",
    )
    parser.add_argument(
        "--n", type=int, default=300, help="Target sample size."
    )
    parser.add_argument(
        "--label",
        default="corpus_parallel",
        help="System label for the judge batches (used in filenames + aggregation).",
    )
    parser.add_argument(
        "--strat-key",
        default="track",
        help="metadata field to stratify on (e.g. 'track', 'difficulty_tier').",
    )
    parser.add_argument(
        "--require-compliant",
        action="store_true",
        help="Only include records flagged compliant=true.",
    )
    args = parser.parse_args()

    corpus_path = Path(args.corpus)
    print(f"Loading corpus from {corpus_path}...")
    records: list[dict] = []
    with open(corpus_path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if args.require_compliant and not r.get("compliant", False):
                continue
            if not r.get("english") or not r.get("ugf"):
                continue
            records.append(r)
    print(f"  {len(records)} records after filtering")

    sample = stratify_sample(records, args.n, args.strat_key)
    print(f"  sampled {len(sample)} records, stratified by {args.strat_key!r}")

    OUT.mkdir(exist_ok=True)
    JUDGE_OUT.mkdir(exist_ok=True)

    label = args.label
    n_batches = (len(sample) + BATCH_SIZE - 1) // BATCH_SIZE
    manifest_additions: list[dict] = []
    for b in range(n_batches):
        chunk = sample[b * BATCH_SIZE : (b + 1) * BATCH_SIZE]
        out_path = OUT / f"{label}_batch_{b+1:02d}.jsonl"
        with open(out_path, "w") as fh:
            for r in chunk:
                fh.write(json.dumps({
                    "id": r["id"],
                    "english_source": r["english"],
                    "ugf_translation": r["ugf"],
                }) + "\n")
        manifest_additions.append({
            "label": label,
            "batch": b + 1,
            "n_items": len(chunk),
            "input_path": str(out_path),
            "output_path": str(JUDGE_OUT / f"{label}_batch_{b+1:02d}.jsonl"),
            "source_file": str(corpus_path),
        })

    # Merge into existing manifest (if any) so corpus-audit batches sit
    # alongside live-translator batches and are picked up by the same aggregator.
    manifest_path = ROOT / "judge_manifest_translator.json"
    existing: list[dict] = []
    if manifest_path.exists():
        existing = json.load(open(manifest_path))
    existing = [m for m in existing if m["label"] != label]
    existing.extend(manifest_additions)
    with open(manifest_path, "w") as fh:
        json.dump(existing, fh, indent=2)

    print(f"\nWrote {n_batches} batches ({len(sample)} items) as label {label!r}.")
    print(f"Manifest updated: {manifest_path}")


if __name__ == "__main__":
    main()
