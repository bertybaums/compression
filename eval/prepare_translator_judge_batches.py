"""
Prepare blinded judge-input batches for the Translator-quality LLM judge.

Reads ≥1 EN→UGF result files and produces per-system batches.

Each batch item has:
    {"id": <str>, "english_source": <str>, "ugf_translation": <str>}

The judge sees nothing identifying which translator produced the translation.

Source files must have at least these fields per record:
    id, english_query, ugf_query

This is the schema written by both run_logic_bench.py (May 5 trained T5)
and run_structured_translator_bench.py (new structured-output translator).
"""

import argparse
import json
from pathlib import Path

ROOT = Path("/Users/bbaum/Documents/_RCDS/compression/eval")
OUT = ROOT / "judge_input_translator"
JUDGE_OUT = ROOT / "judge_output_translator"
BATCH_SIZE = 40


def prepare(sources: dict[str, Path]) -> list[dict]:
    OUT.mkdir(exist_ok=True)
    JUDGE_OUT.mkdir(exist_ok=True)
    manifest: list[dict] = []

    for label, path in sources.items():
        items: list[dict] = []
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                ugf = r.get("ugf_query", "")
                if not ugf or ugf.startswith("<"):
                    continue
                items.append({
                    "id": r["id"],
                    "english_source": r["english_query"],
                    "ugf_translation": ugf,
                })

        n = len(items)
        n_batches = (n + BATCH_SIZE - 1) // BATCH_SIZE
        for b in range(n_batches):
            chunk = items[b * BATCH_SIZE : (b + 1) * BATCH_SIZE]
            out_path = OUT / f"{label}_batch_{b+1:02d}.jsonl"
            with open(out_path, "w") as fh:
                for item in chunk:
                    fh.write(json.dumps(item) + "\n")
            manifest.append({
                "label": label,
                "batch": b + 1,
                "n_items": len(chunk),
                "input_path": str(out_path),
                "output_path": str(JUDGE_OUT / f"{label}_batch_{b+1:02d}.jsonl"),
                "source_file": str(path),
            })

    manifest_path = ROOT / "judge_manifest_translator.json"
    with open(manifest_path, "w") as fh:
        json.dump(manifest, fh, indent=2)

    print(f"Prepared {len(manifest)} batches across {len(sources)} sources.")
    for label in sources:
        n = sum(m["n_items"] for m in manifest if m["label"] == label)
        nb = sum(1 for m in manifest if m["label"] == label)
        print(f"  {label}: {n} items in {nb} batches")
    print(f"Manifest: {manifest_path}")
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        action="append",
        required=True,
        help="LABEL=PATH for each result file. Repeat for multiple systems.",
    )
    args = parser.parse_args()

    sources: dict[str, Path] = {}
    for spec in args.source:
        if "=" not in spec:
            raise SystemExit(f"--source must be LABEL=PATH, got {spec!r}")
        label, path_str = spec.split("=", 1)
        sources[label] = Path(path_str)

    prepare(sources)


if __name__ == "__main__":
    main()
