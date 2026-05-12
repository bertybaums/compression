"""Parse Hume's *Dialogues Concerning Natural Religion* (Gutenberg #4583) into
consecutive (A, B) dialogue pairs.

Hume's format differs from Plato's Jowett: speaker attribution is embedded
mid-paragraph ("..., replied DEMEA, ...", "..., said CLEANTHES, ..."). We
detect attribution via regex, treat each attributed paragraph as the start of
a turn, and let following non-attributed paragraphs continue the same turn
until the next attribution.

Speakers: DEMEA (orthodox), CLEANTHES (natural theology), PHILO (skeptic).
PAMPHILUS / HERMIPPUS are the framing narrator and addressee; we skip their
narrative entirely.

Reads:  corpus/poc/hume_dialogues_raw.txt
Writes: corpus/poc/hume_pairs.jsonl
"""

import argparse
import json
import random
import re
from pathlib import Path

SRC = Path(__file__).parent / "hume_dialogues_raw.txt"
OUT = Path(__file__).parent / "hume_pairs.jsonl"

START_MARKER = "*** START OF THE PROJECT GUTENBERG EBOOK"
END_MARKER = "*** END OF THE PROJECT GUTENBERG EBOOK"

# Dialogue speakers (proper, non-framing)
SPEAKERS = {"DEMEA", "CLEANTHES", "PHILO"}

# Per-character UGF descriptors. Each composed only of UGF-vocabulary words and
# chosen to capture the character's philosophical role: Demea the orthodox
# god-believer, Cleanthes the natural-theology design-argument advocate, Philo
# the cautious skeptic (often taken as Hume's own voice). Used consistently
# across every (A,B) pair drawn from this dialogue. See parse_meno.py header
# for the policy rationale.
DESCRIPTOR_MAP = {
    "DEMEA": "the church man",
    "CLEANTHES": "the man who sees plans",
    "PHILO": "the careful one",
}

# Inline attribution patterns: ", said SPEAKER", "; replied SPEAKER", etc.
VERBS = r"(?:said|replied|cried|continued|answered|returned|added|resumed|interrupted|exclaimed|observed|rejoined)"
ATTR_RE = re.compile(rf"[,;]?\s+{VERBS}\s+(DEMEA|CLEANTHES|PHILO)\b", re.IGNORECASE)

MIN_LEN = 60
MAX_LEN = 1800   # Hume's speeches are longer than Plato's; relax cap
SAMPLE_N = 60
SEED = 42


def find_attribution(para: str) -> str | None:
    """Return the speaker (DEMEA/CLEANTHES/PHILO) if this paragraph attributes a speech."""
    m = ATTR_RE.search(para)
    if m:
        return m.group(1).upper()
    return None


def parse_turns(text: str) -> list[tuple[str, str]]:
    """Walk paragraphs; the first paragraph with attribution starts a turn,
    subsequent paragraphs without attribution continue that turn, the next
    attribution starts the next turn."""
    paragraphs = re.split(r"\n\s*\n", text)
    turns: list[tuple[str, str]] = []
    cur_speaker: str | None = None
    cur_buf: list[str] = []

    def flush():
        if cur_speaker and cur_buf:
            content = " ".join(" ".join(p.split()) for p in cur_buf).strip()
            content = re.sub(r"\s+", " ", content)
            if MIN_LEN <= len(content) <= MAX_LEN * 3:  # allow buffering large turns
                turns.append((cur_speaker, content))

    for para in paragraphs:
        para_one = " ".join(para.split())
        if not para_one:
            continue
        spk = find_attribution(para_one)
        if spk:
            flush()
            cur_speaker = spk
            cur_buf = [para_one]
        elif cur_speaker is not None:
            cur_buf.append(para_one)
    flush()
    return turns


def strip_attribution(text: str, speaker: str) -> str:
    """Remove the ', said SPEAKER,' clause so the saved turn reads as direct speech."""
    # Try the simplest form: ", VERB SPEAKER,"
    text = re.sub(rf",?\s+{VERBS}\s+{speaker}\b,?", "", text, flags=re.IGNORECASE).strip()
    # Clean up doubled spaces and stray punctuation
    text = re.sub(r"\s+", " ", text).strip(" ,;.")
    if text and not text.endswith((".", "?", "!")):
        text += "."
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None,
                    help="Cap on number of pairs to write (default: all available)")
    ap.add_argument("--all", action="store_true",
                    help="Emit every extractable pair (no sampling)")
    args = ap.parse_args()

    raw = SRC.read_text(encoding="utf-8")
    if START_MARKER in raw:
        raw = raw[raw.index(START_MARKER):]
    if END_MARKER in raw:
        raw = raw[:raw.index(END_MARKER)]

    turns = parse_turns(raw)
    print(f"Parsed {len(turns)} attributed speaker turns.")

    cleaned = [(spk, strip_attribution(text, spk)) for spk, text in turns]
    cleaned = [(s, t) for s, t in cleaned if MIN_LEN <= len(t) <= MAX_LEN]
    print(f"After cleaning + length filter [{MIN_LEN},{MAX_LEN}]: {len(cleaned)} turns.")

    pairs: list[tuple[str, str, str, str]] = []
    for i in range(len(cleaned) - 1):
        a_spk, a_text = cleaned[i]
        b_spk, b_text = cleaned[i + 1]
        if a_spk == b_spk:
            continue
        pairs.append((a_spk, b_spk, a_text, b_text))
    print(f"Built {len(pairs)} consecutive (A,B) pairs with different speakers.")

    if args.all:
        sample = pairs
    else:
        rng = random.Random(SEED)
        n = args.limit if args.limit is not None else min(SAMPLE_N, len(pairs))
        sample = rng.sample(pairs, k=min(n, len(pairs)))

    with OUT.open("w", encoding="utf-8") as f:
        for idx, (a_spk, b_spk, a_text, b_text) in enumerate(sample, 1):
            rec = {
                "id": f"hume_pair_{idx:03d}",
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
