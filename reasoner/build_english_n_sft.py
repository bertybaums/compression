"""
Build the English-N SFT arm of the 200M English-vocab baseline
(docs/english-baseline-design-2026-05-24.md).

Reads english_n.jsonl (P3-at-scale teacher English over the matched prompts;
schema {id, english_text, content_type, topic, source_model, metadata, compliant})
and emits english_n_sft.jsonl mirroring the UGF-N arm (ugf_n_sft_400k.jsonl):
  {id, prompt, response, content_type, compliant}
where
  prompt   = CONTENT_TYPES[content_type].format(topic=topic)   -- byte-identical
             to the prompt that generated the trace AND to the UGF-N arm's prompt
  response = english_text

Both arms then train via UGFSFTPlainDataset (dataset_type: sft_plain), which reads
the pre-rendered `prompt`/`response` fields directly -- so the ONLY difference
between the arms is the output vocabulary.

CRITICAL: imports CONTENT_TYPES from generate_reasoning (NOT data_sft) so the
templates match generation + the UGF-N arm exactly. data_sft.CONTENT_TYPES has
drifted on the thought_experiment trailer ("Walk-through:" vs generate_reasoning's
"Thinking through this:"); routing through generate_reasoning + sft_plain sidesteps
it. (sample_matched_n.py imports the same source, so UGF-N and English-N agree.)

Usage (fortyfive):
  python3 -m reasoner.build_english_n_sft \
      --english corpus/processed/english_n.jsonl \
      --out corpus/processed/english_n_sft.jsonl
"""
import argparse
import json
from collections import Counter
from pathlib import Path

from corpus.generation.generate_reasoning import CONTENT_TYPES


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--english", default="corpus/processed/english_n.jsonl")
    ap.add_argument("--out", default="corpus/processed/english_n_sft.jsonl")
    ap.add_argument("--text-field", default="english_text")
    ap.add_argument("--min-words", type=int, default=10,
                    help="Mirror sample_matched_n's >=10-word response filter.")
    args = ap.parse_args()

    n_seen = n_nonc = n_noct = n_short = 0
    kept = []
    word_counts = []
    with open(args.english) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            n_seen += 1
            if not r.get("compliant", True):
                n_nonc += 1
                continue
            ct = r.get("content_type")
            if ct not in CONTENT_TYPES:
                n_noct += 1
                continue
            resp = (r.get(args.text_field) or "").strip()
            if not resp or len(resp.split()) < args.min_words:
                n_short += 1
                continue
            kept.append({
                "id": r["id"],
                "prompt": CONTENT_TYPES[ct].format(topic=r.get("topic", "")),
                "response": resp,
                "content_type": ct,
                "compliant": True,
            })
            word_counts.append(len(resp.split()))

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fo:
        for rec in kept:
            fo.write(json.dumps(rec, ensure_ascii=False) + "\n")

    word_counts.sort()
    n = len(word_counts)

    def pct(p):
        return word_counts[min(n - 1, int(p * n))] if n else 0

    print(f"Scanned {n_seen}; wrote {n} -> {args.out}")
    print(f"  skipped: {n_nonc} noncompliant, {n_noct} no-content_type, "
          f"{n_short} short(<{args.min_words}w)")
    print(f"content_type mix: {dict(Counter(r['content_type'] for r in kept))}")
    if n:
        print(f"response words: mean={sum(word_counts)/n:.0f} p50={pct(0.5)} "
              f"p90={pct(0.9)} p99={pct(0.99)} max={word_counts[-1]}")


if __name__ == "__main__":
    main()
