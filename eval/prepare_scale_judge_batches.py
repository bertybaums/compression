"""
Prepare blinded judge batches for the scale study (docs/scale-study-design-2026-06-03.md).
Mirror of prepare_enbase_judge_batches.py, with arms = the three model sizes.

Reads eval/results/scale_<arm>_<bench>_<TS>.jsonl (arm in {50m, 200m, 1b};
bench in {stress, holdout, cx_patched}), strips to {id, prompt, response}, and
writes OPAQUE-named batches eval/judge_input_scale/batch_NNN.jsonl + a manifest.
Isolation (one arm+bench per batch) + opaque names keep the judges blind to which
size produced a response.

Usage:  python3 eval/prepare_scale_judge_batches.py --ts 20260603_xxxxxx
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).parent
ARMS = ["50m", "200m", "1b"]
BENCHES = ["stress", "holdout", "cx_patched"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ts", required=True)
    ap.add_argument("--batch-size", type=int, default=45)
    ap.add_argument("--results-dir", default=str(ROOT / "results"))
    ap.add_argument("--out-dir", default=str(ROOT / "judge_input_scale"))
    args = ap.parse_args()

    outd = Path(args.out_dir)
    outd.mkdir(exist_ok=True)
    (ROOT / "judge_output_scale").mkdir(exist_ok=True)

    manifest = []
    bidx = 0
    for arm in ARMS:
        for bench in BENCHES:
            p = Path(args.results_dir) / f"scale_{arm}_{bench}_{args.ts}.jsonl"
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
                    items.append({"id": r.get("id", ""), "prompt": r.get("prompt", ""),
                                  "response": r.get("ugf_response", "")})
            for i in range(0, len(items), args.batch_size):
                bidx += 1
                chunk = items[i:i + args.batch_size]
                inp = outd / f"batch_{bidx:03d}.jsonl"
                with open(inp, "w", encoding="utf-8") as f:
                    for it in chunk:
                        f.write(json.dumps(it, ensure_ascii=False) + "\n")
                manifest.append({"batch": f"batch_{bidx:03d}", "arm": arm, "bench": bench,
                                 "n": len(chunk), "input": str(inp),
                                 "output": str(ROOT / "judge_output_scale" / f"batch_{bidx:03d}.jsonl")})

    with open(ROOT / "scale_judge_manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"Prepared {len(manifest)} batches ({sum(m['n'] for m in manifest)} items)")
    for arm in ARMS:
        for bench in BENCHES:
            ms = [m for m in manifest if m["arm"] == arm and m["bench"] == bench]
            if ms:
                print(f"  {arm}/{bench}: {sum(m['n'] for m in ms)} items in {len(ms)} batch(es)")


if __name__ == "__main__":
    main()
