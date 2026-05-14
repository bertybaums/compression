"""
Prepare two kinds of judge batches for the target-probe experiment:

  INDEPENDENT (mode A): blinded, each item scored individually with the
    Reasoner rubric (engagement / coherence / substance / expressive_adequacy).
    Mixes all three conditions (reasoner / p4 / p5) into shuffled batches so
    the judge can't pattern-match on within-batch homogeneity.

  PAIRWISE (mode B): P4-vs-P5 only. Each item shows the judge two responses to
    the same prompt in shuffled A/B order; judge scores both and picks a winner.
    The A/B → system-label truth is written to a separate file the judge does
    not read, used at aggregation time.

Inputs: the three per-condition JSONL files from run_target_probe.py.
Output:
  eval/judge_input_target_probe/independent_batch_NN.jsonl
  eval/judge_input_target_probe/pairwise_batch_NN.jsonl
  eval/judge_manifest_target_probe.json
  eval/judge_input_target_probe/pairwise_truth.json
"""

import argparse
import json
import random
from pathlib import Path

ROOT = Path("/Users/bbaum/Documents/_RCDS/compression/eval")
OUT = ROOT / "judge_input_target_probe"
JUDGE_OUT = ROOT / "judge_output_target_probe"
INDEPENDENT_BATCH_SIZE = 40
PAIRWISE_BATCH_SIZE = 25


def load_jsonl(path: Path) -> list[dict]:
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reasoner", required=True,
                        help="Path to cot_target_probe_reasoner_<ts>.jsonl")
    parser.add_argument("--p4", required=True,
                        help="Path to cot_target_probe_p4_<ts>.jsonl")
    parser.add_argument("--p5", required=True,
                        help="Path to cot_target_probe_p5_<ts>.jsonl")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    reasoner = {r["id"]: r for r in load_jsonl(Path(args.reasoner))}
    p4 = {r["id"]: r for r in load_jsonl(Path(args.p4))}
    p5 = {r["id"]: r for r in load_jsonl(Path(args.p5))}

    common = sorted(set(reasoner) & set(p4) & set(p5))
    print(f"Common prompt ids across all 3 conditions: {len(common)}")
    print(f"  reasoner: {len(reasoner)}, p4: {len(p4)}, p5: {len(p5)}")

    OUT.mkdir(parents=True, exist_ok=True)
    JUDGE_OUT.mkdir(parents=True, exist_ok=True)

    rng = random.Random(args.seed)
    manifest: list[dict] = []

    # ---- Mode A: independent blinded (3 conditions × N prompts, shuffled) ----
    print("\n=== Mode A: independent blinded ===")
    all_items: list[dict] = []
    for cond, store in [("reasoner", reasoner), ("p4", p4), ("p5", p5)]:
        for pid in common:
            r = store[pid]
            ugf = r.get("ugf_response", "") or ""
            if not ugf or ugf.startswith("<"):
                continue
            all_items.append({
                "id": f"{pid}::{cond}",
                "_prompt_id": pid,
                "_condition": cond,  # NOT written to judge files
                "english_query": r["english_query"],
                "ugf_response": ugf,
            })
    rng.shuffle(all_items)
    print(f"  {len(all_items)} items across all 3 conditions")

    independent_truth: dict[str, str] = {}  # item_id -> condition
    n_batches = (len(all_items) + INDEPENDENT_BATCH_SIZE - 1) // INDEPENDENT_BATCH_SIZE
    for b in range(n_batches):
        chunk = all_items[b * INDEPENDENT_BATCH_SIZE : (b + 1) * INDEPENDENT_BATCH_SIZE]
        bp = OUT / f"independent_batch_{b+1:02d}.jsonl"
        with open(bp, "w", encoding="utf-8") as f:
            for it in chunk:
                independent_truth[it["id"]] = it["_condition"]
                f.write(json.dumps({
                    "id": it["id"],
                    "english_query": it["english_query"],
                    "ugf_response": it["ugf_response"],
                }, ensure_ascii=False) + "\n")
        manifest.append({
            "mode": "independent",
            "batch": b + 1,
            "n_items": len(chunk),
            "input_path": str(bp),
            "output_path": str(JUDGE_OUT / f"independent_batch_{b+1:02d}.jsonl"),
        })
    truth_indep = OUT / "independent_truth.json"
    with open(truth_indep, "w", encoding="utf-8") as f:
        json.dump(independent_truth, f, indent=2)
    print(f"  wrote {n_batches} batches; truth at {truth_indep}")

    # ---- Mode B: pairwise P4-vs-P5 ----
    print("\n=== Mode B: pairwise P4-vs-P5 ===")
    pairs: list[dict] = []
    pairwise_truth: dict[str, dict] = {}
    for pid in common:
        a_ugf = p4[pid].get("ugf_response", "") or ""
        b_ugf = p5[pid].get("ugf_response", "") or ""
        if not a_ugf or a_ugf.startswith("<") or not b_ugf or b_ugf.startswith("<"):
            continue
        # Coin flip — which gets the A vs B slot
        if rng.random() < 0.5:
            slot_A, slot_B = "p4", "p5"
            text_A, text_B = a_ugf, b_ugf
        else:
            slot_A, slot_B = "p5", "p4"
            text_A, text_B = b_ugf, a_ugf
        pairs.append({
            "id": pid,
            "english_query": p4[pid]["english_query"],
            "response_A": text_A,
            "response_B": text_B,
        })
        pairwise_truth[pid] = {"A": slot_A, "B": slot_B}
    rng.shuffle(pairs)

    n_pair_batches = (len(pairs) + PAIRWISE_BATCH_SIZE - 1) // PAIRWISE_BATCH_SIZE
    for b in range(n_pair_batches):
        chunk = pairs[b * PAIRWISE_BATCH_SIZE : (b + 1) * PAIRWISE_BATCH_SIZE]
        bp = OUT / f"pairwise_batch_{b+1:02d}.jsonl"
        with open(bp, "w", encoding="utf-8") as f:
            for it in chunk:
                f.write(json.dumps(it, ensure_ascii=False) + "\n")
        manifest.append({
            "mode": "pairwise",
            "batch": b + 1,
            "n_items": len(chunk),
            "input_path": str(bp),
            "output_path": str(JUDGE_OUT / f"pairwise_batch_{b+1:02d}.jsonl"),
        })
    truth_pair = OUT / "pairwise_truth.json"
    with open(truth_pair, "w", encoding="utf-8") as f:
        json.dump(pairwise_truth, f, indent=2)
    print(f"  wrote {n_pair_batches} batches; truth at {truth_pair}")

    manifest_path = ROOT / "judge_manifest_target_probe.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"\nManifest: {manifest_path}")
    print(f"Total batches: {len(manifest)}")


if __name__ == "__main__":
    main()
