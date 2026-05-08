"""
Analysis of the May 6/7 runs:
- Stress bench (30 items, Reasoner + Comparator)
- Patched-cx (50 items, Reasoner + Comparator)

Reports:
- Per-system per-dimension means
- Reasoner−Comparator deltas (per benchmark)
- Stress: per-category D1-D4 means for both systems + delta
- cx_patched: comparison to original (truncated) cx scores from Layer-3
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


def system_means(label):
    scores = load_label(label)
    return scores, {d: mean([s[d]["score"] for s in scores]) for d in DIMS}


def section_stress():
    print("=" * 70)
    print("STRESS BENCH (Layer-4)")
    print("=" * 70)

    bench = {}
    with open(ROOT / "sets" / "stress_bench.jsonl") as fh:
        for line in fh:
            r = json.loads(line)
            bench[r["id"]] = r

    r_scores, r_means = system_means("reasoner_stress")
    c_scores, c_means = system_means("comparator_stress")

    print(f"\nPer-system means (n_reasoner={len(r_scores)}, n_comparator={len(c_scores)})")
    print(f"  {'system':<12}  " + "  ".join(f"{d[:8]:>8}" for d in DIMS))
    print(f"  {'Reasoner':<12}  " + "  ".join(f"{r_means[d]:>8.2f}" for d in DIMS))
    print(f"  {'Comparator':<12}  " + "  ".join(f"{c_means[d]:>8.2f}" for d in DIMS))
    print(f"  {'Δ (R-C)':<12}  " + "  ".join(f"{(r_means[d] - c_means[d]):>+8.2f}" for d in DIMS))

    # Per-category
    def by_category(scores):
        per = defaultdict(lambda: {d: [] for d in DIMS})
        for s in scores:
            cat = bench.get(s["id"], {}).get("category", "unknown")
            for d in DIMS:
                per[cat][d].append(s[d]["score"])
        return per

    r_by_cat = by_category(r_scores)
    c_by_cat = by_category(c_scores)

    print(f"\nPer-category means (Reasoner | Comparator | Δ)")
    print(f"  {'category':<28}  {'D1 R/C/Δ':>16}  {'D2 R/C/Δ':>16}  {'D3 R/C/Δ':>16}  {'D4 R/C/Δ':>16}")
    for cat in sorted(r_by_cat):
        cells = []
        for d in DIMS:
            r_m = mean(r_by_cat[cat][d])
            c_m = mean(c_by_cat[cat][d])
            cells.append(f"{r_m:.1f}/{c_m:.1f}/{r_m-c_m:+.1f}")
        print(f"  {cat:<28}  " + "  ".join(f"{c:>16}" for c in cells))


def section_cx():
    print()
    print("=" * 70)
    print("PATCHED CX SUBSET (50 items)")
    print("=" * 70)

    r_scores, r_means = system_means("reasoner_cx_patched")
    c_scores, c_means = system_means("comparator_cx_patched")

    print(f"\nPer-system means (n_reasoner={len(r_scores)}, n_comparator={len(c_scores)})")
    print(f"  {'system':<14}  " + "  ".join(f"{d[:8]:>8}" for d in DIMS))
    print(f"  {'Reasoner':<14}  " + "  ".join(f"{r_means[d]:>8.2f}" for d in DIMS))
    print(f"  {'Comparator':<14}  " + "  ".join(f"{c_means[d]:>8.2f}" for d in DIMS))
    print(f"  {'Δ (R-C)':<14}  " + "  ".join(f"{(r_means[d] - c_means[d]):>+8.2f}" for d in DIMS))

    # Compare to original (truncated) cx scores from Layer-3
    bench = {}
    with open(ROOT / "sets" / "holdout_bench.jsonl") as fh:
        for line in fh:
            r = json.loads(line)
            bench[r["id"]] = r
    cx_ids = {rid for rid, r in bench.items() if r.get("type") == "counterexample_analysis"}
    orig_r = [s for s in load_label("reasoner_holdout") if s["id"] in cx_ids]
    orig_c = [s for s in load_label("comparator_holdout") if s["id"] in cx_ids]

    orig_r_means = {d: mean([s[d]["score"] for s in orig_r]) for d in DIMS}
    orig_c_means = {d: mean([s[d]["score"] for s in orig_c]) for d in DIMS}

    print(f"\nOriginal (Layer-3, truncated prompts) cx subset:")
    print(f"  {'system':<14}  " + "  ".join(f"{d[:8]:>8}" for d in DIMS))
    print(f"  {'Reasoner':<14}  " + "  ".join(f"{orig_r_means[d]:>8.2f}" for d in DIMS))
    print(f"  {'Comparator':<14}  " + "  ".join(f"{orig_c_means[d]:>8.2f}" for d in DIMS))
    print(f"  {'Δ (R-C)':<14}  " + "  ".join(f"{(orig_r_means[d] - orig_c_means[d]):>+8.2f}" for d in DIMS))

    print(f"\nPatching effect on each system (NEW − ORIGINAL):")
    print(f"  {'system':<14}  " + "  ".join(f"{d[:8]:>8}" for d in DIMS))
    print(f"  {'Reasoner':<14}  " + "  ".join(f"{(r_means[d] - orig_r_means[d]):>+8.2f}" for d in DIMS))
    print(f"  {'Comparator':<14}  " + "  ".join(f"{(c_means[d] - orig_c_means[d]):>+8.2f}" for d in DIMS))


if __name__ == "__main__":
    section_stress()
    section_cx()
