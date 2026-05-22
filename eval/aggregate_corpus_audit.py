"""
Aggregate the corpus-audit judge outputs.

Reads:
- eval/judge_output_corpus_audit_blinded/audit_batch_*.jsonl
- eval/judge_input_corpus_audit_blinded/audit_truth.json

Joins each opaque-id'd score record back to its source corpus (cot,
existing_reasoning, or forms), then computes:

- Per-corpus, per-dimension means + Ns
- Per-corpus score distributions (0..4 histogram)
- Side-by-side table vs v1 Reasoner holdout numbers
  (from memory: Reasoner holdout engagement 2.08 / coherence 3.34 /
   substance 2.26 / expr_adequacy 3.17 — Layer-3, May 5, n=170)

Writes:
- eval/results/corpus_audit_aggregate.json
- prints a compact summary to stdout
"""

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path("/Users/bbaum/Documents/_RCDS/compression/eval")
JUDGE_OUT = ROOT / "judge_output_corpus_audit_blinded"
TRUTH = ROOT / "judge_input_corpus_audit_blinded" / "audit_truth.json"
DIMENSIONS = ["engagement", "coherence", "substance", "expressive_adequacy"]

REASONER_HOLDOUT_MAY5 = {
    "engagement": 2.08,
    "coherence": 3.34,
    "substance": 2.26,
    "expressive_adequacy": 3.17,
}


def load_truth():
    with open(TRUTH) as f:
        return json.load(f)


def load_all_scores():
    out = []
    for path in sorted(JUDGE_OUT.glob("audit_batch_*.jsonl")):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    print(f"WARN: malformed line in {path}: {line[:80]}")
    return out


def main():
    truth = load_truth()
    scores = load_all_scores()
    print(f"Loaded {len(scores)} scored records (truth map: {len(truth)} entries)")

    # Group scores by corpus
    by_corpus_scores: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    by_corpus_dist: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    missing = []
    for s in scores:
        opaque = s.get("id")
        if opaque not in truth:
            missing.append(opaque)
            continue
        corpus = truth[opaque]["corpus"]
        for dim in DIMENSIONS:
            entry = s.get(dim)
            if not entry or "score" not in entry:
                continue
            try:
                score = int(entry["score"])
            except (TypeError, ValueError):
                continue
            by_corpus_scores[corpus][dim].append(score)
            by_corpus_dist[corpus][dim][score] += 1

    if missing:
        print(f"WARN: {len(missing)} scored ids not in truth map")

    summary: dict = {"per_corpus": {}, "reasoner_holdout_may5": REASONER_HOLDOUT_MAY5}
    for corpus, dims in sorted(by_corpus_scores.items()):
        per_dim = {}
        for dim in DIMENSIONS:
            vals = dims[dim]
            if not vals:
                continue
            per_dim[dim] = {
                "mean": round(statistics.mean(vals), 3),
                "stdev": round(statistics.stdev(vals), 3) if len(vals) > 1 else 0.0,
                "n": len(vals),
                "dist": dict(sorted(by_corpus_dist[corpus][dim].items())),
            }
        summary["per_corpus"][corpus] = per_dim

    out_path = ROOT / "results" / "corpus_audit_aggregate.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)

    # Print compact table
    print()
    print(f"{'corpus':<22} {'engage':>8} {'coher':>8} {'subst':>8} {'expr':>8} {'n':>5}")
    print("-" * 64)
    for corpus, per_dim in summary["per_corpus"].items():
        row = [corpus]
        n_first = None
        for dim in DIMENSIONS:
            entry = per_dim.get(dim, {})
            row.append(f"{entry.get('mean', float('nan')):.2f}")
            if n_first is None:
                n_first = entry.get("n", 0)
        row.append(str(n_first))
        print(f"{row[0]:<22} {row[1]:>8} {row[2]:>8} {row[3]:>8} {row[4]:>8} {row[5]:>5}")
    rh = REASONER_HOLDOUT_MAY5
    print(f"{'reasoner_holdout_may5':<22} {rh['engagement']:>8.2f} {rh['coherence']:>8.2f} {rh['substance']:>8.2f} {rh['expressive_adequacy']:>8.2f} {'170':>5}")

    # Deltas: corpus mean − Reasoner holdout
    print()
    print(f"{'delta (corpus − reasoner_holdout)':<40}")
    print(f"{'corpus':<22} {'engage':>8} {'coher':>8} {'subst':>8} {'expr':>8}")
    print("-" * 60)
    for corpus, per_dim in summary["per_corpus"].items():
        row = [corpus]
        for dim in DIMENSIONS:
            entry = per_dim.get(dim, {})
            mean = entry.get("mean")
            base = REASONER_HOLDOUT_MAY5[dim]
            row.append(f"{mean - base:+.2f}" if mean is not None else "")
        print(f"{row[0]:<22} {row[1]:>8} {row[2]:>8} {row[3]:>8} {row[4]:>8}")

    print()
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
