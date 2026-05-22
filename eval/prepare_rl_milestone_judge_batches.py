"""
Prepare blinded judge batches for the RL-final vs SFT-v2 head-to-head.

Pre-registered Step 3 of the RL eval (docs/next-session-pickup.md): after the
RL v3 self-play run hit the Option-B pivot threshold, confirm the training-reward
read on held-out benches by judging RL-final against SFT-v2 on the Reasoner rubric.

Both systems share the SFT-v2 generation format (record has `prompt`,
`ugf_response`, `parse_ok`), so we reuse the v2 loader for both. The only
difference vs prepare_v2_milestone_judge_batches.py is the two systems compared
and the output dirs.

Outputs:
  eval/judge_input_sft_v2_rl/<bench>_batch_NN.jsonl  — blinded judge inputs
  eval/judge_input_sft_v2_rl/<bench>_truth.json      — opaque_id -> {system, bench, original_id, parse_ok}

Then parallel Claude subagents read the blinded inputs against eval/rubric.md
and write to eval/judge_output_sft_v2_rl/<bench>_batch_NN.jsonl.
aggregate_rl_milestone.py joins via the truth file.

Usage:
    python -m eval.prepare_rl_milestone_judge_batches \\
        --bench-name stress \\
        --sftv2-jsonl eval/results/sft_v2_stress_norep_<ts>.jsonl \\
        --rl-jsonl    eval/results/rl_v3_stress_norep_<ts>.jsonl
"""

import argparse
import json
import random
from collections import Counter
from pathlib import Path

ROOT = Path("/Users/bbaum/Documents/_RCDS/compression/eval")
OUT = ROOT / "judge_input_sft_v2_rl"
JUDGE_OUT = ROOT / "judge_output_sft_v2_rl"
BATCH_SIZE = 30
SEED = 20260522


def load_v2(path: Path, system: str) -> list[dict]:
    """v2-format records: `id`, `prompt`, `ugf_response`, parsed `parse_ok`."""
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
    parser.add_argument("--bench-name", required=True,
                        help="Short label for this bench (stress / cx_patched / holdout).")
    parser.add_argument("--sftv2-jsonl", required=True, help="SFT-v2 (norep) generations JSONL")
    parser.add_argument("--rl-jsonl", required=True, help="RL-final (norep) generations JSONL")
    args = parser.parse_args()

    base = load_v2(Path(args.sftv2_jsonl), "sftv2")
    treat = load_v2(Path(args.rl_jsonl), "rl")
    print(f"Loaded sftv2: {len(base)} from {args.sftv2_jsonl}")
    print(f"Loaded rl:    {len(treat)} from {args.rl_jsonl}")

    items = base + treat
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
                opaque_id = f"rl-{args.bench_name}-{b:02d}-{j:02d}"
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
    c = Counter(v["system"] for v in truth.values())
    print(f"Per-system: {dict(c)}")


if __name__ == "__main__":
    main()
