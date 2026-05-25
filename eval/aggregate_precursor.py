"""
Aggregate the English-baseline precursor judging.

Reads the blinded judge outputs + truth map for a comparison, computes per-condition
per-dimension means, and the per-dimension delta (p3_gold_english - teacher_in_ugf)
on engagement / coherence / substance = the vocabulary tax at teacher (120B) scale.

expressive_adequacy is reported only for the restricted-vocabulary (teacher_in_ugf)
arm; gold-English responses carry score -1 (N/A) and are excluded from its mean.

Usage:
  python -m eval.aggregate_precursor --comparison targetprobe
"""
import argparse
import json
import statistics
from pathlib import Path

ROOT = Path("/Users/bbaum/Documents/_RCDS/compression/eval")
DIMS = ["engagement", "coherence", "substance", "expressive_adequacy"]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--comparison", required=True)
    args = p.parse_args()

    in_dir = ROOT / f"judge_input_precursor_{args.comparison}"
    out_dir = ROOT / f"judge_output_precursor_{args.comparison}"
    truth = json.load(open(in_dir / "truth.json"))

    # Collect scores: condition -> dim -> [scores]
    scores: dict[str, dict[str, list]] = {}
    n_parsed, n_bad, n_missing_truth = 0, 0, 0
    seen_ids = set()
    for bf in sorted(out_dir.glob("batch_*.jsonl")):
        for line in open(bf):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                n_bad += 1
                continue
            jid = rec.get("id")
            if jid not in truth:
                n_missing_truth += 1
                continue
            cond = truth[jid]["condition"]
            seen_ids.add(jid)
            n_parsed += 1
            for d in DIMS:
                sc = rec.get(d, {})
                val = sc.get("score") if isinstance(sc, dict) else sc
                if val is None:
                    continue
                bucket = scores.setdefault(cond, {d2: [] for d2 in DIMS})
                bucket[d].append(val)

    # Means (expressive_adequacy excludes -1 = N/A for English)
    def mean_dim(cond, d):
        vals = [v for v in scores.get(cond, {}).get(d, []) if not (d == "expressive_adequacy" and v == -1)]
        return round(statistics.mean(vals), 3) if vals else None

    conds = sorted(scores.keys())
    report = {"comparison": args.comparison, "n_parsed": n_parsed, "n_bad_lines": n_bad,
              "n_unique_ids": len(seen_ids), "n_missing_truth": n_missing_truth,
              "per_condition": {}, "n_per_condition": {}}
    for c in conds:
        report["per_condition"][c] = {d: mean_dim(c, d) for d in DIMS}
        # count of items per condition (use engagement list length)
        report["n_per_condition"][c] = len(scores[c]["engagement"])

    # Tax = p3_gold_english - teacher_in_ugf on engagement/coherence/substance
    if "p3_gold_english" in conds and "teacher_in_ugf" in conds:
        report["vocabulary_tax_p3_minus_ugf"] = {}
        for d in ["engagement", "coherence", "substance"]:
            a = report["per_condition"]["p3_gold_english"][d]
            b = report["per_condition"]["teacher_in_ugf"][d]
            report["vocabulary_tax_p3_minus_ugf"][d] = round(a - b, 3) if (a is not None and b is not None) else None

    out_path = ROOT / "results" / f"precursor_{args.comparison}_aggregate.json"
    json.dump(report, open(out_path, "w"), indent=2)

    # Pretty print
    print(f"=== Precursor: {args.comparison} ===")
    print(f"parsed {n_parsed} scores ({len(seen_ids)} ids); bad lines {n_bad}; missing-truth {n_missing_truth}")
    print(f"{'condition':<18} {'n':>4} {'engage':>8} {'cohere':>8} {'subst':>8} {'expr_ad':>8}")
    for c in conds:
        pc = report["per_condition"][c]
        n = report["n_per_condition"][c]
        def f(x): return f"{x:>8.2f}" if x is not None else f"{'--':>8}"
        print(f"{c:<18} {n:>4} {f(pc['engagement'])} {f(pc['coherence'])} {f(pc['substance'])} {f(pc['expressive_adequacy'])}")
    if "vocabulary_tax_p3_minus_ugf" in report:
        t = report["vocabulary_tax_p3_minus_ugf"]
        print(f"\nVocabulary tax at teacher scale (P3 gold-English − teacher-in-UGF):")
        print(f"  engagement {t['engagement']:+.2f}   coherence {t['coherence']:+.2f}   substance {t['substance']:+.2f}")
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
