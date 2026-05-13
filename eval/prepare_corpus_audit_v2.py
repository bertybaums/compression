"""
Prepare audit batches for the corpus-quality LLM judge.

Targets three corpora:
  - existing_reasoning  →  corpus/processed/ugf_reasoning.jsonl  (v1 pretrain corpus)
  - forms               →  corpus/processed/ugf_forms_corpus.jsonl (diversification)
  - cot                 →  corpus/processed/ugf_cot.jsonl (chain-of-thought)

Each record is normalized to the standard judge-input schema:
    {"id": str, "english_query": str, "ugf_response": str}

where english_query is the prompt-side context (whatever the model was
"answering") and ugf_response is the UGF text under review. This matches the
schema the existing aggregate_judge_scores.py expects, so we can reuse the
Reasoner rubric (rubric.md) and aggregator without modification.

Stratified sampling defaults: 300 records per corpus, total 900.

Usage:
    python -m eval.prepare_corpus_audit_v2 \\
        --existing-reasoning corpus/processed/ugf_reasoning.jsonl \\
        --forms              corpus/processed/ugf_forms_corpus.jsonl \\
        --cot                corpus/processed/ugf_cot.jsonl \\
        --n-per-corpus 300
"""

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

ROOT = Path("/Users/bbaum/Documents/_RCDS/compression/eval")
OUT = ROOT / "judge_input_corpus_audit"
JUDGE_OUT = ROOT / "judge_output_corpus_audit"
BATCH_SIZE = 40


# ---------------------------------------------------------------------------
# Per-corpus normalizers
# ---------------------------------------------------------------------------

def normalize_reasoning(r: dict) -> dict | None:
    """Existing 2M reasoning corpus. Schema:
        {id, ugf_text, content_type, topic, source_model, metadata, compliant}
    """
    if not r.get("compliant", False):
        return None
    if not r.get("ugf_text") or not r.get("topic"):
        return None
    return {
        "id": r["id"],
        "english_query": r["topic"],
        "ugf_response": r["ugf_text"],
        "_strat": r.get("content_type", "unknown"),
        "_meta": {
            "content_type": r.get("content_type"),
            "source_model": r.get("source_model"),
            "domain": (r.get("metadata") or {}).get("domain"),
        },
    }


def normalize_forms(r: dict) -> dict | None:
    """Diversification corpus. Schema (from generate_forms.py):
        {id, form, source, prompt, response, teacher, compliant, metadata}
    """
    if not r.get("compliant", False):
        return None
    if not r.get("prompt") or not r.get("response"):
        return None
    return {
        "id": r["id"],
        "english_query": r["prompt"],  # UGF prompt that was written
        "ugf_response": r["response"],
        "_strat": r.get("form", "unknown"),
        "_meta": {
            "form": r.get("form"),
            "source": r.get("source"),
            "teacher": r.get("teacher"),
        },
    }


def normalize_cot(r: dict) -> dict | None:
    """CoT corpus. Schema (from generate_cot.py):
        {id, track, depth, reasoning, conclusion|verdict, compliant, ...}
    """
    if not r.get("compliant", False):
        return None
    reasoning = r.get("reasoning", "")
    tail = r.get("conclusion") or r.get("verdict") or ""
    if not reasoning:
        return None
    response = f"{reasoning} {tail}".strip() if tail else reasoning
    return {
        "id": r["id"],
        "english_query": r.get("prompt_text", ""),
        "ugf_response": response,
        "_strat": f"{r.get('track', 'unknown')}_{r.get('depth', 'unknown')}",
        "_meta": {
            "track": r.get("track"),
            "depth": r.get("depth"),
            "correct": r.get("correct"),
            "source_model": r.get("source_model"),
        },
    }


CORPUS_HANDLERS = {
    "existing_reasoning": normalize_reasoning,
    "forms": normalize_forms,
    "cot": normalize_cot,
}


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------

def stratified_sample(records: list[dict], n_target: int, seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    buckets: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        buckets[r["_strat"]].append(r)
    total = sum(len(b) for b in buckets.values())
    if total == 0:
        return []
    sample: list[dict] = []
    for key, bucket in buckets.items():
        share = max(1, round(n_target * len(bucket) / total))
        rng.shuffle(bucket)
        sample.extend(bucket[:min(share, len(bucket))])
    rng.shuffle(sample)
    return sample[:n_target]


def write_batches(label: str, records: list[dict]) -> list[dict]:
    OUT.mkdir(exist_ok=True)
    JUDGE_OUT.mkdir(exist_ok=True)
    n_batches = (len(records) + BATCH_SIZE - 1) // BATCH_SIZE
    manifest: list[dict] = []
    for b in range(n_batches):
        chunk = records[b * BATCH_SIZE : (b + 1) * BATCH_SIZE]
        out_path = OUT / f"{label}_batch_{b+1:02d}.jsonl"
        with open(out_path, "w") as f:
            for item in chunk:
                f.write(json.dumps({
                    "id": item["id"],
                    "english_query": item["english_query"],
                    "ugf_response": item["ugf_response"],
                }) + "\n")
        manifest.append({
            "label": label,
            "batch": b + 1,
            "n_items": len(chunk),
            "input_path": str(out_path),
            "output_path": str(JUDGE_OUT / f"{label}_batch_{b+1:02d}.jsonl"),
        })
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--existing-reasoning", default=None,
                        help="Path to corpus/processed/ugf_reasoning.jsonl")
    parser.add_argument("--forms", default=None,
                        help="Path to corpus/processed/ugf_forms_corpus.jsonl")
    parser.add_argument("--cot", default=None,
                        help="Path to corpus/processed/ugf_cot.jsonl")
    parser.add_argument("--n-per-corpus", type=int, default=300)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    corpora = {}
    if args.existing_reasoning:
        corpora["existing_reasoning"] = Path(args.existing_reasoning)
    if args.forms:
        corpora["forms"] = Path(args.forms)
    if args.cot:
        corpora["cot"] = Path(args.cot)
    if not corpora:
        raise SystemExit("Specify at least one of --existing-reasoning, --forms, --cot")

    full_manifest: list[dict] = []
    for label, path in corpora.items():
        print(f"--- {label}: {path} ---")
        if not path.exists():
            print(f"  MISSING; skipping")
            continue
        normalizer = CORPUS_HANDLERS[label]
        normalized: list[dict] = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                norm = normalizer(raw)
                if norm is not None:
                    normalized.append(norm)
        print(f"  compliant records: {len(normalized)}")
        sample = stratified_sample(normalized, args.n_per_corpus, seed=args.seed)
        print(f"  sampled {len(sample)} stratified")
        manifest_entries = write_batches(label, sample)
        print(f"  wrote {len(manifest_entries)} batches")
        full_manifest.extend(manifest_entries)

    manifest_path = ROOT / "judge_manifest_corpus_audit.json"
    with open(manifest_path, "w") as f:
        json.dump(full_manifest, f, indent=2)
    print(f"\nManifest: {manifest_path}")
    print(f"Total batches: {len(full_manifest)}, total items: {sum(m['n_items'] for m in full_manifest)}")


if __name__ == "__main__":
    main()
