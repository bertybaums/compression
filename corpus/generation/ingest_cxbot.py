"""
Ingest cx-bot counterexample-construction passages into the compression pipeline.

cx-bot (~/cx-bot/ on fortyfive, bertybaums/cx-bot on GitHub) contains 4,474
curated English passages that walk through definition and abductive
counterexamples across 16 philosophical domains. Each passage is ~800-1200
chars of clean, register-correct prose — exactly the counterexample-analysis
register missing from our good-thinking-bot + intro-ethics source material.

Two outputs:
  1. English-passage JSONL in the same schema as english_passages.jsonl, so
     generate_parallel.py can translate them without any changes.
  2. (After parallel translation) a small companion script emits the UGF side
     as reasoning-trace records so the Reasoner sees counterexample
     construction as its own content type.

Usage:
  python corpus/generation/ingest_cxbot.py \\
    --cxbot-root ~/cx-bot \\
    --output corpus/processed/english_passages_cxbot.jsonl
"""

import argparse
import json
from pathlib import Path


def iter_cxbot_records(cxbot_root: Path):
    """Yield (cx_type, subdir_file, record) tuples from defcx/ and abdcx/."""
    for cx_type in ("defcx", "abdcx"):
        dir_ = cxbot_root / "data" / cx_type
        if not dir_.is_dir():
            raise FileNotFoundError(f"Missing {dir_} — is --cxbot-root correct?")
        for path in sorted(dir_.glob("*.jsonl")):
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    yield cx_type, path.stem, json.loads(line)


def to_english_passage(cx_type: str, domain_file: str, rec: dict) -> dict:
    """Convert a cx-bot record into the english_passages.jsonl schema.

    Uses the `passage` field as the English text — it's the complete
    prose walkthrough and is the only field the parallel-corpus pipeline
    needs. Other structured fields are preserved as metadata for later
    use (e.g., building a counterexample-specific eval set).
    """
    passage = rec.get("passage", "").strip()
    if not passage:
        return None

    # IDs must match the parallel pipeline's expectation: prefix-domain-seq-suffix
    # We encode as: cxbot-{cxtype}-{subdomain}-{seq4}-passage
    # so that `id.rsplit('-', 1)[0]` gives a stable document key for hold-out.
    orig_id = rec.get("id", "")
    return {
        "id": f"cxbot-{cx_type}-{orig_id.replace('_','-')}-passage",
        "source": "cx-bot",
        "field": "passage",
        "text": passage,
        "metadata": {
            "cx_type": cx_type,
            "domain": rec.get("domain"),
            "subdomain": rec.get("subdomain"),
            "original_id": orig_id,
            # Preserve structured components for downstream eval:
            "definition": rec.get("definition"),
            "counterexample": rec.get("counterexample"),
            "missing_condition": rec.get("missing_condition"),
        },
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cxbot-root", type=Path, required=True,
                   help="Path to cx-bot repo checkout (contains data/defcx/ and data/abdcx/)")
    p.add_argument("--output", type=Path, required=True,
                   help="Output JSONL path (english_passages.jsonl schema)")
    args = p.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)

    n_written = 0
    n_skipped = 0
    by_type = {"defcx": 0, "abdcx": 0}
    with open(args.output, "w", encoding="utf-8") as out:
        for cx_type, dom_file, rec in iter_cxbot_records(args.cxbot_root):
            passage = to_english_passage(cx_type, dom_file, rec)
            if passage is None:
                n_skipped += 1
                continue
            out.write(json.dumps(passage, ensure_ascii=False) + "\n")
            n_written += 1
            by_type[cx_type] += 1

    print(f"Wrote {n_written} passages to {args.output}")
    print(f"  defcx: {by_type['defcx']}")
    print(f"  abdcx: {by_type['abdcx']}")
    if n_skipped:
        print(f"  skipped (no passage): {n_skipped}")


if __name__ == "__main__":
    main()
