"""
Measure out-of-vocabulary (OOV) rate of a corpus under a word-level vocab,
mirroring UGFTokenizer's word tokenization (lowercased alpha runs + apostrophes).

Used to validate the English-baseline vocab (docs/english-baseline-design-2026-05-24.md):
the English arm should have low OOV on its training text (english_n), else <UNK>
noise handicaps it relative to the UGF arm (which is ~100% in-vocab by construction).
If OOV is high under the english_passages-derived vocab, rebuild over english_n.

Usage:
  python -m wordlist.measure_oov --vocab wordlist/vocab_english_40k.json \
      --corpus corpus/processed/english_n.jsonl --text-field english_text
"""
import argparse
import json
import re
from collections import Counter

_WORD_RE = re.compile(r"[a-zA-Z]+(?:'[a-zA-Z]+)*")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vocab", required=True)
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--text-field", default="english_text")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    vocab = set(json.load(open(args.vocab)).keys())
    n_tok = n_oov = n_docs = 0
    oov_counts: Counter = Counter()
    with open(args.corpus) as f:
        for i, line in enumerate(f):
            if args.limit and i >= args.limit:
                break
            line = line.strip()
            if not line:
                continue
            text = (json.loads(line).get(args.text_field) or "")
            for m in _WORD_RE.findall(text):
                n_tok += 1
                if m.lower() not in vocab:
                    n_oov += 1
                    oov_counts[m.lower()] += 1
            n_docs += 1

    rate = n_oov / n_tok * 100 if n_tok else 0.0
    print(f"{n_docs} docs, {n_tok} word tokens, {n_oov} OOV ({rate:.2f}%)")
    print(f"distinct OOV forms: {len(oov_counts)}")
    print(f"top OOV forms: {oov_counts.most_common(25)}")


if __name__ == "__main__":
    main()
