"""Parse Patrick's 1899 English translation of Sextus Empiricus's *Outlines of
Pyrrhonism* Book I (embedded in Gutenberg #17556, "Sextus Empiricus and Greek
Scepticism" by Mary Mills Patrick) into chunks suitable for skeptical-mode
extraction.

The Pyrrhonic Sketches translation begins at line ~3702 of the Gutenberg
file and runs through Chapter XIX+. Chapter XIV contains the Ten Tropes
proper; we extract chunks from that chapter and adjacent skeptical-method
chapters as source passages.

Each chunk is a 200-600 word slice of one Trope, containing both the claim
the dogmatist might make and the differences-of-appearance considerations
that motivate suspension of judgment. The teacher's job is to produce a
(claim, counter+suspension) pair in UGF from each chunk.

Reads:  corpus/poc/sextus_patrick_raw.txt
Writes: corpus/poc/sextus_pairs.jsonl
"""

import argparse
import json
import random
import re
from pathlib import Path

SRC = Path(__file__).parent / "sextus_patrick_raw.txt"
OUT = Path(__file__).parent / "sextus_pairs.jsonl"

# The PYRRHONIC SKETCHES section starts at line ~3702 in the file. We
# locate it programmatically.
SKETCHES_HEADER_RE = re.compile(r"^PYRRHONIC SKETCHES\s*$", re.MULTILINE)

# Per-trope header. Patrick uses "THE FIRST TROPE." through "THE TENTH TROPE."
TROPE_HEADER_RE = re.compile(
    r"^THE\s+(FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH)\s+TROPE\.?\s*$",
    re.MULTILINE,
)

# Patrick's text contains marginal section numbers like "36", "37", etc., as
# right-floats. After paragraph-joining they end up at end-of-line. Strip them.
MARGIN_NUM_RE = re.compile(r"\s+\d{1,3}\s*$", re.MULTILINE)

# Target chunk size in words. Tropes are long; we split each into 2-5 chunks.
CHUNK_TARGET_WORDS = 350
CHUNK_MIN_WORDS = 120
CHUNK_MAX_WORDS = 600
SAMPLE_N = 50
SEED = 42


def find_sketches_section(text: str) -> str:
    """Return the substring starting at PYRRHONIC SKETCHES."""
    m = SKETCHES_HEADER_RE.search(text)
    if not m:
        raise SystemExit("Could not find PYRRHONIC SKETCHES header in source.")
    return text[m.end():]


CHAPTER_RE = re.compile(r"^CHAPTER\s+[IVXLC]+\.?\s*$", re.MULTILINE)


def extract_tropes(sketches_text: str) -> dict[str, str]:
    """Return {ordinal: body} for each named Trope (FIRST..TENTH).

    Each Trope's body is bounded by the next TROPE header OR the next
    CHAPTER header, whichever comes first. This stops the TENTH Trope from
    absorbing subsequent chapters.
    """
    trope_matches = list(TROPE_HEADER_RE.finditer(sketches_text))
    chap_starts = [m.start() for m in CHAPTER_RE.finditer(sketches_text)]
    out: dict[str, str] = {}
    for i, m in enumerate(trope_matches):
        name = m.group(1).upper()
        body_start = m.end()
        # Determine end: next TROPE header, or next CHAPTER, or EOF
        next_trope = trope_matches[i + 1].start() if i + 1 < len(trope_matches) else len(sketches_text)
        next_chap = next((c for c in chap_starts if c > body_start), len(sketches_text))
        body_end = min(next_trope, next_chap)
        body = sketches_text[body_start:body_end].strip()
        body = MARGIN_NUM_RE.sub("", body)
        out[name] = body
    return out


_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"])")


def split_long_paragraphs(paragraphs: list[str]) -> list[str]:
    """Sentence-split any paragraph longer than CHUNK_MAX_WORDS so the chunker
    has units it can fit."""
    out: list[str] = []
    for p in paragraphs:
        if len(p.split()) <= CHUNK_MAX_WORDS:
            out.append(p)
            continue
        # Sentence split
        sents = _SENTENCE_BREAK.split(p)
        # Re-group sentences into ~target-sized units
        cur: list[str] = []
        cur_w = 0
        for s in sents:
            sw = len(s.split())
            if cur and cur_w + sw > CHUNK_MAX_WORDS:
                out.append(" ".join(cur))
                cur, cur_w = [], 0
            cur.append(s)
            cur_w += sw
        if cur:
            out.append(" ".join(cur))
    return out


