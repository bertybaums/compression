"""
Aggregate target-probe judge results.

Reads:
  eval/judge_output_target_probe/independent_batch_NN.jsonl
  eval/judge_output_target_probe/pairwise_batch_NN.jsonl
  eval/judge_input_target_probe/independent_truth.json
  eval/judge_input_target_probe/pairwise_truth.json

Reports:
  - per-condition (reasoner / p4 / p5) per-dimension means + variance + score
    histogram (independent mode)
  - per-condition × per-dimension deltas (reasoner vs p4, reasoner vs p5,
    p4 vs p5)
  - pairwise P4-vs-P5 win rate overall + per-dimension preferences (pairwise mode)
  - agreement check between modes: does pairwise P4 win-rate match
    independent (P4 mean − P5 mean) > 0?

Writes:
  eval/results/target_probe_aggregate.json
  Prints summary to stdout.
"""

import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path("/Users/bbaum/Documents/_RCDS/compression/eval")
JUDGE_OUT = ROOT / "judge_output_target_probe"
JUDGE_IN = ROOT / "judge_input_target_probe"

DIMENSIONS = ["engagement", "coherence", "substance", "expressive_adequacy"]


def mean(xs):
    return statistics.mean(xs) if xs else float("nan")


def stdev(xs):
    return statistics.stdev(xs) if len(xs) >= 2 else float("nan")


def hist(xs):
    h = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
    for x in xs:
        h[x] = h.get(x, 0) + 1
    return h


def load_jsonl(path: Path) -> list[dict]:
    out = []
    if not path.exists():
        return out
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out


def aggregate_independent() -> dict:
    truth_path = JUDGE_IN / "independent_truth.json"
    if not truth_path.exists():
        return {"error": "independent_truth.json not found"}
    truth = json.load(open(truth_path))
    # Per-condition per-dimension scores
    per: dict[str, dict[str, list[int]]] = defaultdict(lambda: {d: [] for d in DIMENSIONS})
    seen: set[str] = set()
    for batch_path in sorted(JUDGE_OUT.glob("independent_batch_*.jsonl")):
        for r in load_jsonl(batch_path):
            iid = r["id"]
            if iid in seen:
                continue
            seen.add(iid)
            cond = truth.get(iid)
            if not cond:
                continue
            for d in DIMENSIONS:
                if d not in r:
                    continue
                per[cond][d].append(r[d]["score"])
    summary: dict[str, dict] = {}
    for cond, dims in per.items():
        summary[cond] = {
            "n": len(dims[DIMENSIONS[0]]),
            "mean": {d: round(mean(dims[d]), 3) for d in DIMENSIONS},
            "stdev": {d: round(stdev(dims[d]), 3) for d in DIMENSIONS},
            "hist": {d: hist(dims[d]) for d in DIMENSIONS},
        }
    # Pairwise deltas
    deltas: dict[str, dict[str, float]] = {}
    conds = list(summary.keys())
    for i, a in enumerate(conds):
        for b in conds[i + 1:]:
            key = f"{a} − {b}"
            deltas[key] = {
                d: round(summary[a]["mean"][d] - summary[b]["mean"][d], 3)
                for d in DIMENSIONS
            }
    return {"per_condition": summary, "deltas": deltas}


def aggregate_pairwise() -> dict:
    truth_path = JUDGE_IN / "pairwise_truth.json"
    if not truth_path.exists():
        return {"error": "pairwise_truth.json not found"}
    truth = json.load(open(truth_path))
    # Counters
    win_overall = {"p4": 0, "p5": 0, "tie": 0}
    win_per_dim = {d: {"p4": 0, "p5": 0, "tie": 0} for d in DIMENSIONS}
    n = 0
    for batch_path in sorted(JUDGE_OUT.glob("pairwise_batch_*.jsonl")):
        for r in load_jsonl(batch_path):
            iid = r["id"]
            t = truth.get(iid)
            if not t:
                continue
            n += 1
            # Overall winner
            winner_AB = (r.get("winner") or "").upper()
            if winner_AB == "A":
                win_overall[t["A"]] += 1
            elif winner_AB == "B":
                win_overall[t["B"]] += 1
            elif winner_AB in {"TIE", ""}:
                win_overall["tie"] += 1
            # Per-dimension preference, if judge supplied dim-level scores
            scores_A = r.get("scores_A") or {}
            scores_B = r.get("scores_B") or {}
            for d in DIMENSIONS:
                sa = (scores_A.get(d) or {}).get("score")
                sb = (scores_B.get(d) or {}).get("score")
                if sa is None or sb is None:
                    continue
                if sa > sb:
                    win_per_dim[d][t["A"]] += 1
                elif sb > sa:
                    win_per_dim[d][t["B"]] += 1
                else:
                    win_per_dim[d]["tie"] += 1
    return {
        "n": n,
        "overall": win_overall,
        "per_dimension": win_per_dim,
    }


def main():
    indep = aggregate_independent()
    pair = aggregate_pairwise()
    out = {"independent": indep, "pairwise": pair}

    out_path = ROOT / "results" / "target_probe_aggregate.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

    print("=" * 72)
    print("Independent mode: per-condition per-dimension means")
    print("=" * 72)
    if "error" in indep:
        print(f"  ERROR: {indep['error']}")
    else:
        cols = ["condition", "n"] + DIMENSIONS
        print(f"{'condition':<12} {'n':>4}  " + "  ".join(f"{d[:10]:>10}" for d in DIMENSIONS))
        for cond, s in indep["per_condition"].items():
            print(f"{cond:<12} {s['n']:>4}  " + "  ".join(f"{s['mean'][d]:>10.2f}" for d in DIMENSIONS))
        print()
        print("Pairwise deltas (A − B):")
        for key, dlt in indep["deltas"].items():
            mark = lambda v: f"{'+' if v >= 0 else ''}{v:.2f}"
            print(f"  {key:<28}: " + "  ".join(f"{mark(dlt[d]):>8}" for d in DIMENSIONS))

    print()
    print("=" * 72)
    print("Pairwise mode: P4-vs-P5 (n = {})".format(pair.get("n", 0)))
    print("=" * 72)
    if "error" in pair:
        print(f"  ERROR: {pair['error']}")
    else:
        ov = pair["overall"]
        total = sum(ov.values()) or 1
        print(f"  P4 wins overall: {ov['p4']}/{total} = {ov['p4']/total:.1%}")
        print(f"  P5 wins overall: {ov['p5']}/{total} = {ov['p5']/total:.1%}")
        print(f"  ties:           {ov['tie']}/{total} = {ov['tie']/total:.1%}")
        print()
        print("  per-dimension preferences:")
        for d in DIMENSIONS:
            ws = pair["per_dimension"][d]
            tot = sum(ws.values()) or 1
            print(f"    {d:<22} P4 {ws['p4']:>3}  P5 {ws['p5']:>3}  tie {ws['tie']:>3}  "
                  f"(P4 wr {ws['p4']/tot:.0%})")

    print()
    print(f"Aggregate at {out_path}")


if __name__ == "__main__":
    main()
