"""
Prepare blinded judge batches for the Stage-1 DPO/APO-final vs SFT-v2 head-to-head.

Same machinery as prepare_rl_milestone_judge_batches.py (the v3 head-to-head),
but compares SFT-v2 against the DPO checkpoint and writes to DPO-specific dirs so
the v3 evidence stays intact. Both systems share the v2 generation format.

Outputs:
  eval/judge_input_sft_v2_dpo/<bench>_batch_NN.jsonl  — blinded judge inputs
  eval/judge_input_sft_v2_dpo/<bench>_truth.json      — opaque_id -> {system, bench, original_id, parse_ok}

Then parallel Claude subagents score against eval/rubric.md into
eval/judge_output_sft_v2_dpo/; aggregate_dpo_milestone.py joins via the truth file.

Usage:
    python -m eval.prepare_dpo_milestone_judge_batches \\
        --bench-name stress \\
        --sftv2-jsonl eval/results/sft_v2_stress_norep_20260519_062446.jsonl \\
        --dpo-jsonl   eval/results/dpo_stress_norep_<ts>.jsonl
"""

import argparse
import json
import random
from collections import Counter
from pathlib import Path

ROOT = Path("/Users/bbaum/Documents/_RCDS/compression/eval")
OUT = ROOT / "judge_input_sft_v2_dpo"
JUDGE_OUT = ROOT / "judge_output_sft_v2_dpo"
BATCH_SIZE = 30
SEED = 20260523


def load_v2(path: Path, system: str) -> list[dict]:
    items = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            ugf = r.get("ugf_response", "") or ""
            if not ugf or ugf.startswith("<"):
                continue
            items.append({
                "original_id": r["id"],
                "english_query": r.get("prompt", ""),
                "ugf_response": ugf,
                "system": system,
                "parse_ok": r.get("parse_ok", False),
            })
    return items


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bench-name", required=True, help="stress / cx_patched / holdout")
    parser.add_argument("--sftv2-jsonl", required=True)
    parser.add_argument("--dpo-jsonl", required=True)
    args = parser.parse_args()

    base = load_v2(Path(args.sftv2_jsonl), "sftv2")
    treat = load_v2(Path(args.dpo_jsonl), "dpo")
    print(f"Loaded sftv2: {len(base)} from {args.sftv2_jsonl}")
    print(f"Loaded dpo:   {len(treat)} from {args.dpo_jsonl}")

    items = base + treat
    random.Random(SEED).shuffle(items)

    OUT.mkdir(exist_ok=True)
    JUDGE_OUT.mkdir(exist_ok=True)

    truth = {}
    n_batches = (len(items) + BATCH_SIZE - 1) // BATCH_SIZE
    for b in range(n_batches):
        chunk = items[b * BATCH_SIZE : (b + 1) * BATCH_SIZE]
        out_path = OUT / f"{args.bench_name}_batch_{b+1:02d}.jsonl"
        with open(out_path, "w") as f:
            for j, item in enumerate(chunk):
                opaque_id = f"dpo-{args.bench_name}-{b:02d}-{j:02d}"
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
    print(f"Per-system: {dict(Counter(v['system'] for v in truth.values()))}")


if __name__ == "__main__":
    main()
