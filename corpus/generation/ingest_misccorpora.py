"""
Ingest misc-corpora (analogies, conditionals) extended passages into the
compression pipeline.

/misc-corpuses is a separate RCDS project that produced two SFT-curated
datasets for analogical reasoning and conditional reasoning. Each SFT record
contains a structured analysis followed by an `Extended passage:` block of
roughly 300 words of register-correct prose that embeds the reasoning move
(analogical mapping, conditional inference) in natural sentences.

We ingest only the `Extended passage:` portion. The structured analysis
preamble contains field labels (e.g. `Positive analogy (shared):`), bullet
dashes, and colons that would trip the UGF no-markdown rule. The prose
passage carries the reasoning content in natural prose, which is what
the parallel-corpus pipeline handles best.

Output: JSONL in the same schema as english_passages.jsonl so the
existing generate_parallel.py pipeline can translate it.

Usage:
  python corpus/generation/ingest_misccorpora.py \\
      --misc-root /path/to/misc-corpuses \\
      --output corpus/processed/english_passages_misccorpora.jsonl
"""

import argparse
import json
import re
from pathlib import Path


# The SFT assistant content always ends with an "Extended passage:" section.
# We split on it and take whatever follows.
_PASSAGE_RE = re.compile(r"\n\s*Extended passage:\s*\n", re.IGNORECASE)


def extract_passage(assistant_content: str) -> str | None:
    """Return the extended-passage portion of an SFT assistant response."""
    parts = _PASSAGE_RE.split(assistant_content, maxsplit=1)
    if len(parts) != 2:
        return None
    passage = parts[1].strip()
    return passage or None


def iter_sft_records(sft_path: Path):
    with open(sft_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def to_english_passage(rec: dict, corpus_name: str) -> dict | None:
    # Assistant content lives in the last message with role=assistant
    messages = rec.get("messages", [])
    assistant = next((m for m in reversed(messages) if m.get("role") == "assistant"), None)
    if assistant is None:
        return None
    passage = extract_passage(assistant.get("content", ""))
    if not passage:
        return None

    meta = rec.get("meta", {}) or {}
    orig_id = rec.get("id", "")
    # IDs: {corpus}-{orig_id_normalized}-passage
    # rsplit('-', 1)[0] gives the document key for hold-out stratification.
    normalized = orig_id.replace("_", "-")
    return {
        "id": f"misc-{corpus_name}-{normalized}-passage",
        "source": f"misc-{corpus_name}",
        "field": "extended_passage",
        "text": passage,
        "metadata": {
            "corpus": corpus_name,
            "original_id": orig_id,
            # Preserve the full structured meta so we can rebuild
            # corpus-aware eval slices later:
            **{k: v for k, v in meta.items() if v is not None},
        },
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--misc-root", type=Path, required=True,
                   help="Path to misc-corpuses repo (contains analogies/data/sft_analogies.jsonl etc.)")
    p.add_argument("--output", type=Path, required=True,
                   help="Output JSONL in english_passages.jsonl schema")
    p.add_argument("--corpora", nargs="+", default=["analogies", "conditionals"],
                   help="Which subcorpora to ingest (default: both)")
    args = p.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)

    n_written = 0
    n_skipped = 0
    by_corpus: dict[str, int] = {}

    with open(args.output, "w", encoding="utf-8") as out:
        for corpus in args.corpora:
            sft_path = args.misc_root / corpus / "data" / f"sft_{corpus}.jsonl"
            if not sft_path.is_file():
                print(f"WARN: missing {sft_path}, skipping {corpus}")
                continue
            count = 0
            for rec in iter_sft_records(sft_path):
                passage = to_english_passage(rec, corpus)
                if passage is None:
                    n_skipped += 1
                    continue
                out.write(json.dumps(passage, ensure_ascii=False) + "\n")
                n_written += 1
                count += 1
            by_corpus[corpus] = count

    print(f"Wrote {n_written} passages to {args.output}")
    for corpus, count in by_corpus.items():
        print(f"  {corpus}: {count}")
    if n_skipped:
        print(f"  skipped (missing passage / no assistant): {n_skipped}")


if __name__ == "__main__":
    main()
