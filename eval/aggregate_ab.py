"""
General A/B judge-score aggregator (pairs with prepare_ab_judge_batches.py).

Reads blinded judge outputs + truth, reports per-system 4-dim means and the
B−A delta per bench and overall. Parameterized by the two system labels.

Usage:
    python -m eval.aggregate_ab --tag formpilot --a essay --b form \\
        --benches stress cx_patched holdout
"""

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path("/Users/bbaum/Documents/_RCDS/compression/eval")
DIMS = ["engagement", "coherence", "substance", "expressive_adequacy"]


def load_bench(bench, in_dir, out_dir):
    truth_path = in_dir / f"{bench}_truth.json"
    if not truth_path.exists():
        return {}
    truth = json.load(open(truth_path))
    scores = []
    for path in sorted(out_dir.glob(f"{bench}_batch_*.jsonl")):
        with open(path) as f:
            scores += [json.loads(l) for l in f if l.strip()]
    by_sys = defaultdict(lambda: defaultdict(list))
    parse_ok = defaultdict(list)
    for s in scores:
        e = truth.get(s.get("id"))
        if not e:
            continue
        if e.get("parse_ok") is not None:
            parse_ok[e["system"]].append(e["parse_ok"])
        for dim in DIMS:
            d = s.get(dim)
            if d and "score" in d:
                try:
                    by_sys[e["system"]][dim].append(int(d["score"]))
                except (TypeError, ValueError):
                    pass
    out = {}
    for sysname, dims in by_sys.items():
        out[sysname] = {dim: {"mean": round(statistics.mean(v), 3), "n": len(v)}
                        for dim, v in dims.items() if v}
    for sysname, oks in parse_ok.items():
        if oks:
            out[f"_{sysname}_parse"] = round(sum(oks) / len(oks), 4)
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tag", default="ab")
    p.add_argument("--a", required=True, help="system A label (baseline)")
    p.add_argument("--b", required=True, help="system B label (treatment)")
    p.add_argument("--benches", nargs="+", default=["stress", "cx_patched", "holdout"])
    p.add_argument("--in-dir", default=str(ROOT / "judge_input_ab"))
    p.add_argument("--out-dir", default=str(ROOT / "judge_output_ab"))
    args = p.parse_args()
    in_dir = Path(args.in_dir); out_dir = Path(args.out_dir)

    full = {}
    for bench in args.benches:
        agg = load_bench(bench, in_dir, out_dir)
        full[bench] = agg
        if not agg:
            print(f"{bench}: no data"); continue
        print(f"\n=== {bench} ===")
        print(f"{'system':<10} {'engage':>8} {'coher':>8} {'subst':>8} {'expr':>8} {'n':>5}")
        for sysname in (args.a, args.b):
            if sysname not in agg:
                continue
            row = [agg[sysname].get(d, {}).get("mean", float('nan')) for d in DIMS]
            n0 = agg[sysname].get("engagement", {}).get("n", 0)
            print(f"{sysname:<10} {row[0]:>8.2f} {row[1]:>8.2f} {row[2]:>8.2f} {row[3]:>8.2f} {n0:>5}")
        if args.a in agg and args.b in agg:
            d = [agg[args.b].get(dim, {}).get("mean", 0) - agg[args.a].get(dim, {}).get("mean", 0) for dim in DIMS]
            print(f"{'Δ('+args.b+'-'+args.a+')':<10} {d[0]:>+8.2f} {d[1]:>+8.2f} {d[2]:>+8.2f} {d[3]:>+8.2f}")

    print(f"\n=== Verdict: {args.b} vs {args.a} on weighted dims (substance, engagement) ===")
    for dim in ["substance", "engagement"]:
        gains = []
        for bench in args.benches:
            av = full.get(bench, {}).get(args.a, {}).get(dim, {}).get("mean")
            bv = full.get(bench, {}).get(args.b, {}).get(dim, {}).get("mean")
            if av is not None and bv is not None:
                gains.append((bench, bv - av))
        if gains:
            tot = sum(g for _, g in gains) / len(gains)
            detail = "  ".join(f"{bn}:{g:+.2f}" for bn, g in gains)
            verdict = f"{args.b} ahead" if tot > 0.05 else ("parity" if tot > -0.05 else f"{args.b} behind")
            print(f"  {dim:<12} mean Δ {tot:+.2f}  [{detail}]  -> {verdict}")

    out_path = ROOT / "results" / f"ab_{args.tag}_aggregate.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    json.dump(full, open(out_path, "w"), indent=2)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
