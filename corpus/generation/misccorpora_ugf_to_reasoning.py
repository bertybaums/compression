"""
Extract UGF side of misc-corpora translations into reasoning-trace format.

Companion to cxbot_ugf_to_reasoning.py. After generate_parallel.py has
translated the analogies + conditionals extended passages to UGF, this
script lifts the UGF side into ugf_reasoning.jsonl's schema so the
Reasoner sees analogical_analysis and conditional_analysis as distinct
content types.

Content-type mapping:
  misc-analogies    -> analogical_analysis
  misc-conditionals -> conditional_analysis

Usage:
  python corpus/generation/misccorpora_ugf_to_reasoning.py \\
      --parallel-corpus corpus/processed/parallel_corpus_misccorpora.jsonl \\
      --output corpus/processed/ugf_reasoning_misccorpora.jsonl \\
      [--only-compliant]
"""

import argparse
import json
from pathlib import Path


CONTENT_TYPE_BY_SOURCE = {
    "misc-analogies": "analogical_analysis",
    "misc-conditionals": "conditional_analysis",
}


def topic_for(meta: dict, source: str) -> str:
    """Human-readable topic string for downstream analysis."""
    if source == "misc-analogies":
        st = meta.get("structural_type", "analogy")
        fn = meta.get("function", "unknown")
        subdomain = meta.get("subdomain", "unknown")
        return f"{st} analogy ({fn}) — {subdomain}"
    if source == "misc-conditionals":
        ct = meta.get("conditional_type", "conditional")
        ip = meta.get("inference_pattern", "unknown")
        subdomain = meta.get("subdomain", "unknown")
        return f"{ct} conditional, {ip} — {subdomain}"
    return meta.get("subdomain") or "unknown"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--parallel-corpus", type=Path, required=True,
                   help="parallel_corpus.jsonl containing misc-corpora rows")
    p.add_argument("--output", type=Path, required=True,
                   help="Output JSONL in ugf_reasoning.jsonl schema")
    p.add_argument("--only-compliant", action="store_true",
                   help="Skip rows where compliant=False")
    args = p.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)

    n_in = 0
    n_out = 0
    n_skipped_noncompliant = 0
    n_skipped_not_misc = 0
    by_content_type: dict[str, int] = {}
    with open(args.output, "w", encoding="utf-8") as out:
        with open(args.parallel_corpus) as f:
            for line in f:
                n_in += 1
                r = json.loads(line)
                rid = r.get("id", "")
                if not rid.startswith("misc-"):
                    n_skipped_not_misc += 1
                    continue
                if args.only_compliant and not r.get("compliant", True):
                    n_skipped_noncompliant += 1
                    continue

                meta = r.get("metadata", {}) or {}
                source_tag = f"misc-{meta.get('corpus', 'unknown')}"
                content_type = CONTENT_TYPE_BY_SOURCE.get(
                    source_tag, "reasoning_trace"
                )
                topic = topic_for(meta, source_tag)

                out.write(json.dumps({
                    "id": rid.replace("-passage", "-reasoning"),
                    "ugf_text": r.get("ugf", ""),
                    "content_type": content_type,
                    "topic": topic,
                    "source_model": "misc-corpora-distilled",
                    "metadata": meta,
                    "compliant": r.get("compliant", True),
                }, ensure_ascii=False) + "\n")
                n_out += 1
                by_content_type[content_type] = by_content_type.get(content_type, 0) + 1

    print(f"Read {n_in} parallel-corpus rows")
    print(f"Wrote {n_out} reasoning traces to {args.output}")
    for ct, count in by_content_type.items():
        print(f"  {ct}: {count}")
    if n_skipped_not_misc:
        print(f"  skipped (not misc-corpora): {n_skipped_not_misc}")
    if n_skipped_noncompliant:
        print(f"  skipped (non-compliant): {n_skipped_noncompliant}")


if __name__ == "__main__":
    main()
