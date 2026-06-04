"""
Aggregate Claude-subagent judge scores for the scale study and apply the
pre-registered decision rule (docs/scale-study-design-2026-06-03.md).

Reads scale_judge_manifest.json + judge_output_scale/*.jsonl, computes per-(arm,
bench) means on engagement / coherence / substance, prints the scaling curve
(engagement vs size), and reads the verdict off stress-bench engagement vs size:

  1B stress engagement - 200M >= +1.0   -> CAPACITY WALL (deficit is a scale effect)
  flat (52m ~ 200m ~ 1b, max-min <= 0.3) -> capacity EXONERATED, deficit is form
  otherwise                              -> PARTIAL (capacity contributes)
"""
import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent
DIMS = ["engagement", "coherence", "substance"]
ARMS = ["50m", "200m", "1b"]
BENCHES = ["stress", "holdout", "cx_patched"]


def mean(xs):
    return round(statistics.mean(xs), 3) if xs else float("nan")


def main():
    manifest = json.load(open(ROOT / "scale_judge_manifest.json"))
    agg = defaultdict(lambda: defaultdict(list))
    seen = defaultdict(set)
    missing = []
    for m in manifest:
        outp = Path(m["output"])
        if not outp.exists():
            missing.append(m["batch"]); continue
        with open(outp) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                s = json.loads(line)
                key = (m["arm"], m["bench"]); iid = s.get("id", "")
                if iid in seen[key]:
                    continue
                seen[key].add(iid)
                for d in DIMS:
                    v = s.get(d); sc = v.get("score") if isinstance(v, dict) else v
                    if isinstance(sc, (int, float)):
                        agg[key][d].append(sc)
    if missing:
        print(f"WARN missing judge outputs for batches: {missing}")

    means = {}
    print(f"{'arm/bench':<18} {'n':>4}  " + "  ".join(f"{d[:9]:>9}" for d in DIMS))
    for arm in ARMS:
        for bench in BENCHES:
            k = (arm, bench)
            means[k] = {d: mean(agg[k][d]) for d in DIMS}
            print(f"{arm + '/' + bench:<18} {len(seen[k]):>4}  "
                  + "  ".join(f"{means[k][d]:>9.2f}" for d in DIMS))

    print("\nSCALING CURVE — engagement vs size:")
    print(f"{'bench':<12}  " + "  ".join(f"{a:>8}" for a in ARMS))
    for bench in BENCHES:
        print(f"{bench:<12}  " + "  ".join(f"{means[(a, bench)]['engagement']:>8.2f}" for a in ARMS))
    print("\nSCALING CURVE — substance vs size:")
    print(f"{'bench':<12}  " + "  ".join(f"{a:>8}" for a in ARMS))
    for bench in BENCHES:
        print(f"{bench:<12}  " + "  ".join(f"{means[(a, bench)]['substance']:>8.2f}" for a in ARMS))

    se = {a: means[(a, "stress")]["engagement"] for a in ARMS}
    delta_1b_200 = se["1b"] - se["200m"]
    spread = max(se.values()) - min(se.values())
    if delta_1b_200 >= 1.0:
        verdict = (f"CAPACITY WALL -- 1B stress engagement ({se['1b']:.2f}) exceeds 200M "
                   f"({se['200m']:.2f}) by {delta_1b_200:+.2f}. The deficit is a scale effect.")
    elif spread <= 0.3:
        verdict = (f"CAPACITY EXONERATED -- stress engagement is flat across sizes "
                   f"(52M {se['50m']:.2f} / 200M {se['200m']:.2f} / 1B {se['1b']:.2f}; "
                   f"spread {spread:.2f}). A 20x model trained the same way fails the same way "
                   f"-> the deficit is training-form. Caveat: the 1B is undertrained at the "
                   f"iso-step budget (val above 200M), so a compute-optimal 1B is the cleaner "
                   f"follow-up before calling capacity fully dead.")
    else:
        verdict = (f"PARTIAL -- stress engagement rises with size but the 1B-vs-200M gap "
                   f"({delta_1b_200:+.2f}) is under +1.0; capacity contributes but does not "
                   f"dissolve the deficit at this budget.")

    print(f"\n=== PRE-REGISTERED DECISION ===")
    print(f"stress engagement by size: 52M {se['50m']:.2f} / 200M {se['200m']:.2f} / 1B {se['1b']:.2f}")
    print(f"VERDICT: {verdict}")

    out = {"means": {f"{a}/{b}": means[(a, b)] for a in ARMS for b in BENCHES},
           "stress_engagement_by_size": se, "delta_1b_minus_200m": delta_1b_200,
           "spread": spread, "verdict": verdict}
    with open(ROOT / "results" / "scale_judge_aggregate.json", "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nWrote {ROOT / 'results' / 'scale_judge_aggregate.json'}")


if __name__ == "__main__":
    main()
