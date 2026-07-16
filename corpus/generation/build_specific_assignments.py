"""
Stage 2 of ARM C (prompt informativeness) -- pair the case pool to the 400K ids.

Emits an assignments file with the SAME schema as matched_prompts_400k.jsonl, but
with `topic` replaced by a SPECIFIC CASE from the pool (the original general
subject is preserved as `topic_area`). That is the whole trick: the ARM B runner
formats POINTED_CONTENT_TYPES[ct].format(topic=...), so feeding it this file makes
it emit prompts that carry particulars -- same templates, same form instructions,
same teachers, same id/source_model routing as ARM B. Only the informativeness of
the slot changes, which is exactly the B-vs-C contrast.

    python3 -m corpus.generation.build_specific_assignments \
        --assignments corpus/processed/matched_prompts_400k.jsonl \
        --pool corpus/processed/specific_cases_pool.jsonl \
        --output corpus/processed/specific_assignments_400k.jsonl

Cases are dealt round-robin within each (topic_area, content_type) bucket, so if the
pool saturated below 1.0 coverage the reuse is spread evenly rather than concentrated.
Prints the achieved prompt:example ratio -- the number the whole arm exists to move
(arms A and B sit at 0.0009).
"""
import argparse
import json
import random
from collections import defaultdict


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--assignments", required=True)
    ap.add_argument("--pool", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--seed", type=int, default=20260716)
    args = ap.parse_args()

    pool = defaultdict(list)
    with open(args.pool, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            pool[(d["topic"], d["content_type"])].append(d["case"])

    rng = random.Random(args.seed)
    for v in pool.values():
        rng.shuffle(v)

    rows = []
    with open(args.assignments, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    # Deal round-robin per bucket so reuse (if the pool saturated short) is even.
    cursor = defaultdict(int)
    missing = defaultdict(int)
    used = set()
    n_out = 0
    with open(args.output, "w", encoding="utf-8") as out:
        for a in rows:
            k = (a["topic"], a["content_type"])
            cases = pool.get(k)
            if not cases:
                missing[k] += 1
                continue
            case = cases[cursor[k] % len(cases)]
            cursor[k] += 1
            used.add(case)
            rec = dict(a)
            rec["topic_area"] = a["topic"]   # keep the original general subject
            rec["topic"] = case              # the slot the POINTED template fills
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n_out += 1

    print(f"examples written : {n_out:,}")
    print(f"unique cases used: {len(used):,}")
    print(f"prompt:example   : {len(used)/n_out:.4f}   (arms A and B sit at 0.0009)")
    print(f"reuse/case       : {n_out/max(1,len(used)):.2f}")
    if missing:
        tot = sum(missing.values())
        print(f"\nWARNING: {tot:,} examples dropped -- {len(missing)} bucket(s) had no cases:")
        for k, v in sorted(missing.items(), key=lambda x: -x[1])[:5]:
            print(f"  {v:>7,}  {k[1]} / {k[0][:50]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
