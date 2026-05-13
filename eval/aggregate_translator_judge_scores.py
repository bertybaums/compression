"""
Aggregate Translator-quality judge outputs into per-system summary statistics.

Reads all batch outputs in eval/judge_output_translator/ matching each system
label from the manifest. Computes per-system per-dimension means, score
histograms, and pairwise deltas across systems.

Outputs:
- eval/results/judge_aggregate_translator.json
- prints summary to stdout
"""

import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path("/Users/bbaum/Documents/_RCDS/compression/eval")
JUDGE_OUT = ROOT / "judge_output_translator"
MANIFEST = ROOT / "judge_manifest_translator.json"
DIMENSIONS = ["meaning_preservation", "fluency", "no_fabrication", "paraphrase_sensibility"]


def mean(xs):
    return statistics.mean(xs) if xs else float("nan")


def hist(xs):
    h = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
    for x in xs:
        h[x] = h.get(x, 0) + 1
    return h


def load_label_scores(label: str) -> list[dict]:
    out: list[dict] = []
    for path in sorted(JUDGE_OUT.glob(f"{label}_batch_*.jsonl")):
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                out.append(json.loads(line))
    return out


def summarize(label: str, expected_n: int) -> dict:
    scores = load_label_scores(label)
    per_dim: dict[str, list[int]] = {d: [] for d in DIMENSIONS}
    seen_ids: set[str] = set()
    for s in scores:
        if s["id"] in seen_ids:
            continue
        seen_ids.add(s["id"])
        for d in DIMENSIONS:
            per_dim[d].append(s[d]["score"])
    return {
        "label": label,
        "expected_n": expected_n,
        "received_n": len(scores),
        "scored_n": len(seen_ids),
        "per_dim_mean": {d: round(mean(per_dim[d]), 3) for d in DIMENSIONS},
        "per_dim_hist": {d: hist(per_dim[d]) for d in DIMENSIONS},
    }


def main():
    with open(MANIFEST) as fh:
        manifest = json.load(fh)

    labels_expected_n: dict[str, int] = defaultdict(int)
    for m in manifest:
        labels_expected_n[m["label"]] += m["n_items"]

    summaries = {label: summarize(label, n) for label, n in labels_expected_n.items()}

    deltas: dict[str, dict[str, dict[str, float]]] = {}
    labels = list(summaries.keys())
    for i, a in enumerate(labels):
        for b in labels[i + 1:]:
            key = f"{a} − {b}"
            deltas[key] = {
                d: round(
                    summaries[a]["per_dim_mean"][d] - summaries[b]["per_dim_mean"][d],
                    3,
                )
                for d in DIMENSIONS
            }

    aggregate = {"summaries": summaries, "deltas": deltas}
    out_path = ROOT / "results" / "judge_aggregate_translator.json"
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w") as fh:
        json.dump(aggregate, fh, indent=2)
    print(f"Wrote {out_path}\n")

    print("=" * 72)
    print("Per-system per-dimension means")
    print("=" * 72)
    print(f"{'system':<30} {'n':>5}  " + "  ".join(f"{d[:10]:>10}" for d in DIMENSIONS))
    for label, s in summaries.items():
        means = s["per_dim_mean"]
        print(
            f"{label:<30} {s['scored_n']:>5}  "
            + "  ".join(f"{means[d]:>10.2f}" for d in DIMENSIONS)
        )

    print()
    print("=" * 72)
    print("Pairwise deltas (A − B)")
    print("=" * 72)
    for key, dlt in deltas.items():
        marker = lambda v: f"{'+' if v >= 0 else ''}{v:.2f}"
        print(f"{key:<48} " + "  ".join(f"{marker(dlt[d]):>9}" for d in DIMENSIONS))


if __name__ == "__main__":
    main()
