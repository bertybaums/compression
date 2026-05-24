"""
Build the Phase-0 essay control corpus for the form-diverse pilot.

The form-diverse arm trains on the dialogue/objection-reply pairs in
ugf_forms_corpus.jsonl. The control arm must be identical in everything except
*form*: same size, same plain (prompt, response) shape, same vocabulary, drawn
from the v1 essay distribution. This script renders a size-matched sample of the
v1 reasoning corpus into that shape — prompt = the content_type template applied
to the topic (exactly what v1 SFT trained on), response = the UGF essay — so the
only difference between the two arms is the structure of the data.

Held-out documents are excluded (same heldout_ids + random_val_fraction the v1
SFT used) so the control never trains on anything in the holdout bench.

Usage (on fortyfive):
    python -m reasoner.build_phase0_essay_control \\
        --reasoning corpus/processed/ugf_reasoning.jsonl \\
        --heldout corpus/processed/heldout_ids.json \\
        --out corpus/processed/phase0_essay_control.jsonl \\
        --n 2766
"""

import argparse
import json
import random
from pathlib import Path

from reasoner.data_sft import CONTENT_TYPES, _stable_hash_in_val


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reasoning", default="corpus/processed/ugf_reasoning.jsonl")
    parser.add_argument("--heldout", default="corpus/processed/heldout_ids.json")
    parser.add_argument("--out", default="corpus/processed/phase0_essay_control.jsonl")
    parser.add_argument("--n", type=int, default=2766, help="Match the compliant form-pair count.")
    parser.add_argument("--random-val-fraction", type=float, default=0.05,
                        help="Mirror v1 SFT: exclude this random fraction (the val split).")
    parser.add_argument("--seed", type=int, default=20260524)
    parser.add_argument("--text-field", default="ugf_text")
    args = parser.parse_args()

    heldout_doc_ids = set()
    if Path(args.heldout).exists():
        with open(args.heldout) as f:
            heldout_doc_ids = {pid.rsplit("-", 1)[0] for pid in json.load(f)["heldout_passage_ids"]}
        print(f"Heldout doc-keys: {len(heldout_doc_ids)}")

    candidates = []
    n_seen = n_no_ct = n_heldout = n_short = 0
    with open(args.reasoning) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            n_seen += 1
            if not r.get("compliant", True):
                continue
            rid = r.get("id", "")
            doc_key = rid.rsplit("-", 1)[0] if rid else ""
            if (doc_key in heldout_doc_ids) or _stable_hash_in_val(rid, args.random_val_fraction):
                n_heldout += 1
                continue
            ct = r.get("content_type")
            if ct not in CONTENT_TYPES:
                n_no_ct += 1
                continue
            resp = (r.get(args.text_field) or "").strip()
            if not resp or len(resp.split()) < 10:
                n_short += 1
                continue
            candidates.append({
                "id": rid,
                "prompt": CONTENT_TYPES[ct].format(topic=r.get("topic", "")),
                "response": resp,
                "content_type": ct,
                "compliant": True,
            })

    print(f"Scanned {n_seen}; eligible {len(candidates)} "
          f"(skipped {n_heldout} heldout, {n_no_ct} no content_type, {n_short} short)")
    if len(candidates) < args.n:
        print(f"WARNING: only {len(candidates)} eligible, fewer than requested {args.n}")
    rng = random.Random(args.seed)
    rng.shuffle(candidates)
    sample = candidates[: args.n]

    with open(args.out, "w", encoding="utf-8") as fout:
        for rec in sample:
            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"Wrote {len(sample)} essay-control pairs -> {args.out}")
    from collections import Counter
    print(f"content_type mix: {dict(Counter(r['content_type'] for r in sample))}")


if __name__ == "__main__":
    main()
