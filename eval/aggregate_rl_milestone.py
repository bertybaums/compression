"""
Aggregate RL-final vs SFT-v2 judge outputs into a head-to-head table.

For each bench (stress / cx_patched / holdout), reads:
  - eval/judge_output_sft_v2_rl/<bench>_batch_*.jsonl  (subagent scores)
  - eval/judge_input_sft_v2_rl/<bench>_truth.json      (opaque_id -> system, etc.)

Computes per-system, per-dimension means + Ns. Prints a compact table with the
RL−SFTv2 delta and writes eval/results/rl_milestone_aggregate.json.

The head-to-head that matters (pre-registered): RL vs SFT-v2 on engagement +
substance (the heavily-weighted reward dims, 0.2 and 0.6). If RL moved those up
on held-out benches, the self-play loop delivered a real bench gain despite the
flat training-reward trend; if not, it confirms the Option-B pivot.

Usage:
    python -m eval.aggregate_rl_milestone --benches stress cx_patched holdout
"""

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path("/Users/bbaum/Documents/_RCDS/compression/eval")
JUDGE_OUT = ROOT / "judge_output_sft_v2_rl"
JUDGE_IN = ROOT / "judge_input_sft_v2_rl"
DIMS = ["engagement", "coherence", "substance", "expressive_adequacy"]
SYSTEMS = ["sftv2", "rl"]


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
            if not vals:
                continue
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

    if "sftv2" in agg and "rl" in agg:
        deltas = []
        for dim in DIMS:
            a = agg["sftv2"].get(dim, {}).get("mean")
            b = agg["rl"].get(dim, {}).get("mean")
            deltas.append(f"{b - a:+.2f}" if a is not None and b is not None else "—")
        print(f"{'Δ (rl-sftv2)':<14} {deltas[0]:>8} {deltas[1]:>8} {deltas[2]:>8} {deltas[3]:>8}")

    for sysname in SYSTEMS:
        key = f"_{sysname}_parse_success_rate"
        if key in agg:
            rate = agg[key]
            n = agg[f"_{sysname}_parse_n"]
            flag = "✓" if rate >= 0.95 else "⚠"
            print(f"  {sysname} parse-success: {rate:.1%} ({n} records)  {flag}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--benches", nargs="+", default=["stress", "cx_patched", "holdout"])
    args = parser.parse_args()

    full = {}
    for bench in args.benches:
        agg = load_bench(bench)
        full[bench] = agg
        print_table(bench, agg)

    # Pre-registered verdict: did RL move the weighted dims (substance 0.6, engagement 0.2)?
    print("\n=== Verdict (RL vs SFT-v2 on weighted dims) ===")
    for dim in ["substance", "engagement"]:
        gains = []
        for bench in args.benches:
            a = full.get(bench, {}).get("sftv2", {}).get(dim, {}).get("mean")
            b = full.get(bench, {}).get("rl", {}).get(dim, {}).get("mean")
            if a is not None and b is not None:
                gains.append((bench, b - a))
        if gains:
            tot = sum(g for _, g in gains) / len(gains)
            detail = "  ".join(f"{bn}:{g:+.2f}" for bn, g in gains)
            verdict = "RL ahead" if tot > 0.05 else ("parity" if tot > -0.05 else "RL behind")
            print(f"  {dim:<12} mean Δ {tot:+.2f}  [{detail}]  -> {verdict}")

    out_path = ROOT / "results" / "rl_milestone_aggregate.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(full, f, indent=2)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
