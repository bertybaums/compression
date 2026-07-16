"""
Prompt-diversity audit for SFT corpora.

Written July 16, 2026, after an audit found that BOTH arms of the form-controlled
retrain carry only **380 unique prompts across ~400,000 examples** (76 topics x 5
content_types, ~1,053 repeats each), while responses are ~all distinct. That makes
p(response | prompt) effectively unconditional within a topic bucket: the prompt
identifies a bucket, not a target, so attending to prompt detail beyond bucket-ID
earns nothing in training loss. A model trained this way cannot learn
prompt-conditioning -- which is precisely the deficit the project has been chasing
through capacity, vocabulary, DPO and RL, all of which held this variable fixed.

The stress bench, by contrast, is 30 unique specific prompts. 380 memorizable
buckets at train time -> novel prompts at eval time IS the distribution shift.

Run this on any SFT corpus BEFORE spending GPU on it:

    python3 -m corpus.generation.audit_prompt_diversity corpus/processed/ugf_n_sft_400k.jsonl
    python3 -m corpus.generation.audit_prompt_diversity corpus/processed/*.jsonl --quiet

Reports the prompt:example ratio and flags corpora where the prompt cannot carry
enough information to be worth conditioning on.
"""
import argparse
import json
import sys
from collections import Counter


def audit(path: str, warn_ratio: float) -> dict:
    prompts: Counter = Counter()
    responses = set()
    topics = set()
    total = 0
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        total += 1
        p = d.get("prompt")
        if p is not None:
            prompts[p] += 1
        r = d.get("response")
        if r is not None:
            responses.add(r)
        t = d.get("topic")
        if t is not None:
            topics.add(t)

    uniq = len(prompts)
    out = {
        "path": path, "examples": total, "unique_prompts": uniq,
        "unique_responses": len(responses), "unique_topics": len(topics),
        "repeats": (total / uniq) if uniq else None,
    }

    print(f"\n{path}")
    print(f"  examples          : {total:,}")
    if not uniq:
        print("  unique prompts    : (no 'prompt' field -- pretraining corpus?)")
        if topics:
            print(f"  unique topics     : {len(topics):,}")
        return out
    print(f"  unique prompts    : {uniq:,}")
    print(f"  unique responses  : {len(responses):,}")
    if topics:
        print(f"  unique topics     : {len(topics):,}")
    print(f"  repeats/prompt    : {out['repeats']:.1f}")

    # The diagnostic quantity: how many distinct responses share one prompt? If it is
    # large, the prompt cannot be a target -- only a bucket label -- and conditioning
    # on it beyond bucket-ID is not rewarded.
    if responses:
        per = len(responses) / uniq
        print(f"  distinct responses per prompt: ~{per:.0f}")

    ratio = uniq / total
    print(f"  prompt:example    : {ratio:.4f}  (warn below {warn_ratio})")
    if ratio < warn_ratio:
        print("  *** WARNING: prompt-uninformative corpus. Each prompt maps to many")
        print("      different responses, so p(response|prompt) is ~unconditional within")
        print("      a bucket and prompt-attention earns nothing during training. Do not")
        print("      interpret a prompt-conditioning failure as a model/capacity limit")
        print("      until this is varied -- it is a corpus property, not a model one.")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--warn-ratio", type=float, default=0.1,
                    help="warn when unique_prompts/examples falls below this (default 0.1)")
    args = ap.parse_args()
    flagged = 0
    for p in args.paths:
        try:
            r = audit(p, args.warn_ratio)
        except FileNotFoundError:
            print(f"\n{p}\n  (not found)")
            continue
        if r["unique_prompts"] and r["unique_prompts"] / r["examples"] < args.warn_ratio:
            flagged += 1
    print(f"\n{flagged} corpus/corpora flagged as prompt-uninformative.")
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())
