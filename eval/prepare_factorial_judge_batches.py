"""
Prepare blinded judge batches for the form x prompt-diversity factorial
(docs/form-retrain-clean-design-2026-06-03.md, THIRD AMENDMENT).

Mirrors prepare_enbase_judge_batches.py, with one deliberate change: arms are
passed explicitly as arm=path pairs rather than assembled from a fixed prefix.
That is what lets ARM A be RE-JUDGED from its existing June 2 generation files
alongside the new arms.

Why re-judge ARM A rather than reuse its June 2 scores: the judge is a Claude
subagent, and ARM A was scored in June by a different judge instance than the one
that will score ARM B/C today. Reusing those numbers would confound the arm
contrast with judge drift -- on a 30-item bench read to ~0.3 resolution, that is
not a safe assumption. Re-judging both arms in the same pass, blinded, costs 30
extra items and removes the confound. ARM A's generations are NOT regenerated;
only re-scored.

Two design points preserved from the enbase/precursor work:
  - ISOLATION: every batch holds exactly one arm + one bench. The precursor showed
    cross-register contrast depresses the restricted arm by ~1 substance point on
    IDENTICAL text, so arms must never share a batch.
  - BLINDING: opaque batch filenames, and only {id, prompt, response} in the file
    (no arm label anywhere), so the judge cannot tell which arm it is scoring.

Batches are emitted in a shuffled order so that batch number does not leak arm
identity either (arm A's batches are not simply all the low numbers).

Usage:
  python3 eval/prepare_factorial_judge_batches.py \
      --arm ugf_n=eval/results/enbase_ugf_n_stress_20260602_081559.jsonl \
      --arm form_n=eval/results/factorial_form_n_stress_20260716_070441.jsonl \
      --bench stress
"""
import argparse
import json
import random
from pathlib import Path

ROOT = Path(__file__).parent


def load(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            resp = d.get("ugf_response") or d.get("response") or d.get("generation")
            prompt = d.get("prompt") or d.get("english_query")
            if resp is None or prompt is None:
                continue
            rows.append({"id": d["id"], "prompt": prompt, "response": resp})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", action="append", required=True,
                    help="arm=path/to/generations.jsonl (repeatable)")
    ap.add_argument("--bench", required=True)
    ap.add_argument("--batch-size", type=int, default=30)
    ap.add_argument("--out-dir", default=str(ROOT / "judge_input_factorial"))
    ap.add_argument("--manifest", default=str(ROOT / "factorial_judge_manifest.json"))
    ap.add_argument("--seed", type=int, default=20260716)
    args = ap.parse_args()

    outd = Path(args.out_dir)
    outd.mkdir(exist_ok=True)
    (ROOT / "judge_output_factorial").mkdir(exist_ok=True)

    pending = []
    for spec in args.arm:
        if "=" not in spec:
            raise SystemExit(f"--arm must be arm=path, got {spec!r}")
        arm, path = spec.split("=", 1)
        rows = load(path)
        if not rows:
            raise SystemExit(f"{path}: no usable rows")
        for i in range(0, len(rows), args.batch_size):
            pending.append({"arm": arm, "bench": args.bench, "src": path,
                            "rows": rows[i:i + args.batch_size]})
        print(f"{arm:12} {len(rows):>4} items  <- {path}")

    # Shuffle so batch NUMBER does not leak arm identity to the judge.
    random.Random(args.seed).shuffle(pending)

    manifest = []
    for idx, b in enumerate(pending, start=1):
        name = f"batch_{idx:03d}"
        fp = outd / f"{name}.jsonl"
        with open(fp, "w", encoding="utf-8") as f:
            for r in b["rows"]:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        manifest.append({
            "batch": name, "arm": b["arm"], "bench": b["bench"], "n": len(b["rows"]),
            "src": b["src"],
            "input": str(fp),
            "output": str(ROOT / "judge_output_factorial" / f"{name}.jsonl"),
        })

    Path(args.manifest).write_text(json.dumps(manifest, indent=2))
    print(f"\nwrote {len(manifest)} blinded batches -> {outd}")
    print(f"manifest (arm mapping, judge must NOT see this) -> {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
