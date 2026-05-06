"""
Prepare blinded judge-input batches for the LLM judge.

Reads the 4 Layer-2 result files, strips them to the minimum fields needed for
scoring (id, english_query, ugf_response), and splits them into batches that
will each be assigned to a single Claude subagent.

The input files contain `type`, `template`, `expected_answer` etc. — those are
NOT in the batch files, so the judge cannot use them to infer which system
produced the response. The mapping back to type/etc. happens at aggregation.
"""

import json
import os
from pathlib import Path

ROOT = Path("/Users/bbaum/Documents/_RCDS/compression/eval")
RESULTS = ROOT / "results" / "_jsonl"
OUT = ROOT / "judge_input"
OUT.mkdir(exist_ok=True)

SOURCES = {
    "reasoner_textbook": RESULTS / "logic_bench_20260505_143235.jsonl",
    "comparator_textbook": RESULTS / "comparator_logic_textbook_20260505_143019_with_english.jsonl",
    "reasoner_holdout": RESULTS / "logic_bench_20260505_152347.jsonl",
    "comparator_holdout": RESULTS / "comparator_holdout_20260505_152335_with_english.jsonl",
}

BATCH_SIZE = 40

manifest = []

for label, path in SOURCES.items():
    items = []
    with open(path) as fh:
        for line in fh:
            r = json.loads(line)
            items.append(
                {
                    "id": r["id"],
                    "english_query": r["english_query"],
                    "ugf_response": r["ugf_response"],
                }
            )

    n = len(items)
    n_batches = (n + BATCH_SIZE - 1) // BATCH_SIZE
    for b in range(n_batches):
        chunk = items[b * BATCH_SIZE : (b + 1) * BATCH_SIZE]
        out_path = OUT / f"{label}_batch_{b+1:02d}.jsonl"
        with open(out_path, "w") as fh:
            for item in chunk:
                fh.write(json.dumps(item) + "\n")
        manifest.append(
            {
                "label": label,
                "batch": b + 1,
                "n_items": len(chunk),
                "input_path": str(out_path),
                "output_path": str(ROOT / "judge_output" / f"{label}_batch_{b+1:02d}.jsonl"),
            }
        )

(ROOT / "judge_output").mkdir(exist_ok=True)

with open(ROOT / "judge_manifest.json", "w") as fh:
    json.dump(manifest, fh, indent=2)

print(f"Prepared {len(manifest)} batches across {len(SOURCES)} sources.")
for label in SOURCES:
    n = sum(m["n_items"] for m in manifest if m["label"] == label)
    nb = sum(1 for m in manifest if m["label"] == label)
    print(f"  {label}: {n} items in {nb} batches")
