"""
Re-blind the corpus-audit batches written by prepare_corpus_audit_v2.py.

Reads all `cot_batch_*.jsonl`, `existing_reasoning_batch_*.jsonl`,
`forms_batch_*.jsonl` from eval/judge_input_corpus_audit/, plus per-corpus
record metadata kept in memory, then:

- Assigns each record a fresh opaque id `audit-NNNN`.
- Shuffles ALL records together so corpus identity is invisible at the batch
  level (each blinded batch contains a mix from all three corpora).
- Splits into N_BATCHES blinded batches.
- Writes them to eval/judge_input_corpus_audit_blinded/audit_batch_NN.jsonl.
- Writes a truth map eval/judge_input_corpus_audit_blinded/audit_truth.json
  that maps opaque_id -> original_id, corpus, strat.

Subagent judges read only the blinded batches; the aggregator joins via the
truth map.
"""

import json
import random
from pathlib import Path

ROOT = Path("/Users/bbaum/Documents/_RCDS/compression/eval")
SRC = ROOT / "judge_input_corpus_audit"
DST = ROOT / "judge_input_corpus_audit_blinded"
JUDGE_OUT = ROOT / "judge_output_corpus_audit_blinded"
N_BATCHES = 12
SEED = 20260518


def collect_records():
    """Walk SRC/, attach corpus label from filename. Also pull strat from prepare script's per-corpus meta."""
    items = []
    for path in sorted(SRC.glob("*.jsonl")):
        # e.g. "cot_batch_03.jsonl" -> corpus "cot"
        corpus = path.stem.rsplit("_batch_", 1)[0]
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                items.append({
                    "original_id": r["id"],
                    "corpus": corpus,
                    "english_query": r["english_query"],
                    "ugf_response": r["ugf_response"],
                })
    return items


def main():
    rng = random.Random(SEED)
    records = collect_records()
    print(f"Loaded {len(records)} records from {SRC}")

    rng.shuffle(records)

    DST.mkdir(exist_ok=True)
    JUDGE_OUT.mkdir(exist_ok=True)

    truth = {}
    batch_sizes = [len(records) // N_BATCHES] * N_BATCHES
    for i in range(len(records) % N_BATCHES):
        batch_sizes[i] += 1

    cursor = 0
    n_per_batch = []
    for b, size in enumerate(batch_sizes, start=1):
        chunk = records[cursor:cursor + size]
        cursor += size
        out_path = DST / f"audit_batch_{b:02d}.jsonl"
        with open(out_path, "w") as f:
            for j, r in enumerate(chunk):
                opaque_id = f"audit-{(b-1)*100 + j:04d}"
                f.write(json.dumps({
                    "id": opaque_id,
                    "english_query": r["english_query"],
                    "ugf_response": r["ugf_response"],
                }) + "\n")
                truth[opaque_id] = {
                    "original_id": r["original_id"],
                    "corpus": r["corpus"],
                }
        n_per_batch.append((out_path.name, len(chunk)))

    truth_path = DST / "audit_truth.json"
    with open(truth_path, "w") as f:
        json.dump(truth, f, indent=2)

    print(f"Wrote {N_BATCHES} blinded batches to {DST}")
    for name, n in n_per_batch:
        print(f"  {name}: {n} items")
    print(f"Truth map: {truth_path}  ({len(truth)} entries)")

    # Sanity: per-corpus counts across the blinded set
    from collections import Counter
    c = Counter(v["corpus"] for v in truth.values())
    print(f"Per-corpus total: {dict(c)}")


if __name__ == "__main__":
    main()
