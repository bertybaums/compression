"""
Curate a ~40K-word English vocabulary for the English-baseline tokenizer
(docs/english-baseline-design-2026-05-24.md).

The English arm needs a word-level vocabulary that is the analog of UGF's
externally-defined ~1K Munroe list — here, the top-K most frequent English word
FORMS over a general-English corpus (english_passages.jsonl), NOT derived from the
arm's own training text (which would make it corpus-tailored, unlike UGF's fixed
list). Output is structured EXACTLY like wordlist/vocab_final.json (same specials /
punctuation / numerals / newline, same ordering) so the existing UGFTokenizer
loads it directly: UGFTokenizer(vocab_path="wordlist/vocab_english_40k.json").

Word forms (not lemmas) are the tokens, mirroring UGF. Counting uses the same word
pattern as UGFTokenizer so coverage numbers transfer.

Usage:
  python -m wordlist.curate_english_wordlist --top-k 40000
"""
import argparse
import json
import re
from collections import Counter
from pathlib import Path

# Matches UGFTokenizer's word pattern (alpha runs + internal apostrophes).
_WORD_RE = re.compile(r"[a-zA-Z]+(?:'[a-zA-Z]+)*")

SPECIAL_TOKENS = ["<PAD>", "<UNK>", "<BOS>", "<EOS>", "<CAP>"]
PUNCTUATION = [".", ",", "!", "?", ";", ":", "-", "(", ")", '"', "'"]
NUMERALS = [str(d) for d in range(10)]
STRUCTURAL = ["\n"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="corpus/processed/english_passages.jsonl")
    ap.add_argument("--text-field", default="text")
    ap.add_argument("--top-k", type=int, default=40000)
    ap.add_argument("--out", default="wordlist/vocab_english_40k.json")
    ap.add_argument("--words-out", default="wordlist/vocab_english_40k_words.txt")
    args = ap.parse_args()

    counts: Counter = Counter()
    n_docs = n_tokens = 0
    with open(args.corpus) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            text = (json.loads(line).get(args.text_field) or "")
            for m in _WORD_RE.findall(text):
                counts[m.lower()] += 1
                n_tokens += 1
            n_docs += 1

    top = [w for w, _ in counts.most_common(args.top_k)]
    covered = sum(counts[w] for w in top)
    coverage = covered / n_tokens if n_tokens else 0.0
    print(f"Scanned {n_docs} docs, {n_tokens} word tokens, {len(counts)} unique forms")
    print(f"Top-{args.top_k} forms cover {coverage*100:.2f}% of word tokens "
          f"({100 - coverage*100:.2f}% -> <UNK>)")

    vocab: dict[str, int] = {}
    idx = 0
    for group in (SPECIAL_TOKENS, PUNCTUATION, NUMERALS, STRUCTURAL):
        for tok in group:
            if tok not in vocab:
                vocab[tok] = idx
                idx += 1
    for word in top:
        if word not in vocab:  # words are alpha-only, won't collide, but guard anyway
            vocab[word] = idx
            idx += 1

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(vocab, f, ensure_ascii=False)  # no indent: 40K entries
    with open(args.words_out, "w", encoding="utf-8") as f:
        f.write("\n".join(top) + "\n")
    print(f"Final vocab size: {len(vocab)} tokens "
          f"({len(SPECIAL_TOKENS)} special + {len(PUNCTUATION)} punct + "
          f"{len(NUMERALS)} num + {len(STRUCTURAL)} struct + {len(top)} words)")
    print(f"Wrote {args.out} + {args.words_out}")


if __name__ == "__main__":
    main()
