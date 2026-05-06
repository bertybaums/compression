"""
Aggregate the 16 judge-output JSONL files into per-system summary statistics.

Joins judge scores back to the source items so we can break out by `type`
(content category from the original benchmark file). Computes:

- Per-system, per-dimension means (Reasoner-textbook, Comparator-textbook,
  Reasoner-holdout, Comparator-holdout)
- Reasoner-vs-Comparator deltas, per-dimension, per-benchmark
- Per-type breakdowns (within each benchmark)
- Score distributions (histogram of 0/1/2/3/4 per dimension per system)

Outputs:
- eval/results/judge_aggregate.json — full structured aggregate
- prints a compact summary to stdout
"""

import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path("/Users/bbaum/Documents/_RCDS/compression/eval")
JUDGE_OUT = ROOT / "judge_output"
RESULTS = ROOT / "results" / "_jsonl"

# Map system label → source file (for `type` lookup)
SOURCE_FILES = {
    "reasoner_textbook": RESULTS / "logic_bench_20260505_143235.jsonl",
    "comparator_textbook": RESULTS / "comparator_logic_textbook_20260505_143019_with_english.jsonl",
    "reasoner_holdout": RESULTS / "logic_bench_20260505_152347.jsonl",
    "comparator_holdout": RESULTS / "comparator_holdout_20260505_152335_with_english.jsonl",
}

DIMENSIONS = ["engagement", "coherence", "substance", "expressive_adequacy"]


def load_source_types(label):
    """Return {id: type} from the source benchmark file."""
    out = {}
    with open(SOURCE_FILES[label]) as fh:
        for line in fh:
            r = json.loads(line)
            out[r["id"]] = r.get("type", "unknown")
    return out


def load_judge_scores(label):
    """Load all batches for a label, return list of score dicts."""
    out = []
    batches = sorted(JUDGE_OUT.glob(f"{label}_batch_*.jsonl"))
    for path in batches:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                out.append(json.loads(line))
    return out


def mean(xs):
    return statistics.mean(xs) if xs else float("nan")


def hist(xs):
    h = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
    for x in xs:
        h[x] = h.get(x, 0) + 1
    return h


def summarize_system(label):
    type_lookup = load_source_types(label)
    scores = load_judge_scores(label)

    expected_n = len(type_lookup)
    received_n = len(scores)

    # Per-dimension all-items scores
    per_dim = {d: [] for d in DIMENSIONS}
    # Per-type, per-dimension scores
    per_type_dim = defaultdict(lambda: {d: [] for d in DIMENSIONS})

    seen_ids = set()
    for s in scores:
        item_id = s["id"]
        if item_id in seen_ids:
            continue
        seen_ids.add(item_id)
        item_type = type_lookup.get(item_id, "unknown")
        for d in DIMENSIONS:
            score_val = s[d]["score"]
            per_dim[d].append(score_val)
            per_type_dim[item_type][d].append(score_val)

    return {
        "label": label,
        "expected_n": expected_n,
        "received_n": received_n,
        "scored_n": len(seen_ids),
        "per_dim_mean": {d: round(mean(per_dim[d]), 3) for d in DIMENSIONS},
        "per_dim_hist": {d: hist(per_dim[d]) for d in DIMENSIONS},
        "per_type": {
            t: {
                "n": len(d_scores[DIMENSIONS[0]]),
                "mean": {d: round(mean(d_scores[d]), 3) for d in DIMENSIONS},
            }
            for t, d_scores in per_type_dim.items()
        },
    }


def main():
    summaries = {label: summarize_system(label) for label in SOURCE_FILES}

    # Compute deltas per benchmark (Reasoner - Comparator)
    deltas = {}
    for bench in ["textbook", "holdout"]:
        r = summaries[f"reasoner_{bench}"]["per_dim_mean"]
        c = summaries[f"comparator_{bench}"]["per_dim_mean"]
        deltas[bench] = {d: round(r[d] - c[d], 3) for d in DIMENSIONS}

    # Per-type deltas
    per_type_deltas = {}
    for bench in ["textbook", "holdout"]:
        r_types = summaries[f"reasoner_{bench}"]["per_type"]
        c_types = summaries[f"comparator_{bench}"]["per_type"]
        common = set(r_types) & set(c_types)
        per_type_deltas[bench] = {
            t: {
                "n": min(r_types[t]["n"], c_types[t]["n"]),
                "delta": {
                    d: round(r_types[t]["mean"][d] - c_types[t]["mean"][d], 3)
                    for d in DIMENSIONS
                },
                "reasoner_mean": r_types[t]["mean"],
                "comparator_mean": c_types[t]["mean"],
            }
            for t in sorted(common)
        }

    aggregate = {
        "summaries": summaries,
        "deltas": deltas,
        "per_type_deltas": per_type_deltas,
    }

    out_path = ROOT / "results" / "judge_aggregate.json"
    with open(out_path, "w") as fh:
        json.dump(aggregate, fh, indent=2)
    print(f"Wrote {out_path}")

    print()
    print("=" * 70)
    print("Per-system per-dimension means")
    print("=" * 70)
    cols = ["system", "n"] + DIMENSIONS
    print(f"{'system':<25} {'n':>5}  " + "  ".join(f"{d[:8]:>8}" for d in DIMENSIONS))
    for label, s in summaries.items():
        means = s["per_dim_mean"]
        print(f"{label:<25} {s['scored_n']:>5}  " + "  ".join(f"{means[d]:>8.2f}" for d in DIMENSIONS))

    print()
    print("=" * 70)
    print("Reasoner − Comparator (per benchmark)")
    print("=" * 70)
    print(f"{'benchmark':<12}  " + "  ".join(f"{d[:8]:>8}" for d in DIMENSIONS))
    for bench, dlt in deltas.items():
        marker = lambda v: f"{'+' if v >= 0 else ''}{v:.2f}"
        print(f"{bench:<12}  " + "  ".join(f"{marker(dlt[d]):>8}" for d in DIMENSIONS))

    print()
    print("=" * 70)
    print("Per-type deltas (Reasoner − Comparator) — TEXTBOOK")
    print("=" * 70)
    for t, info in per_type_deltas["textbook"].items():
        marker = lambda v: f"{'+' if v >= 0 else ''}{v:.2f}"
        print(f"  {t:<32} n={info['n']:>3}  " + "  ".join(f"{marker(info['delta'][d]):>7}" for d in DIMENSIONS))

    print()
    print("=" * 70)
    print("Per-type deltas (Reasoner − Comparator) — HOLDOUT")
    print("=" * 70)
    for t, info in per_type_deltas["holdout"].items():
        marker = lambda v: f"{'+' if v >= 0 else ''}{v:.2f}"
        print(f"  {t:<32} n={info['n']:>3}  " + "  ".join(f"{marker(info['delta'][d]):>7}" for d in DIMENSIONS))


if __name__ == "__main__":
    main()
