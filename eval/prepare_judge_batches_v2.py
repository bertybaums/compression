"""
Generalized judge-batch prep — accepts any (label, source_path) pairs.

Reads each source JSONL, strips to (id, english_query, ugf_response),
splits into batches of N items, writes blinded inputs under
eval/judge_input/, and a manifest under eval/judge_manifest_v2.json.

The original prepare_judge_batches.py was Layer-2-specific. This version
handles Layer-3 + Layer-4 + patched-cx + future runs.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path("/Users/bbaum/Documents/_RCDS/compression/eval")
INPUT_DIR = ROOT / "judge_input"
OUTPUT_DIR = ROOT / "judge_output"
INPUT_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

BATCH_SIZE = 40


def prep_one(label: str, source_path: Path, batch_size: int = BATCH_SIZE) -> list[dict]:
    items = []
    with open(source_path) as fh:
        for line in fh:
            r = json.loads(line)
            ugf = r.get("ugf_response", "")
            if not ugf:
                continue
            items.append(
                {
                    "id": r["id"],
                    "english_query": r.get("english_query", r.get("question", "")),
                    "ugf_response": ugf,
                }
            )
    n_batches = (len(items) + batch_size - 1) // batch_size
    manifest = []
    for b in range(n_batches):
        chunk = items[b * batch_size : (b + 1) * batch_size]
        in_path = INPUT_DIR / f"{label}_batch_{b+1:02d}.jsonl"
        out_path = OUTPUT_DIR / f"{label}_batch_{b+1:02d}.jsonl"
        with open(in_path, "w") as fh:
            for it in chunk:
                fh.write(json.dumps(it, ensure_ascii=False) + "\n")
        manifest.append(
            {
                "label": label,
                "batch": b + 1,
                "n_items": len(chunk),
                "input_path": str(in_path),
                "output_path": str(out_path),
            }
        )
    return manifest


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", action="append", required=True,
                   help="LABEL=PATH pairs, can be repeated")
    p.add_argument("--manifest-out", default=str(ROOT / "judge_manifest_v2.json"))
    p.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    args = p.parse_args()

    all_manifest = []
    for spec in args.source:
        if "=" not in spec:
            print(f"Bad --source spec: {spec}", file=sys.stderr)
            sys.exit(1)
        label, path = spec.split("=", 1)
        manifest = prep_one(label, Path(path), args.batch_size)
        all_manifest.extend(manifest)
        print(f"  {label}: {sum(m['n_items'] for m in manifest)} items in {len(manifest)} batches")

    with open(args.manifest_out, "w") as fh:
        json.dump(all_manifest, fh, indent=2)
    print(f"\nManifest: {args.manifest_out}  ({len(all_manifest)} batches total)")


if __name__ == "__main__":
    main()
