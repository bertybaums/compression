"""
Prepare blinded judge batches for the 200M English-vocab baseline eval
(docs/english-baseline-design-2026-05-24.md).

Reads the 6 generation files eval/results/enbase_<arm>_<bench>_<TS>.jsonl
(arm in {ugf_n, en_n}; bench in {stress, holdout, cx_patched}), strips each to
{id, prompt, response}, and writes OPAQUE-named batch files
eval/judge_input_enbase/batch_NNN.jsonl plus enbase_judge_manifest.json mapping
each opaque batch back to (arm, bench).

Two design points enforced here:
  - ISOLATION: every batch contains exactly one arm + one bench (never mixes
    UGF and English in a batch). The precursor proved cross-register contrast
    depresses the restricted arm ~1 substance point on identical text.
  - BLINDING: opaque batch filenames + only {id, prompt, response} in the file
    (no arm label), so a Claude-subagent judge can't tell which arm it scores.

Usage:
  python3 eval/prepare_enbase_judge_batches.py --ts 20260602_081500
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).parent
ARMS = ["ugf_n", "en_n"]
BENCHES = ["stress", "holdout", "cx_patched"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ts", required=True, help="timestamp of the enbase_*_<ts>.jsonl run")
    ap.add_argument("--batch-size", type=int, default=45)
    ap.add_argument("--results-dir", default=str(ROOT / "results"))
    ap.add_argument("--out-dir", default=str(ROOT / "judge_input_enbase"))
    args = ap.parse_args()

    outd = Path(args.out_dir)
    outd.mkdir(exist_ok=True)
    (ROOT / "judge_output_enbase").mkdir(exist_ok=True)

    manifest = []
    bidx = 0
    for arm in ARMS:
        for bench in BENCHES:
            p = Path(args.results_dir) / f"enbase_{arm}_{bench}_{args.ts}.jsonl"
            if not p.exists():
                print(f"WARN missing {p}")
                continue
            items = []
            with open(p) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    r = json.loads(line)
                    items.append({
                        "id": r.get("id", ""),
                        "prompt": r.get("prompt", ""),
                        "response": r.get("ugf_response", ""),
                    })
            for i in range(0, len(items), args.batch_size):
                bidx += 1
                chunk = items[i:i + args.batch_size]
                inp = outd / f"batch_{bidx:03d}.jsonl"
                with open(inp, "w", encoding="utf-8") as f:
                    for it in chunk:
                        f.write(json.dumps(it, ensure_ascii=False) + "\n")
                manifest.append({
                    "batch": f"batch_{bidx:03d}", "arm": arm, "bench": bench,
                    "n": len(chunk), "input": str(inp),
                    "output": str(ROOT / "judge_output_enbase" / f"batch_{bidx:03d}.jsonl"),
                })

    with open(ROOT / "enbase_judge_manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"Prepared {len(manifest)} batches ({sum(m['n'] for m in manifest)} items)")
    for arm in ARMS:
        for bench in BENCHES:
            ms = [m for m in manifest if m["arm"] == arm and m["bench"] == bench]
            if ms:
                print(f"  {arm}/{bench}: {sum(m['n'] for m in ms)} items in {len(ms)} batch(es)")


if __name__ == "__main__":
    main()