def chunk_paragraphs(text: str) -> list[str]:
    """Split text into paragraphs (sentence-splitting long ones), then group
    into ~CHUNK_TARGET_WORDS chunks bounded by CHUNK_MAX_WORDS."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    paragraphs = [" ".join(p.split()) for p in paragraphs]
    paragraphs = split_long_paragraphs(paragraphs)

    chunks: list[str] = []
    cur: list[str] = []
    cur_w = 0
    for p in paragraphs:
        pw = len(p.split())
        if cur and cur_w + pw > CHUNK_MAX_WORDS:
            chunk_text = " ".join(cur)
            if CHUNK_MIN_WORDS <= len(chunk_text.split()) <= CHUNK_MAX_WORDS:
                chunks.append(chunk_text)
            cur, cur_w = [], 0
        cur.append(p)
        cur_w += pw
        if cur_w >= CHUNK_TARGET_WORDS:
            chunk_text = " ".join(cur)
            if CHUNK_MIN_WORDS <= len(chunk_text.split()) <= CHUNK_MAX_WORDS:
                chunks.append(chunk_text)
            cur, cur_w = [], 0
    if cur:
        chunk_text = " ".join(cur)
        if CHUNK_MIN_WORDS <= len(chunk_text.split()) <= CHUNK_MAX_WORDS:
            chunks.append(chunk_text)
    return chunks


CHAPTER_BLOCK_RE = re.compile(
    r"^CHAPTER\s+(XV|XVI|XVII|XVIII|XIX|XX|XXI|XXII|XXIII|XXIV|XXV)\.\s*$",
    re.MULTILINE,
)


def extract_named_blocks(sketches_text: str) -> dict[str, str]:
    """Pull additional skeptical-method chapters by Roman numeral.

    Patrick's Outlines I has these post-Ten-Tropes chapters of interest:
      XV   — The Five Tropes (of Agrippa)
      XVI  — The Two Tropes
      XVII — Why Sceptics utter Improbable Sentences sometimes
      XVIII — Of Sceptical Expressions (the equipollence sayings)
      XIX  — Of the Sceptical Expression 'No More'

    We treat XV and XVI as additional skeptical-mode source material. XVII–XIX
    are about Pyrrhonist methodology rather than first-order skeptical
    arguments and are skipped for now.
    """
    blocks = {}
    chap_matches = list(CHAPTER_BLOCK_RE.finditer(sketches_text))
    for i, m in enumerate(chap_matches):
        chap_num = m.group(1)
        if chap_num not in ("XV", "XVI"):
            continue
        body_start = m.end()
        body_end = chap_matches[i + 1].start() if i + 1 < len(chap_matches) else len(sketches_text)
        body = sketches_text[body_start:body_end].strip()
        body = MARGIN_NUM_RE.sub("", body)
        label = {"XV": "AGRIPPA", "XVI": "TWO"}[chap_num]
        blocks[label] = body
    return blocks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None,
                    help="Cap on number of pairs to write (default: all available)")
    ap.add_argument("--all", action="store_true",
                    help="Emit every extractable pair (no sampling)")
    args = ap.parse_args()

    raw = SRC.read_text(encoding="utf-8")
    sketches = find_sketches_section(raw)

    tropes = extract_tropes(sketches)
    print(f"Found {len(tropes)} named Tropes (Aenesidemus's Ten).")
    blocks = extract_named_blocks(sketches)
    print(f"Found {len(blocks)} additional skeptical-method chapters: {list(blocks.keys())}")

    all_pairs: list[dict] = []
    for name, body in tropes.items():
        chunks = chunk_paragraphs(body)
        for j, c in enumerate(chunks, 1):
            all_pairs.append({
                "trope": name,
                "chunk_index": j,
                "passage": c,
            })
    for name, body in blocks.items():
        chunks = chunk_paragraphs(body)
        for j, c in enumerate(chunks, 1):
            all_pairs.append({
                "trope": name,
                "chunk_index": j,
                "passage": c,
            })
    print(f"Built {len(all_pairs)} chunks across {len(tropes)} named Tropes + {len(blocks)} method chapters.")

    if args.all:
        sample = all_pairs
    else:
        rng = random.Random(SEED)
        n = args.limit if args.limit is not None else min(SAMPLE_N, len(all_pairs))
        sample = rng.sample(all_pairs, k=min(n, len(all_pairs)))

    with OUT.open("w", encoding="utf-8") as f:
        for idx, p in enumerate(sample, 1):
            rec = {"id": f"sextus_pair_{idx:03d}", **p}
            f.write(json.dumps(rec) + "\n")
    print(f"Wrote {len(sample)} pairs -> {OUT}")


if __name__ == "__main__":
    main()
