"""
Sample representative scored examples for the Layer-3 report.

Picks for each system:
- 1 high (sum of 4 dims >= 14)
- 1 mid (sum 8-12)
- 1 low (sum <= 6)

Joins judge scores back to original english_query + ugf_response so the report
can show what was scored.
"""

import json
import random
from pathlib import Path

ROOT = Path("/Users/bbaum/Documents/_RCDS/compression/eval")
JUDGE_OUT = ROOT / "judge_output"
RESULTS = ROOT / "results" / "_jsonl"

SOURCES = {
    "reasoner_textbook": RESULTS / "logic_bench_20260505_143235.jsonl",
    "comparator_textbook": RESULTS / "comparator_logic_textbook_20260505_143019_with_english.jsonl",
    "reasoner_holdout": RESULTS / "logic_bench_20260505_152347.jsonl",
    "comparator_holdout": RESULTS / "comparator_holdout_20260505_152335_with_english.jsonl",
}

DIMS = ["engagement", "coherence", "substance", "expressive_adequacy"]


def load_source(label):
    return {json.loads(l)["id"]: json.loads(l) for l in open(SOURCES[label])}


def load_scores(label):
    out = []
    for path in sorted(JUDGE_OUT.glob(f"{label}_batch_*.jsonl")):
        out.extend(json.loads(l) for l in open(path) if l.strip())
    return out


def sample(label, seed=42):
    src = load_source(label)
    scores = load_scores(label)
    rng = random.Random(seed)

    high = [s for s in scores if sum(s[d]["score"] for d in DIMS) >= 14]
    mid = [s for s in scores if 8 <= sum(s[d]["score"] for d in DIMS) <= 12]
    low = [s for s in scores if sum(s[d]["score"] for d in DIMS) <= 6]

    out = {}
    for tier, pool in [("high", high), ("mid", mid), ("low", low)]:
        if pool:
            picked = rng.choice(pool)
            item = src.get(picked["id"], {})
            out[tier] = {
                "id": picked["id"],
                "type": item.get("type", "unknown"),
                "english_query": item.get("english_query", ""),
                "ugf_response": item.get("ugf_response", ""),
                "scores": {d: picked[d] for d in DIMS},
                "notes": picked.get("notes", ""),
                "tier_count": len(pool),
            }
        else:
            out[tier] = None
    return out


def main():
    samples = {label: sample(label) for label in SOURCES}
    out_path = ROOT / "results" / "judge_examples.json"
    with open(out_path, "w") as fh:
        json.dump(samples, fh, indent=2)
    print(f"Wrote {out_path}")
    for label, s in samples.items():
        print(f"\n{label}:")
        for tier in ["high", "mid", "low"]:
            if s[tier]:
                print(f"  {tier}: id={s[tier]['id']} ({s[tier]['tier_count']} items in tier)")
            else:
                print(f"  {tier}: (none)")


if __name__ == "__main__":
    main()
