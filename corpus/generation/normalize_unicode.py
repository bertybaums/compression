"""
Normalize Unicode typography to ASCII in a JSONL text field, for the English arm
of the 200M English-vocab baseline (docs/english-baseline-design-2026-05-24.md).

The English teacher prose uses curly quotes, em/en/nb-dashes, ellipses, etc.,
which the word-level English vocab (built over plain-ASCII english_passages)
lacks -> ~1.1% of English response tokens map to <UNK> purely from typography,
vs 0.05% for the UGF arm (whose generation enforced plain ASCII). Mapping to the
ASCII equivalents the UGF corpus already uses makes the comparison a pure
word-vocabulary test, not a typography test (June 1, 2026 decision).

Applied to `english_text` only (the response / pretrain text); topics are left
untouched so the rendered prompts stay byte-identical to the UGF-N arm (and SFT
masks prompt tokens in the loss anyway).

Usage (fortyfive):
  python3 -m corpus.generation.normalize_unicode \
      --in corpus/processed/english_n.jsonl \
      --out corpus/processed/english_n_norm.jsonl --field english_text
"""
import argparse
import json
from collections import Counter

# Common Unicode typography -> ASCII. Multi-char and empty targets allowed.
_MAP = {
    "‐": "-", "‑": "-", "‒": "-", "–": "-",   # hyphen, nb-hyphen, figure, en
    "—": "-", "―": "-", "−": "-",                    # em dash, horizontal bar, minus
    "‘": "'", "’": "'", "‚": "'", "‛": "'",   # single quotes
    "′": "'",                                                  # prime
    "“": '"', "”": '"', "„": '"', "″": '"',   # double quotes / double prime
    "…": "...",                                                # ellipsis
    "⁄": "/", "∕": "/",                                   # fraction / division slash
    " ": " ", " ": " ", " ": " ", " ": " ",   # nb / narrow / thin / hair spaces
    " ": " ", " ": " ", " ": " ",                    # figure / em / en spaces
    "​": "", "﻿": "",                                     # zero-width space, BOM -> drop
}
_TRANS = str.maketrans(_MAP)


def normalize_text(s: str) -> str:
    return s.translate(_TRANS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--field", default="english_text")
    args = ap.parse_args()

    n = n_changed = 0
    changed_chars = Counter()
    with open(args.inp) as f, open(args.out, "w", encoding="utf-8") as fo:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            n += 1
            orig = r.get(args.field) or ""
            norm = normalize_text(orig)
            if norm != orig:
                n_changed += 1
                for ch in orig:
                    if ch in _MAP:
                        changed_chars[ch] += 1
            r[args.field] = norm
            fo.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"Wrote {n} records -> {args.out} ({n_changed} had normalizations)")
    print("chars normalized:", {repr(k): v for k, v in changed_chars.most_common()})


if __name__ == "__main__":
    main()
