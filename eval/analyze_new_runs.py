"""
Quick analysis of the May 6 comparator runs:
- Stress bench (30 items, comparator only — Reasoner side pending fortyfive)
- Patched-cx (50 items, comparator only — Reasoner side pending fortyfive)

Reports:
- comparator_stress: per-category D1-D4 means (the diagnostic for which UGF
  categories the 120B teacher itself can/can't carry well)
- comparator_cx_patched: overall D1-D4 means + comparison to the original
  (truncated) cx subset's comparator scores from Layer-3
"""

import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path("/Users/bbaum/Documents/_RCDS/compression/eval")
JUDGE_OUT = ROOT / "judge_output"
DIMS = ["engagement", "coherence", "substance", "expressive_adequacy"]


def load_label(label):
    items = []
    for p in sorted(JUDGE_OUT.glob(f"{label}_batch_*.jsonl")):
        with open(p) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    items.append(json.loads(line))
    return items


def mean(xs):
    return statistics.mean(xs) if xs else float("nan")


def stress_per_category():
    # Need to join scores back to original items for category
    bench = {}
    with open(ROOT / "sets" / "stress_bench.jsonl") as fh:
        for line in fh:
            r = json.loads(line)
            bench[r["id"]] = r

    scores = load_label("comparator_stress")
    print(f"comparator_stress: {len(scores)} scored items")

    per_cat = defaultdict(lambda: {d: [] for d in DIMS})
    overall = {d: [] for d in DIMS}
    for s in scores:
        cat = bench.get(s["id"], {}).get("category", "unknown")
        for d in DIMS:
            per_cat[cat][d].append(s[d]["score"])
            overall[d].append(s[d]["score"])

    print()
    print(f"{'category':<28} {'n':>3}  " + "  ".join(f"{d[:8]:>8}" for d in DIMS))
    for cat in sorted(per_cat):
        row = per_cat[cat]
        n = len(row[DIMS[0]])
        print(f"  {cat:<26} {n:>3}  " + "  ".join(f"{mean(row[d]):>8.2f}" for d in DIMS))
    print(f"  {'OVERALL':<26} {len(scores):>3}  " + "  ".join(f"{mean(overall[d]):>8.2f}" for d in DIMS))
    return overall


def cx_patched_vs_original():
    # New patched comparator
    new_scores = load_label("comparator_cx_patched")
    print(f"\ncomparator_cx_patched (NEW, full definitions): {len(new_scores)} items")
    new_means = {d: mean([s[d]["score"] for s in new_scores]) for d in DIMS}
    print(f"  " + "  ".join(f"{d[:8]:>8}" for d in DIMS))
    print(f"  " + "  ".join(f"{new_means[d]:>8.2f}" for d in DIMS))

    # Original (truncated) comparator scores on cx items, from Layer-3
    # Filter comparator_holdout scores by ids that match cxbot- counterexample items
    bench = {}
    with open(ROOT / "sets" / "holdout_bench.jsonl") as fh:
        for line in fh:
            r = json.loads(line)
            bench[r["id"]] = r
    cx_ids = {rid for rid, r in bench.items() if r.get("type") == "counterexample_analysis"}

    orig_scores = [s for s in load_label("comparator_holdout") if s["id"] in cx_ids]
    print(f"\ncomparator_holdout (ORIGINAL, truncated definitions, cx subset): {len(orig_scores)} items")
    orig_means = {d: mean([s[d]["score"] for s in orig_scores]) for d in DIMS}
    print(f"  " + "  ".join(f"{orig_means[d]:>8.2f}" for d in DIMS))

    print(f"\nDelta (NEW − ORIGINAL): how much did patching the prompts help?")
    print(f"  " + "  ".join(f"{(new_means[d] - orig_means[d]):>+8.2f}" for d in DIMS))


if __name__ == "__main__":
    stress_per_category()
    cx_patched_vs_original()
