"""
Extract the UGF side of cx-bot translations into the reasoning-trace schema.

After generate_parallel.py has translated cx-bot passages to UGF, each
(english, ugf) pair has done double duty: the pair itself trains the
Translator, and the UGF side is a high-quality counterexample-construction
reasoning trace for the Reasoner. This script lifts that UGF side into
ugf_reasoning.jsonl's schema so the Reasoner training pipeline picks it
up as its own content type.

Usage:
  python corpus/generation/cxbot_ugf_to_reasoning.py \\
    --parallel-corpus corpus/processed/parallel_corpus_cxbot.jsonl \\
    --output corpus/processed/ugf_reasoning_cxbot.jsonl \\
    [--only-compliant]
"""

import argparse
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--parallel-corpus", type=Path, required=True,
                   help="parallel_corpus.jsonl output from generate_parallel.py, containing cx-bot rows")
    p.add_argument("--output", type=Path, required=True,
                   help="Output JSONL in ugf_reasoning.jsonl schema")
    p.add_argument("--only-compliant", action="store_true",
                   help="Skip rows where compliant=False")
    args = p.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)

    n_in = 0
    n_out = 0
    n_skipped_noncompliant = 0
    n_skipped_not_cxbot = 0
    with open(args.output, "w", encoding="utf-8") as out:
        with open(args.parallel_corpus) as f:
            for line in f:
                n_in += 1
                r = json.loads(line)
                if not r.get("id", "").startswith("cxbot-"):
                    n_skipped_not_cxbot += 1
                    continue
                if args.only_compliant and not r.get("compliant", True):
                    n_skipped_noncompliant += 1
                    continue

                meta = r.get("metadata", {})
                subdomain = meta.get("subdomain") or meta.get("domain") or "unknown"
                cx_type = meta.get("cx_type", "cx")
                # Human-readable topic string for downstream analysis
                topic = f"{cx_type.upper()} — {subdomain}"
                if meta.get("definition"):
                    topic = f"counterexample to: {meta['definition'][:80]}"

                out.write(json.dumps({
                    "id": r["id"].replace("-passage", "-reasoning"),
                    "ugf_text": r.get("ugf", ""),
                    "content_type": "counterexample_analysis",
                    "topic": topic,
                    "source_model": "cx-bot-distilled",
                    "metadata": {
                        "cx_type": cx_type,
                        "domain": meta.get("domain"),
                        "subdomain": subdomain,
                        "original_id": meta.get("original_id"),
                    },
                    "compliant": r.get("compliant", True),
                }, ensure_ascii=False) + "\n")
                n_out += 1

    print(f"Read {n_in} parallel-corpus rows")
    print(f"Wrote {n_out} reasoning traces to {args.output}")
    if n_skipped_not_cxbot:
        print(f"  skipped (not cx-bot): {n_skipped_not_cxbot}")
    if n_skipped_noncompliant:
        print(f"  skipped (non-compliant): {n_skipped_noncompliant}")


if __name__ == "__main__":
    main()
