"""
Sample N matched (topic, content_type) records from ugf_reasoning.jsonl for the
200M English-vocab baseline (docs/english-baseline-design-2026-05-24.md).

Emits two files sharing the SAME N ids:
  - matched_prompts (id, topic, content_type, source_model, domain)
      -> drives English-N generation. Each prompt keeps its source_model so the
         English arm uses the SAME teacher per prompt (teacher-mix held constant).
  - ugf_n_sft (id, prompt, response, content_type)
      -> the UGF-N training arm (prompt = content_type template on topic,
         response = the existing ugf_text). Same shape as build_phase0_essay_control.

Filters mirror build_phase0_essay_control (compliant, non-heldout, valid
content_type, response >= 10 words) PLUS source_model in the current teacher
ensemble — so the English arm can match the teacher per prompt (excludes the
~19% qwen-generated records, which the current ensemble can't reproduce).

Usage (fortyfive):
  python -m reasoner.sample_matched_n --n 400000
"""
import argparse
import json
import random
from collections import Counter
from pathlib import Path

# Render UGF-N prompts with the SAME templates that elicited the corpus (and that
# the English-N generator uses), so both arms get byte-identical prompts per
# (topic, content_type). _stable_hash_in_val mirrors the v1 SFT val-split exclusion.
from corpus.generation.generate_reasoning import CONTENT_TYPES
from reasoner.data_sft import _stable_hash_in_val

DEFAULT_TEACHERS = ["openai/gpt-oss-120b", "google/gemma-4-26b"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reasoning", default="corpus/processed/ugf_reasoning.jsonl")
    ap.add_argument("--heldout", default="corpus/processed/heldout_ids.json")
    ap.add_argument("--out-prompts", default="corpus/processed/matched_prompts_400k.jsonl")
    ap.add_argument("--out-ugf-sft", default="corpus/processed/ugf_n_sft_400k.jsonl")
    ap.add_argument("--n", type=int, default=400000)
    ap.add_argument("--teachers", nargs="+", default=DEFAULT_TEACHERS)
    ap.add_argument("--random-val-fraction", type=float, default=0.05,
                    help="Mirror v1 SFT: exclude this random fraction (the val split).")
    ap.add_argument("--seed", type=int, default=20260525)
    ap.add_argument("--text-field", default="ugf_text")
    args = ap.parse_args()

    teachers = set(args.teachers)
    heldout_doc_ids = set()
    if Path(args.heldout).exists():
        with open(args.heldout) as f:
            heldout_doc_ids = {pid.rsplit("-", 1)[0] for pid in json.load(f)["heldout_passage_ids"]}
    print(f"Heldout doc-keys: {len(heldout_doc_ids)}; teacher filter: {sorted(teachers)}")

    candidates = []
    n_seen = n_noncompliant = n_heldout = n_noct = n_teacher = n_short = 0
    with open(args.reasoning) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            n_seen += 1
            if not r.get("compliant", True):
                n_noncompliant += 1
                continue
            rid = r.get("id", "")
            doc_key = rid.rsplit("-", 1)[0] if rid else ""
            if (doc_key in heldout_doc_ids) or _stable_hash_in_val(rid, args.random_val_fraction):
                n_heldout += 1
                continue
            ct = r.get("content_type")
            if ct not in CONTENT_TYPES:
                n_noct += 1
                continue
            sm = r.get("source_model", "")
            if sm not in teachers:
                n_teacher += 1
                continue
            resp = (r.get(args.text_field) or "").strip()
            if not resp or len(resp.split()) < 10:
                n_short += 1
                continue
            candidates.append({
                "id": rid, "topic": r.get("topic", ""), "content_type": ct,
                "source_model": sm, "domain": r.get("metadata", {}).get("domain", ""),
                "response": resp,
            })

    print(f"Scanned {n_seen}; eligible {len(candidates)} (skipped: "
          f"{n_noncompliant} noncompliant, {n_heldout} heldout/val, {n_noct} no-content_type, "
          f"{n_teacher} other-teacher, {n_short} short)")
    if len(candidates) < args.n:
        print(f"WARNING: only {len(candidates)} eligible < requested {args.n}; using all")
    rng = random.Random(args.seed)
    rng.shuffle(candidates)
    sample = candidates[: args.n]

    Path(args.out_prompts).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out_prompts, "w", encoding="utf-8") as fp, \
            open(args.out_ugf_sft, "w", encoding="utf-8") as fu:
        for rec in sample:
            fp.write(json.dumps({
                "id": rec["id"], "topic": rec["topic"], "content_type": rec["content_type"],
                "source_model": rec["source_model"], "domain": rec["domain"],
            }, ensure_ascii=False) + "\n")
            fu.write(json.dumps({
                "id": rec["id"],
                "prompt": CONTENT_TYPES[rec["content_type"]].format(topic=rec["topic"]),
                "response": rec["response"], "content_type": rec["content_type"],
                "compliant": True,
            }, ensure_ascii=False) + "\n")

    print(f"Wrote {len(sample)} -> {args.out_prompts} + {args.out_ugf_sft}")
    print(f"content_type mix: {dict(Counter(r['content_type'] for r in sample))}")
    print(f"teacher mix:      {dict(Counter(r['source_model'] for r in sample))}")


if __name__ == "__main__":
    main()
