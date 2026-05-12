"""Parse Aquinas's *Summa Theologica* Part I (Gutenberg #17611, Fathers of the
English Dominican Province 1911 translation) into (objection, reply) pairs.

Each article has the structure:
    [N] ARTICLE [I, Q. n, Art. m]
    Whether ... ? (the article title)
    Objection 1: ...
    Obj. 2: ...
    Obj. 3: ...
    _On the contrary,_ ...
    _I answer that,_ ...
    Reply Obj. 1: ...
    Reply Obj. 2: ...
    Reply Obj. 3: ...

We extract (objection N, reply to objection N) pairs from each article,
keeping the article title for context. Each pair is a separate training
example for the objection-reply form.

Reads:  corpus/poc/aquinas_summa1_raw.txt
Writes: corpus/poc/aquinas_pairs.jsonl
"""

import argparse
import json
import random
import re
from pathlib import Path

SRC = Path(__file__).parent / "aquinas_summa1_raw.txt"
OUT = Path(__file__).parent / "aquinas_pairs.jsonl"

START_MARKER = "*** START OF THE PROJECT GUTENBERG EBOOK"
END_MARKER = "*** END OF THE PROJECT GUTENBERG EBOOK"

ARTICLE_RE = re.compile(r"^(?:FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH|ELEVENTH|TWELFTH)\s+ARTICLE\b.*?\[I,\s*Q\.\s*(\d+),\s*Art\.\s*(\d+)\]", re.MULTILINE)
# Objections can be "Objection N:" or "Obj. N:"
OBJ_RE = re.compile(r"^(?:Objection|Obj\.)\s+(\d+):\s*(.+?)(?=\n\s*(?:Obj\.|Objection|_On the contrary,_|Reply Obj\.|_______________________))", re.MULTILINE | re.DOTALL)
REPLY_RE = re.compile(r"^Reply\s+Obj\.\s+(\d+):\s*(.+?)(?=\n\s*(?:Reply Obj\.|_______________________|^[A-Z]+\s+ARTICLE|\Z))", re.MULTILINE | re.DOTALL)
TITLE_RE = re.compile(r"^(Whether\s+.+?\?)\s*$", re.MULTILINE)

MIN_LEN = 80
MAX_LEN = 1200
SAMPLE_N = 60
SEED = 42


def clean(text: str) -> str:
    """Normalize whitespace and strip italics underscores."""
    text = re.sub(r"_([^_]+)_", r"\1", text)  # remove italics markers
    text = re.sub(r"\s+", " ", text).strip()
    return text


def split_articles(text: str) -> list[tuple[str, str]]:
    """Yield (article_header, article_body) by splitting on ARTICLE markers."""
    matches = list(re.finditer(r"^(?:FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH|ELEVENTH|TWELFTH)\s+ARTICLE\b.*$", text, re.MULTILINE))
    articles = []
    for i, m in enumerate(matches):
        header = m.group(0)
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end]
        articles.append((header, body))
    return articles


def extract_pairs_from_article(header: str, body: str, qa_key: str) -> list[dict]:
    """Find Obj N + Reply Obj N + article title; return list of pair dicts."""
    # Article title
    title_m = TITLE_RE.search(body)
    title = clean(title_m.group(1)) if title_m else "(no title)"

    # Build maps of objection N -> text, reply N -> text
    objs: dict[str, str] = {}
    for m in OBJ_RE.finditer(body):
        n, text = m.group(1), clean(m.group(2))
        objs[n] = text

    replies: dict[str, str] = {}
    for m in REPLY_RE.finditer(body):
        n, text = m.group(1), clean(m.group(2))
        replies[n] = text

    pairs = []
    for n, obj_text in objs.items():
        if n not in replies:
            continue
        reply_text = replies[n]
        if not (MIN_LEN <= len(obj_text) <= MAX_LEN and MIN_LEN <= len(reply_text) <= MAX_LEN):
            continue
        pairs.append({
            "article_key": qa_key,
            "article_title": title,
            "objection_n": n,
            "objection": obj_text,
            "reply": reply_text,
        })
    return pairs


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

    articles = split_articles(raw)
    print(f"Split into {len(articles)} articles.")

    all_pairs: list[dict] = []
    for header, body in articles:
        m = re.search(r"\[I,\s*Q\.\s*(\d+),\s*Art\.\s*(\d+)\]", header)
        qa_key = f"I-Q{m.group(1)}-A{m.group(2)}" if m else header[:30]
        pairs = extract_pairs_from_article(header, body, qa_key)
        all_pairs.extend(pairs)
    print(f"Extracted {len(all_pairs)} (objection, reply) pairs across all articles.")

    if args.all:
        sample = all_pairs
    else:
        rng = random.Random(SEED)
        n = args.limit if args.limit is not None else min(SAMPLE_N, len(all_pairs))
        sample = rng.sample(all_pairs, k=min(n, len(all_pairs)))

    with OUT.open("w", encoding="utf-8") as f:
        for idx, p in enumerate(sample, 1):
            rec = {"id": f"aquinas_pair_{idx:03d}", **p}
            f.write(json.dumps(rec) + "\n")
    print(f"Wrote {len(sample)} pairs -> {OUT}")


if __name__ == "__main__":
    main()
