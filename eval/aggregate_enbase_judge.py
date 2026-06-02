"""
Aggregate Claude-subagent judge scores for the 200M English-vocab baseline
(docs/english-baseline-design-2026-05-24.md) and apply the pre-registered
decision rule.

Reads enbase_judge_manifest.json + judge_output_enbase/*.jsonl (one line per
item: {id, engagement:{score,...}, coherence:{...}, substance:{...}}), computes
per-(arm,bench) means on engagement / coherence / substance, the English-N − UGF-N
deltas per bench, and the verdict from the stress-bench engagement delta
(co-reported with substance).

Decision rule (design doc):
  |Δ stress engagement| <= 0.3  -> vocabulary EXONERATED (deficit is form/capacity)
  Δ >= +1.5                     -> vocabulary IMPLICATED (empirical Sheffer-stroke)
  in between                    -> PARTIAL (vocabulary contributes, not the whole story)

Usage:
  python3 eval/aggregate_enbase_judge.py
"""
import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent
DIMS = ["engagement", "coherence", "substance"]
ARMS = ["ugf_n", "en_n"]
BENCHES = ["stress", "holdout", "cx_patched"]


def mean(xs):
    return round(statistics.mean(xs), 3) if xs else float("nan")


def main():
    manifest = json.load(open(ROOT / "enbase_judge_manifest.json"))
    agg = defaultdict(lambda: defaultdict(list))   # (arm,bench) -> dim -> [scores]
    seen = defaultdict(set)
    missing = []
    for m in manifest:
        outp = Path(m["output"])
        if not outp.exists():
            missing.append(m["batch"])
            continue
        with open(outp) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                s = json.loads(line)
                key = (m["arm"], m["bench"])
                iid = s.get("id", "")
                if iid in seen[key]:
                    continue
                seen[key].add(iid)
                for d in DIMS:
                    v = s.get(d)
                    sc = v.get("score") if isinstance(v, dict) else v
                    if isinstance(sc, (int, float)):
                        agg[key][d].append(sc)
    if missing:
        print(f"WARN missing judge outputs for batches: {missing}")

    means = {}
    print(f"{'arm/bench':<20} {'n':>4}  " + "  ".join(f"{d[:9]:>9}" for d in DIMS))
    for arm in ARMS:
        for bench in BENCHES:
            k = (arm, bench)
            means[k] = {d: mean(agg[k][d]) for d in DIMS}
            print(f"{arm + '/' + bench:<20} {len(seen[k]):>4}  "
                  + "  ".join(f"{means[k][d]:>9.2f}" for d in DIMS))

    def fmt(v):
        return ("+" if v >= 0 else "") + format(v, ".2f")

    print("\nDelta (English-N - UGF-N), per bench:")
    print(f"{'bench':<12}  " + "  ".join(f"{d[:9]:>9}" for d in DIMS))
    deltas = {}
    for bench in BENCHES:
        deltas[bench] = {d: round(means[("en_n", bench)][d] - means[("ugf_n", bench)][d], 3)
                         for d in DIMS}
        print(f"{bench:<12}  " + "  ".join(f"{fmt(deltas[bench][d]):>9}" for d in DIMS))

    de = deltas["stress"]["engagement"]
    ds = deltas["stress"]["substance"]
    if abs(de) <= 0.3:
        verdict = ("VOCABULARY EXONERATED -- English-N ~= UGF-N on stress engagement "
                   "(deficit is form/capacity, not the restricted vocabulary). "
                   "Strengthens the expressive-adequacy thesis.")
    elif de >= 1.5:
        verdict = ("VOCABULARY IMPLICATED -- English-N >> UGF-N on stress engagement. "
                   "Empirical Sheffer-stroke: restricted-vocab derivations exceed the "
                   "capacity budget at 200M.")
    else:
        verdict = (f"PARTIAL -- stress-engagement delta {de:+.2f} is between 0.3 and 1.5; "
                   "vocabulary contributes but is not the whole story.")

    print(f"\n=== PRE-REGISTERED DECISION ===")
    print(f"stress engagement delta (English - UGF) = {de:+.2f}  [primary]")
    print(f"stress substance  delta (English - UGF) = {ds:+.2f}  [co-primary]")
    print(f"VERDICT: {verdict}")

    out = {
        "means": {f"{a}/{b}": means[(a, b)] for a in ARMS for b in BENCHES},
        "deltas": deltas,
        "stress_engagement_delta": de,
        "stress_substance_delta": ds,
        "verdict": verdict,
    }
    with open(ROOT / "results" / "enbase_judge_aggregate.json", "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nWrote {ROOT / 'results' / 'enbase_judge_aggregate.json'}")


if __name__ == "__main__":
    main()
