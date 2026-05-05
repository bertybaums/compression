"""
Sample held-out items from the corpus and format as a benchmark JSONL.

The held-out subset is determined by the same logic the data loader uses at
training time:
  - doc-key match against heldout_ids.json (catches cxbot/misccorpora records
    whose source passage is held out)
  - stable MD5-hash random fraction (catches main reasoning records whose
    doc-key is the no-op 'reasoning')

The output benchmark schema mirrors logic_textbook_bench.jsonl so existing
runners (eval/run_logic_bench.py, eval/run_comparator.py) work on it:

  {id, type, exercise=None, subquestion=None, instruction='',
   question=<topic>, expected_answer=<original ugf_text from held-out trace>,
   source='corpus heldout: <source_basename>'}

Where `type` is the corpus content_type (concept_explanation,
chain_of_thought, socratic_dialogue, argument_analysis, thought_experiment,
counterexample_analysis, analogical_analysis, conditional_analysis).

Usage:
  python -m eval.sample_holdout \\
      --main-n 70 --cxbot-n 50 --misc-n 50 \\
      --out eval/sets/holdout_bench.jsonl
"""

import argparse
import hashlib
import json
import random
from pathlib import Path


def stable_hash_in_val(rid: str, fraction: float, buckets: int = 10000) -> bool:
    if fraction <= 0 or not rid:
        return False
    digest = hashlib.md5(rid.encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:4], "big") % buckets
    return bucket < int(fraction * buckets)


def load_heldout(path: str, heldout_doc_ids: set, random_val_fraction: float = 0.05) -> list[dict]:
    items = []
    with open(path) as f:
        for line in f:
            r = json.loads(line)
            if not r.get("compliant"):
                continue
            rid = r.get("id", "")
            doc_key = rid.rsplit("-", 1)[0] if rid else ""
            is_doc = bool(heldout_doc_ids) and doc_key in heldout_doc_ids
            is_rand = stable_hash_in_val(rid, random_val_fraction)
            if is_doc or is_rand:
                items.append(r)
    return items


def to_bench_entry(rec: dict, source_label: str) -> dict | None:
    if not rec.get("ugf_text") or not rec.get("topic") or not rec.get("content_type"):
        return None
    return {
        "id": rec["id"],
        "type": rec["content_type"],
        "instruction": "",  # the CONTENT_TYPES template provides the instructional prefix
        "question": rec["topic"],
        "expected_answer": rec["ugf_text"],
        "source": f"corpus heldout: {source_label}",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--main-corpus", default="corpus/processed/ugf_reasoning.jsonl")
    parser.add_argument("--cxbot-corpus", default="corpus/processed/ugf_reasoning_cxbot.jsonl")
    parser.add_argument("--misccorpora-corpus", default="corpus/processed/ugf_reasoning_misccorpora.jsonl")
    parser.add_argument("--heldout-path", default="corpus/processed/heldout_ids.json")
    parser.add_argument("--main-n", type=int, default=70)
    parser.add_argument("--cxbot-n", type=int, default=50)
    parser.add_argument("--misc-n", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    rng = random.Random(args.seed)

    # Load doc-key heldout list (used for cxbot/misccorpora)
    heldout_doc_ids = set()
    if args.heldout_path and Path(args.heldout_path).exists():
        with open(args.heldout_path) as f:
            passage_ids = json.load(f)["heldout_passage_ids"]
        heldout_doc_ids = {pid.rsplit("-", 1)[0] for pid in passage_ids}
        print(f"Loaded {len(heldout_doc_ids)} heldout doc-keys from {args.heldout_path}")

    bench = []

    # Main reasoning — only random_val_fraction applies (doc-key is no-op for reasoning-NNNNN)
    print(f"Scanning main corpus {args.main_corpus}...")
    main_held = load_heldout(args.main_corpus, heldout_doc_ids, random_val_fraction=0.05)
    print(f"  Held out: {len(main_held)}. Sampling {args.main_n}.")
    if len(main_held) >= args.main_n:
        main_sample = rng.sample(main_held, args.main_n)
    else:
        main_sample = main_held
    for r in main_sample:
        e = to_bench_entry(r, "main_reasoning")
        if e:
            bench.append(e)

    # cxbot — primarily doc-key heldout (random adds a slice)
    print(f"Scanning cxbot corpus {args.cxbot_corpus}...")
    cxbot_held = load_heldout(args.cxbot_corpus, heldout_doc_ids, random_val_fraction=0.05)
    print(f"  Held out: {len(cxbot_held)}. Sampling {args.cxbot_n}.")
    cxbot_sample = rng.sample(cxbot_held, min(args.cxbot_n, len(cxbot_held)))
    for r in cxbot_sample:
        e = to_bench_entry(r, "cxbot")
        if e:
            bench.append(e)

    # misccorpora
    print(f"Scanning misccorpora corpus {args.misccorpora_corpus}...")
    misc_held = load_heldout(args.misccorpora_corpus, heldout_doc_ids, random_val_fraction=0.05)
    print(f"  Held out: {len(misc_held)}. Sampling {args.misc_n}.")
    misc_sample = rng.sample(misc_held, min(args.misc_n, len(misc_held)))
    for r in misc_sample:
        e = to_bench_entry(r, "misccorpora")
        if e:
            bench.append(e)

    # Save
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for it in bench:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")

    print(f"\nWrote {len(bench)} items to {args.out}")
    # Distribution
    from collections import Counter
    by_type = Counter(it["type"] for it in bench)
    by_source = Counter(it["source"] for it in bench)
    print("By type:")
    for t, n in by_type.most_common():
        print(f"  {t}: {n}")
    print("By source:")
    for s, n in by_source.most_common():
        print(f"  {s}: {n}")


if __name__ == "__main__":
    main()
