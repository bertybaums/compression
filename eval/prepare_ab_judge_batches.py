"""
General blinded A/B judge-batch prep. Parameterized by two labeled systems, so
any head-to-head reuses it (supersedes the bespoke prepare_{v2,rl,dpo}_milestone
scripts). Both inputs are run_sft_v2_bench-format JSONL (id, prompt, ugf_response,
parse_ok). Opaque ids carry only the experiment tag, never the system label.

Outputs (under --in-dir, default eval/judge_input_ab):
  <bench>_batch_NN.jsonl  — blinded judge inputs (id, english_query, ugf_response)
  <bench>_truth.json      — opaque_id -> {system, bench, original_id, parse_ok}

Then parallel Claude judges score against eval/rubric.md into --out-dir
(default eval/judge_output_ab); aggregate_ab.py joins via the truth file.

Usage:
    python -m eval.prepare_ab_judge_batches --bench-name stress --tag formpilot \\
        --a form  --a-jsonl eval/results/sft_form_stress_norep_<ts>.jsonl \\
        --b essay --b-jsonl eval/results/sft_essay_stress_norep_<ts>.jsonl
"""

import argparse
import json
import random
from collections import Counter
from pathlib import Path

ROOT = Path("/Users/bbaum/Documents/_RCDS/compression/eval")
BATCH_SIZE = 30
SEED = 20260524


def load(path: Path, system: str) -> list[dict]:
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
                "parse_ok": r.get("parse_ok"),
            })
    return items


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--bench-name", required=True)
    p.add_argument("--tag", default="ab", help="Opaque-id namespace (no system info).")
    p.add_argument("--a", required=True, help="system A label")
    p.add_argument("--a-jsonl", required=True)
    p.add_argument("--b", required=True, help="system B label")
    p.add_argument("--b-jsonl", required=True)
    p.add_argument("--in-dir", default=str(ROOT / "judge_input_ab"))
    p.add_argument("--out-dir", default=str(ROOT / "judge_output_ab"))
    args = p.parse_args()

    in_dir = Path(args.in_dir); out_dir = Path(args.out_dir)
    in_dir.mkdir(exist_ok=True); out_dir.mkdir(exist_ok=True)

    a = load(Path(args.a_jsonl), args.a)
    b = load(Path(args.b_jsonl), args.b)
    print(f"Loaded {args.a}: {len(a)} | {args.b}: {len(b)}")

    items = a + b
    random.Random(SEED).shuffle(items)

    truth = {}
    n_batches = (len(items) + BATCH_SIZE - 1) // BATCH_SIZE
    for bi in range(n_batches):
        chunk = items[bi * BATCH_SIZE:(bi + 1) * BATCH_SIZE]
        with open(in_dir / f"{args.bench_name}_batch_{bi+1:02d}.jsonl", "w") as f:
            for j, item in enumerate(chunk):
                oid = f"{args.tag}-{args.bench_name}-{bi:02d}-{j:02d}"
                truth[oid] = {"system": item["system"], "bench": args.bench_name,
                              "original_id": item["original_id"], "parse_ok": item.get("parse_ok")}
                f.write(json.dumps({"id": oid, "english_query": item["english_query"],
                                    "ugf_response": item["ugf_response"]}) + "\n")
    with open(in_dir / f"{args.bench_name}_truth.json", "w") as f:
        json.dump(truth, f, indent=2)
    print(f"Wrote {n_batches} batches to {in_dir}; per-system {dict(Counter(v['system'] for v in truth.values()))}")


if __name__ == "__main__":
    main()
