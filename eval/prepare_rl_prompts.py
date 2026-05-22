"""
Build the RL training-prompt set from the CoT corpus heldout slice.

For the smoke test we want ~500 English prompts of the same shape v2 was
trained on. The simplest source: take the heldout slice of the CoT corpus
(by the existing per-source-val mechanism) and pull the prompt_text field.

Heldout is small but the prompts themselves are not the heldout-target —
they're inputs the RL model has never been trained on as supervised labels.
That's fine for RL prompts: the model only learns from its own rollouts
plus the judge's reward.

Usage:
    python -m eval.prepare_rl_prompts \\
        --cot corpus/processed/ugf_cot.jsonl \\
        --out corpus/processed/rl_train_prompts.jsonl \\
        --n 500
"""

import argparse
import hashlib
import json
import random
from pathlib import Path


def _stable_hash_in_val(rid: str, fraction: float, buckets: int = 10000) -> bool:
    if fraction <= 0 or not rid:
        return False
    digest = hashlib.md5(rid.encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:4], "big") % buckets
    return bucket < int(fraction * buckets)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cot", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--n", type=int, default=500)
    parser.add_argument("--seed", type=int, default=20260519)
    parser.add_argument("--heldout-fraction", type=float, default=0.05,
                        help="Match the SFT random_val_fraction. Use these heldout prompts for RL.")
    args = parser.parse_args()

    prompts = []
    with open(args.cot) as f:
        for line in f:
            r = json.loads(line)
            rid = r.get("id", "")
            if not _stable_hash_in_val(rid, args.heldout_fraction):
                continue
            p = (r.get("prompt_text") or "").strip()
            if not p:
                continue
            prompts.append({"id": rid, "english_query": p, "track": r.get("track")})

    rng = random.Random(args.seed)
    rng.shuffle(prompts)
    prompts = prompts[: args.n]

    with open(args.out, "w") as f:
        for p in prompts:
            f.write(json.dumps(p) + "\n")
    print(f"Wrote {len(prompts)} RL prompts to {args.out}")
    from collections import Counter
    tracks = Counter(p["track"] for p in prompts)
    print(f"Tracks: {dict(tracks)}")


if __name__ == "__main__":
    main()
