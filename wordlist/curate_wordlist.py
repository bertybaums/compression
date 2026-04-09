"""
Curate the Up Goer Five word list into a canonical vocabulary for the UGF tokenizer.

Source: XKCD Simple Writer Word List 0.2.1
        https://xkcd.com/simplewriter/words.js

The raw list contains ~3,634 inflected forms of the ~1,000 most common English
lemmas (e.g., "walk", "walked", "walking" are separate entries). Each inflected
form gets its own token ID -- the UGF inclusion rule ("all forms of a word count
as one") determines what's *allowed*, not how it's tokenized.

Additions beyond the raw list:
  - Special tokens: <PAD>, <UNK>, <BOS>, <EOS>, <CAP>
  - Punctuation: . , ! ? ; : - ( ) " '
  - Numerals: 0-9
  - Newline token for multi-paragraph reasoning

Output: vocab_final.json -- {token: id} mapping used by UGFTokenizer.
"""

import json
import re
from pathlib import Path

HERE = Path(__file__).parent

# --- 1. Extract words from the XKCD Simple Writer JS file ---
raw_js = (HERE / "xkcd_simplewriter_words.js").read_text(encoding="utf-8")
match = re.search(r'__WORDS\s*=\s*"([^"]+)"', raw_js)
if not match:
    raise ValueError("Could not find __WORDS in xkcd_simplewriter_words.js")

raw_words = match.group(1).split("|")

# Keep only entries that are actual words (lowercase alpha + apostrophes)
words = sorted(set(w.strip() for w in raw_words if re.match(r"^[a-z]['a-z]*$", w.strip())))

print(f"Extracted {len(words)} unique word forms from XKCD Simple Writer")

# --- 2. Define special tokens, punctuation, numerals ---
SPECIAL_TOKENS = ["<PAD>", "<UNK>", "<BOS>", "<EOS>", "<CAP>"]

PUNCTUATION = [".", ",", "!", "?", ";", ":", "-", "(", ")", '"', "'"]

NUMERALS = [str(d) for d in range(10)]

STRUCTURAL = ["\n"]  # newline for multi-paragraph output

# --- 3. Build the vocabulary ---
# Order: special tokens first (PAD=0), then punctuation, numerals, structural, then words
vocab = {}
idx = 0

for tok in SPECIAL_TOKENS:
    vocab[tok] = idx
    idx += 1

for tok in PUNCTUATION:
    vocab[tok] = idx
    idx += 1

for tok in NUMERALS:
    vocab[tok] = idx
    idx += 1

for tok in STRUCTURAL:
    vocab[tok] = idx
    idx += 1

for word in words:
    if word not in vocab:  # guard against overlap with punctuation tokens
        vocab[word] = idx
        idx += 1

print(f"Final vocabulary size: {len(vocab)} tokens")
print(f"  Special tokens: {len(SPECIAL_TOKENS)}")
print(f"  Punctuation:    {len(PUNCTUATION)}")
print(f"  Numerals:       {len(NUMERALS)}")
print(f"  Structural:     {len(STRUCTURAL)}")
print(f"  Words:          {len(vocab) - len(SPECIAL_TOKENS) - len(PUNCTUATION) - len(NUMERALS) - len(STRUCTURAL)}")

# --- 4. Write output ---
output_path = HERE / "vocab_final.json"
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(vocab, f, indent=2, ensure_ascii=False)

print(f"Wrote vocabulary to {output_path}")

# --- 5. Also write a plain text word list for human inspection ---
wordlist_path = HERE / "vocab_words_only.txt"
with open(wordlist_path, "w", encoding="utf-8") as f:
    for word in words:
        f.write(word + "\n")

print(f"Wrote word-only list to {wordlist_path}")
