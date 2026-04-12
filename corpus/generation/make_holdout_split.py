"""
Build a coordinated hold-out split for Translator and Reasoner training.

Holds out whole source-documents (not individual passages) so that:
  - The English passages of held-out docs are excluded from Translator training.
  - The UGF passages of held-out docs are excluded from Reasoner reasoning-trace
    generation, and thus from Reasoner training.
  - End-to-end evaluation on held-out docs is free of data contamination.

Sampling is stratified by source (good-thinking-bot, intro-ethics) so each
source contributes proportionally to both the train and held-out sets.

Document key:
  passage_id.rsplit('-', 1)[0]
Works for both sources:
  gtb-A3.5-COR0000-scenario_text        -> gtb-A3.5-COR0000
  ethics-appendix-a-reading-guides-0000 -> ethics-appendix-a-reading-guides

Usage:
    python corpus/generation/make_holdout_split.py \
        --input corpus/processed/english_passages.jsonl \
        --output corpus/processed/heldout_ids.json \
        --fraction 0.05 \
        --seed 42

Downstream consumers (Translator dataset loader, reasoning-trace generator,
Reasoner dataset loader) MUST load heldout_ids.json and filter out any
passage whose id appears in heldout_passage_ids.
"""

import argparse
import json
import random
from collections import defaultdict
from datetime import date
from pathlib import Path


def doc_id_of(passage_id: str) -> str:
    return passage_id.rsplit("-", 1)[0]


def main(input_path: Path, output_path: Path, fraction: float, seed: int):
    docs_by_source: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    with open(input_path) as f:
        for line in f:
            r = json.loads(line)
            docs_by_source[r["source"]][doc_id_of(r["id"])].append(r["id"])

    rng = random.Random(seed)
    heldout_passage_ids: list[str] = []
    by_source_stats = {}

    for source, docs in docs_by_source.items():
        doc_ids = sorted(docs.keys())
        n_heldout_docs = max(1, round(len(doc_ids) * fraction))
        heldout_docs = set(rng.sample(doc_ids, n_heldout_docs))
        passages_in_heldout = [pid for d in heldout_docs for pid in docs[d]]
        heldout_passage_ids.extend(passages_in_heldout)

        total_passages = sum(len(v) for v in docs.values())
        by_source_stats[source] = {
            "total_docs": len(doc_ids),
            "heldout_docs": len(heldout_docs),
            "total_passages": total_passages,
            "heldout_passages": len(passages_in_heldout),
        }

    heldout_passage_ids.sort()
    n_total_passages = sum(s["total_passages"] for s in by_source_stats.values())
    n_total_docs = sum(s["total_docs"] for s in by_source_stats.values())

    out = {
        "meta": {
            "created": str(date.today()),
            "seed": seed,
            "holdout_fraction": fraction,
            "n_total_passages": n_total_passages,
            "n_heldout_passages": len(heldout_passage_ids),
            "n_total_documents": n_total_docs,
            "n_heldout_documents": sum(s["heldout_docs"] for s in by_source_stats.values()),
            "by_source": by_source_stats,
        },
        "heldout_passage_ids": heldout_passage_ids,
    }

    with open(output_path, "w") as f:
        json.dump(out, f, indent=2)

    print(f"Wrote {output_path}")
    print(json.dumps(out["meta"], indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, default=Path("corpus/processed/english_passages.jsonl"))
    p.add_argument("--output", type=Path, default=Path("corpus/processed/heldout_ids.json"))
    p.add_argument("--fraction", type=float, default=0.05)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    main(args.input, args.output, args.fraction, args.seed)
