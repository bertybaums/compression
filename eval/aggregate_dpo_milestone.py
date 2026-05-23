"""
Aggregate Stage-1 DPO/APO-final vs SFT-v2 judge outputs into a head-to-head table.

Mirrors aggregate_rl_milestone.py but for the DPO checkpoint, reading the
DPO-specific dirs and writing dpo_milestone_aggregate.json.

Pre-registered success (docs/dpo-stage1-design-2026-05-22.md): engagement and
substance Δ (dpo − sftv2) both >= 0, with engagement clearly up on stress +
cx_patched (where v3 regressed −0.40 / −0.80). Directly comparable to the v3
result in rl_milestone_aggregate.json.

Usage:
    python -m eval.aggregate_dpo_milestone --benches stress cx_patched holdout
"""

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path("/Users/bbaum/Documents/_RCDS/compression/eval")
JUDGE_OUT = ROOT / "judge_output_sft_v2_dpo"
JUDGE_IN = ROOT / "judge_input_sft_v2_dpo"
DIMS = ["engagement", "coherence", "substance", "expressive_adequacy"]
SYSTEMS = ["sftv2", "dpo"]


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
                if line:
                    scores.append(json.loads(line))

    by_system: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    parse_ok = defaultdict(list)
    for s in scores:
        entry = truth.get(s.get("id"))
        if entry is None:
            continue
        system = entry["system"]
        if entry.get("parse_ok") is not None:
            parse_ok[system].append(entry["parse_ok"])
        for dim in DIMS:
            d = s.get(dim)
            if not d or "score" not in d:
                continue
            try:
                by_system[system][dim].append(int(d["score"]))
            except (TypeError, ValueError):
                continue

    out = {}
    for system, dims in by_system.items():
        per_dim = {}
        for dim in DIMS:
            vals = dims[dim]
            if vals:
                per_dim[dim] = {
                    "mean": round(statistics.mean(vals), 3),
                    "stdev": round(statistics.stdev(vals), 3) if len(vals) > 1 else 0.0,
                    "n": len(vals),
                }
        out[system] = per_dim
    for system, oks in parse_ok.items():
        if oks:
            out[f"_{system}_parse_success_rate"] = round(sum(oks) / len(oks), 4)
            out[f"_{system}_parse_n"] = len(oks)
    return out


def print_table(bench_name: str, agg: dict):
    if not agg:
        print(f"{bench_name}: no data")
        return
    print(f"\n=== {bench_name} ===")
    print(f"{'system':<14} {'engage':>8} {'coher':>8} {'subst':>8} {'expr':>8} {'n':>5}")
    print("-" * 56)
    for sysname in SYSTEMS:
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

    if "sftv2" in agg and "dpo" in agg:
        deltas = []
        for dim in DIMS:
            a = agg["sftv2"].get(dim, {}).get("mean")
            b = agg["dpo"].get(dim, {}).get("mean")
            deltas.append(f"{b - a:+.2f}" if a is not None and b is not None else "—")
        print(f"{'Δ (dpo-sftv2)':<14} {deltas[0]:>8} {deltas[1]:>8} {deltas[2]:>8} {deltas[3]:>8}")

    for sysname in SYSTEMS:
        key = f"_{sysname}_parse_success_rate"
        if key in agg:
            rate = agg[key]; n = agg[f"_{sysname}_parse_n"]
            print(f"  {sysname} parse-success: {rate:.1%} ({n} records)  {'✓' if rate >= 0.95 else '⚠'}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--benches", nargs="+", default=["stress", "cx_patched", "holdout"])
    args = parser.parse_args()

    full = {}
    for bench in args.benches:
        agg = load_bench(bench)
        full[bench] = agg
        print_table(bench, agg)

    print("\n=== Verdict (DPO vs SFT-v2 on weighted dims; pre-registered ≥ 0) ===")
    for dim in ["substance", "engagement"]:
        gains = []
        for bench in args.benches:
            a = full.get(bench, {}).get("sftv2", {}).get(dim, {}).get("mean")
            b = full.get(bench, {}).get("dpo", {}).get(dim, {}).get("mean")
            if a is not None and b is not None:
                gains.append((bench, b - a))
        if gains:
            tot = sum(g for _, g in gains) / len(gains)
            detail = "  ".join(f"{bn}:{g:+.2f}" for bn, g in gains)
            verdict = "DPO ahead" if tot > 0.05 else ("parity" if tot > -0.05 else "DPO behind")
            print(f"  {dim:<12} mean Δ {tot:+.2f}  [{detail}]  -> {verdict}")

    out_path = ROOT / "results" / "dpo_milestone_aggregate.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(full, f, indent=2)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
