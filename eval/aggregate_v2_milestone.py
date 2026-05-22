"""
Aggregate SFT v2 milestone judge outputs into a head-to-head v1-vs-v2 table.

For each bench (stress / cx_patched / holdout), reads:
  - eval/judge_output_sft_v2/<bench>_batch_*.jsonl  (subagent scores)
  - eval/judge_input_sft_v2/<bench>_truth.json     (opaque_id -> system, etc.)

Computes per-system, per-dimension means + Ns, plus a parse-success rate
for v2 (from the truth file's `parse_ok` flag). Prints a compact table and
writes eval/results/sft_v2_milestone_aggregate.json.

The headline decision (v2 success or fallback to special tokens) is based
on two thresholds:
  - parse_failure_rate on v2 outputs <= 5% (or fallback kicks in)
  - engagement on stress >= 1.0 (up from v1's 0.13)

Usage:
    python -m eval.aggregate_v2_milestone --benches stress cx_patched holdout
"""

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path("/Users/bbaum/Documents/_RCDS/compression/eval")
JUDGE_OUT = ROOT / "judge_output_sft_v2"
JUDGE_IN = ROOT / "judge_input_sft_v2"
DIMS = ["engagement", "coherence", "substance", "expressive_adequacy"]

# v1-SFT May-5/7 reference points for delta computation. From session_status.md.
V1_REFERENCE = {
    "holdout":    {"engagement": 2.08, "coherence": 3.34, "substance": 2.26, "expressive_adequacy": 3.17},
    "stress":     {"engagement": 0.13, "coherence": None, "substance": None, "expressive_adequacy": None},
    "cx_patched": {"engagement": None, "coherence": None, "substance": None, "expressive_adequacy": None},
}


def load_bench(bench_name: str) -> dict:
    truth_path = JUDGE_IN / f"{bench_name}_truth.json"
    if not truth_path.exists():
        return {}
    truth = json.load(open(truth_path))
    scores = []
    for path in sorted(JUDGE_OUT.glob(f"{bench_name}_batch_*.jsonl")):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                scores.append(json.loads(line))

    by_system: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    parse_ok_v2 = []
    for s in scores:
        opaque = s.get("id")
        entry = truth.get(opaque)
        if entry is None:
            continue
        system = entry["system"]
        if system == "v2" and entry.get("parse_ok") is not None:
            parse_ok_v2.append(entry["parse_ok"])
        for dim in DIMS:
            d = s.get(dim)
            if not d or "score" not in d:
                continue
            try:
                score = int(d["score"])
            except (TypeError, ValueError):
                continue
            by_system[system][dim].append(score)

    out = {}
    for system, dims in by_system.items():
        per_dim = {}
        for dim in DIMS:
            vals = dims[dim]
            if not vals:
                continue
            per_dim[dim] = {
                "mean": round(statistics.mean(vals), 3),
                "stdev": round(statistics.stdev(vals), 3) if len(vals) > 1 else 0.0,
                "n": len(vals),
            }
        out[system] = per_dim
    if parse_ok_v2:
        out["_v2_parse_success_rate"] = round(sum(parse_ok_v2) / len(parse_ok_v2), 4)
        out["_v2_parse_n"] = len(parse_ok_v2)
    return out


def print_table(bench_name: str, agg: dict):
    if not agg:
        print(f"{bench_name}: no data")
        return
    print(f"\n=== {bench_name} ===")
    print(f"{'system':<14} {'engage':>8} {'coher':>8} {'subst':>8} {'expr':>8} {'n':>5}")
    print("-" * 56)
    for sysname in ["v1", "v2"]:
        if sysname not in agg:
            continue
        row = [sysname]
        n0 = None
        for dim in DIMS:
            e = agg[sysname].get(dim, {})
            row.append(f"{e.get('mean', float('nan')):.2f}")
            if n0 is None:
                n0 = e.get("n", 0)
        row.append(str(n0 or 0))
        print(f"{row[0]:<14} {row[1]:>8} {row[2]:>8} {row[3]:>8} {row[4]:>8} {row[5]:>5}")

    # v1 reference (May 5/7 numbers)
    ref = V1_REFERENCE.get(bench_name)
    if ref:
        cells = [f"{ref.get(d):.2f}" if ref.get(d) is not None else "—" for d in DIMS]
        print(f"{'v1_ref_may5/7':<14} {cells[0]:>8} {cells[1]:>8} {cells[2]:>8} {cells[3]:>8}")

    # Delta v2 - v1
    if "v1" in agg and "v2" in agg:
        deltas = []
        for dim in DIMS:
            v1 = agg["v1"].get(dim, {}).get("mean")
            v2 = agg["v2"].get(dim, {}).get("mean")
            if v1 is not None and v2 is not None:
                deltas.append(f"{v2 - v1:+.2f}")
            else:
                deltas.append("—")
        print(f"{'Δ (v2-v1)':<14} {deltas[0]:>8} {deltas[1]:>8} {deltas[2]:>8} {deltas[3]:>8}")

    # Parse success
    if "_v2_parse_success_rate" in agg:
        rate = agg["_v2_parse_success_rate"]
        n = agg["_v2_parse_n"]
        flag = "✓" if rate >= 0.95 else "⚠"
        print(f"  v2 parse-success: {rate:.1%} ({n} records)  {flag}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--benches", nargs="+", default=["stress", "cx_patched", "holdout"])
    args = parser.parse_args()

    full = {}
    for bench in args.benches:
        agg = load_bench(bench)
        full[bench] = agg
        print_table(bench, agg)

    # Top-level summary verdict
    print("\n=== Verdict (against pre-registered criteria) ===")
    stress_eng = full.get("stress", {}).get("v2", {}).get("engagement", {}).get("mean")
    if stress_eng is not None:
        v1_stress_eng = V1_REFERENCE["stress"]["engagement"]
        success = stress_eng >= 1.0
        print(f"  Stress engagement v2={stress_eng:.2f} (v1 ref {v1_stress_eng})  "
              f"{'PASS' if success else 'FAIL'} (need >= 1.0)")
    parse_rates = [
        full.get(b, {}).get("_v2_parse_success_rate")
        for b in args.benches
        if full.get(b, {}).get("_v2_parse_success_rate") is not None
    ]
    if parse_rates:
        min_rate = min(parse_rates)
        success = min_rate >= 0.95
        print(f"  Min v2 parse-success across benches: {min_rate:.1%}  "
              f"{'PASS' if success else 'FAIL — falls back to special tokens'} (need >= 95%)")

    out_path = ROOT / "results" / "sft_v2_milestone_aggregate.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(full, f, indent=2)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
