"""
Prepare blinded judge batches for the SFT v2 milestone eval.

For each bench (stress / cx-patched / holdout), pairs v1 Reasoner
generations (May 5/6) with v2 Reasoner generations (this run) into mixed
batches with opaque ids. Subagent judges score each generation on the
Reasoner 4-dim rubric without seeing which system produced it.

Outputs:
  eval/judge_input_sft_v2/<bench>_batch_NN.jsonl  — blinded judge inputs
  eval/judge_input_sft_v2/<bench>_truth.json     — opaque_id -> {system, bench, original_id}

Then 12-ish parallel Claude subagents read the blinded inputs against
eval/rubric.md and write to eval/judge_output_sft_v2/<bench>_batch_NN.jsonl.
The aggregator joins via the truth file.

Usage:
    python -m eval.prepare_v2_milestone_judge_batches \\
        --bench-name stress \\
        --v1-jsonl eval/results/_jsonl/stress_bench_reasoner_20260506_210418.jsonl \\
        --v2-jsonl eval/results/sft_v2_stress_20260518_HHMMSS.jsonl
"""

import argparse
import json
import random
from pathlib import Path

ROOT = Path("/Users/bbaum/Documents/_RCDS/compression/eval")
OUT = ROOT / "judge_input_sft_v2"
JUDGE_OUT = ROOT / "judge_output_sft_v2"
BATCH_SIZE = 30
SEED = 20260518


def load_v1(path: Path) -> list[dict]:
    """v1 records have `id`, `ugf_response`, and `english_query` (or `question`+`instruction`)."""
    items = []
    with open(path) as f:
        for line in f:
            r = json.loads(line)
            text = r.get("english_query") or r.get("question") or r.get("prompt") or ""
            ugf = r.get("ugf_response", "") or ""
            if not ugf or ugf.startswith("<"):
                continue
            items.append({"original_id": r["id"], "english_query": text, "ugf_response": ugf, "system": "v1"})
    return items


def load_v2(path: Path) -> list[dict]:
    """v2 records have `id`, `prompt`, `ugf_response`, plus parsed `reasoning`/`answer`/`parse_ok`."""
    items = []
    with open(path) as f:
        for line in f:
            r = json.loads(line)
            ugf = r.get("ugf_response", "") or ""
            if not ugf or ugf.startswith("<"):
                continue
            items.append({
                "original_id": r["id"],
                "english_query": r.get("prompt", ""),
                "ugf_response": ugf,
                "system": "v2",
                "parse_ok": r.get("parse_ok", False),
            })
    return items


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bench-name", required=True,
                        help="Short label for this bench (e.g., 'stress', 'cx_patched', 'holdout').")
    parser.add_argument("--v1-jsonl", required=True, help="v1 Reasoner generations JSONL")
    parser.add_argument("--v2-jsonl", required=True, help="v2 Reasoner generations JSONL")
    args = parser.parse_args()

    v1 = load_v1(Path(args.v1_jsonl))
    v2 = load_v2(Path(args.v2_jsonl))
    print(f"Loaded v1: {len(v1)} from {args.v1_jsonl}")
    print(f"Loaded v2: {len(v2)} from {args.v2_jsonl}")

    items = v1 + v2
    rng = random.Random(SEED)
    rng.shuffle(items)

    OUT.mkdir(exist_ok=True)
    JUDGE_OUT.mkdir(exist_ok=True)

    truth = {}
    n_batches = (len(items) + BATCH_SIZE - 1) // BATCH_SIZE
    for b in range(n_batches):
        chunk = items[b * BATCH_SIZE : (b + 1) * BATCH_SIZE]
        out_path = OUT / f"{args.bench_name}_batch_{b+1:02d}.jsonl"
        with open(out_path, "w") as f:
            for j, item in enumerate(chunk):
                opaque_id = f"v2-{args.bench_name}-{b:02d}-{j:02d}"
                truth[opaque_id] = {
                    "system": item["system"],
                    "bench": args.bench_name,
                    "original_id": item["original_id"],
                    "parse_ok": item.get("parse_ok"),
                }
                f.write(json.dumps({
                    "id": opaque_id,
                    "english_query": item["english_query"],
                    "ugf_response": item["ugf_response"],
                }) + "\n")
        print(f"  {out_path.name}: {len(chunk)} items")

    truth_path = OUT / f"{args.bench_name}_truth.json"
    with open(truth_path, "w") as f:
        json.dump(truth, f, indent=2)
    print(f"Wrote {n_batches} blinded batches and truth map {truth_path}")
    from collections import Counter
    c = Counter(v["system"] for v in truth.values())
    print(f"Per-system: {dict(c)}")


if __name__ == "__main__":
    main()
