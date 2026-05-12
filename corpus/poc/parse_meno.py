"""Parse Plato's Meno (Jowett translation, Project Gutenberg) into consecutive
(A, B) dialogue pairs for the corpus-form POC.

Reads:  corpus/poc/meno_raw.txt   (Project Gutenberg #1643)
Writes: corpus/poc/meno_pairs.jsonl

Each output record:
  {
    "id": "meno_pair_001",
    "speaker_a": "MENO",
    "speaker_b": "SOCRATES",
    "turn_a": "Can you tell me, Socrates, whether virtue ...",
    "turn_b": "O Meno, there was a time when ...",
  }

Filters: keep pairs where both turns are 20–800 chars (substantive but not
oversized for teacher context).
"""

import argparse
import json
import random
import re
from pathlib import Path

SPEAKERS = {"SOCRATES", "MENO", "ANYTUS", "BOY"}
SPEAKER_RE = re.compile(r"^(SOCRATES|MENO|ANYTUS|BOY):\s*(.*)$")

# Per-character UGF descriptors. These replace the original Greek names so that
# the trained Reasoner never sees a proper noun. Each descriptor is composed
# entirely of UGF-vocabulary words; the same descriptor is used consistently
# across every (A,B) pair drawn from this dialogue, so the descriptor functions
# as a stable referring expression. Whether the model treats these as
# rigid-designator-like is an EMPIRICAL question to test post-training, not a
# property we hard-code via separate name tokens.
DESCRIPTOR_MAP = {
    "SOCRATES": "the old teacher",
    "MENO": "the young man",
    "ANYTUS": "the angry man",
    "BOY": "the young helper",
}

SRC = Path(__file__).parent / "meno_raw.txt"
OUT = Path(__file__).parent / "meno_pairs.jsonl"

# Project Gutenberg bracketing — extract just the dialogue body.
START = "*** START OF THE PROJECT GUTENBERG EBOOK MENO ***"
END = "*** END OF THE PROJECT GUTENBERG EBOOK MENO ***"
DIALOGUE_BEGIN_MARKER = "PERSONS OF THE DIALOGUE"

MIN_LEN = 20
MAX_LEN = 800
SAMPLE_N = 60      # default sample size; can be overridden via --limit
SEED = 42


def extract_turns(text: str) -> list[tuple[str, str]]:
    """Parse SPEAKER: ... turns out of the dialogue body."""
    # Skip the Jowett introduction — start at the first PERSONS line.
    if DIALOGUE_BEGIN_MARKER in text:
        text = text[text.index(DIALOGUE_BEGIN_MARKER):]

    lines = text.splitlines()
    turns: list[tuple[str, str]] = []
    cur_speaker: str | None = None
    cur_buf: list[str] = []

    def flush():
        if cur_speaker and cur_buf:
            content = " ".join(s.strip() for s in cur_buf).strip()
            content = re.sub(r"\s+", " ", content)
            turns.append((cur_speaker, content))

    for line in lines:
        m = SPEAKER_RE.match(line)
        if m:
            flush()
            cur_speaker, first = m.group(1), m.group(2)
            cur_buf = [first] if first else []
        else:
            if cur_speaker is not None:
                if line.strip() == "":
                    continue
                cur_buf.append(line)
    flush()
    return turns


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None,
                    help="Cap on number of pairs to write (default: all available)")
    ap.add_argument("--all", action="store_true",
                    help="Emit every extractable pair (no sampling)")
    args = ap.parse_args()

    raw = SRC.read_text(encoding="utf-8")
    if START in raw and END in raw:
        raw = raw[raw.index(START):raw.index(END)]

    turns = extract_turns(raw)
    print(f"Parsed {len(turns)} total speaker turns.")

    pairs: list[tuple[str, str, str, str]] = []
    for i in range(len(turns) - 1):
        a_spk, a_text = turns[i]
        b_spk, b_text = turns[i + 1]
        if a_spk == b_spk:
            continue
        if not (MIN_LEN <= len(a_text) <= MAX_LEN):
            continue
        if not (MIN_LEN <= len(b_text) <= MAX_LEN):
            continue
        pairs.append((a_spk, b_spk, a_text, b_text))
    print(f"Built {len(pairs)} substantive consecutive (A,B) pairs in [{MIN_LEN},{MAX_LEN}] chars.")

    if args.all:
        sample = pairs
    else:
        rng = random.Random(SEED)
        n = args.limit if args.limit is not None else min(SAMPLE_N, len(pairs))
        sample = rng.sample(pairs, k=min(n, len(pairs)))

    with OUT.open("w", encoding="utf-8") as f:
        for idx, (a_spk, b_spk, a_text, b_text) in enumerate(sample, 1):
            rec = {
                "id": f"meno_pair_{idx:03d}",
                "speaker_a": a_spk,
                "speaker_b": b_spk,
                "descriptor_a": DESCRIPTOR_MAP[a_spk],
                "descriptor_b": DESCRIPTOR_MAP[b_spk],
                "turn_a": a_text,
                "turn_b": b_text,
            }
            f.write(json.dumps(rec) + "\n")
    print(f"Wrote {len(sample)} pairs -> {OUT}")
    print(f"Descriptor map: {DESCRIPTOR_MAP}")


if __name__ == "__main__":
    main()
