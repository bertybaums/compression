"""
Blind + batch the English-baseline precursor judging (P3 gold-English vs
teacher-in-UGF), per comparison.

The precursor measures the *teacher-scale* vocabulary tax: for the same prompts,
how far does teacher-in-UGF (restricted ~1000-word output) fall below gold-English
(P3, unrestricted output)? Each response is scored independently on the 4-dim
Reasoner rubric (eval/rubric.md). The per-dimension delta (P3 - teacher_in_ugf)
on engagement / coherence / substance is the tax. D4 (expressive adequacy under
UGF) is N/A for the English (P3) arm.

CROSS-REGISTER CAVEAT (baked into JUDGE_INSTRUCTIONS.md): P3 is English, the
comparator is UGF, so the two conditions are visually distinguishable by register
— unlike the within-UGF P4-vs-P5 target probe, this comparison cannot be
register-blinded. Mitigated by (a) independent scoring with opaque ids, (b)
instructing the judge to score reasoning CONTENT, not prose register/fluency.
Directional teacher-scale read; the publication-grade measurement is the 200M
student experiment.

Usage:
  python -m eval.prepare_precursor_judge_batches --comparison targetprobe \
      --a-file eval/results/_jsonl/cot_target_probe_p4_20260514_095547.jsonl \
      --a-label p3_gold_english --a-field en_intermediate \
      --b-file eval/results/_jsonl/cot_target_probe_p5_20260514_095547.jsonl \
      --b-label teacher_in_ugf --b-field ugf_response
"""
import argparse
import json
import random
from pathlib import Path

ROOT = Path("/Users/bbaum/Documents/_RCDS/compression/eval")
BATCH = 32

JUDGE_INSTRUCTIONS = """# Precursor judging — gold-English (P3) vs teacher-in-UGF

You are scoring single responses to philosophical/reasoning prompts on a
four-dimensional, anchored 0-4 rubric. Score each item independently.

## IMPORTANT — score content, not register
Some responses are written in unrestricted English. Others are written in a
restricted vocabulary of ~1000 common English words ("Up Goer Five"), so they
use circumlocutions ("the rules the world goes by" for "laws of physics").
Score the **reasoning content** — engagement, coherence, substance — on the
merits. Do NOT reward a response for sounding fluent/natural, and do NOT
penalize a response for using restricted vocabulary. A simply-worded response
that nails the question should outscore an eloquent one that drifts.

## Dimensions (0 / 2 / 4 anchored; interpolate 1 and 3)
- **engagement**: Does the response address the prompt's ACTUAL question?
  0 = wanders/restates/tangential; 2 = touches but misses the central ask;
  4 = engages the central question on its own terms.
- **coherence**: Internal logical consistency; each step follows from the prior.
  0 = self-contradictory/disconnected; 2 = mostly readable, sloppy steps/gaps;
  4 = connected chain, no contradictions.
- **substance**: Real philosophical work vs paraphrase (a counterexample, a
  traced analogy, a non-obvious distinction, what's at stake).
  0 = restatement/truisms; 2 = identifies a move but doesn't push it;
  4 = develops/advances the question.
- **expressive_adequacy**: Does the content come through cleanly, or does a
  vocabulary restriction visibly degrade it? **If the response is in
  unrestricted English, this dimension is N/A — report score -1.** For
  restricted-vocabulary responses: 0 = restriction breaks the argument;
  2 = restriction shows but point recoverable; 4 = reads as clean as English.

## Output — one JSON object per input id, as a JSONL list
For each item, output exactly:
{"id": "<the id>", "engagement": {"score": N, "justification": "..."},
 "coherence": {"score": N, "justification": "..."},
 "substance": {"score": N, "justification": "..."},
 "expressive_adequacy": {"score": N, "justification": "..."}}
Use score -1 for expressive_adequacy ONLY when the response is unrestricted English.
"""


def load(path):
    return {r["id"]: r for r in (json.loads(l) for l in open(path) if l.strip())}


def usable(text):
    return bool(text) and not text.strip().startswith("<")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--comparison", required=True, help="short name, e.g. targetprobe / stress")
    p.add_argument("--a-file", required=True)
    p.add_argument("--a-label", required=True)
    p.add_argument("--a-field", required=True)
    p.add_argument("--b-file", required=True)
    p.add_argument("--b-label", required=True)
    p.add_argument("--b-field", required=True)
    p.add_argument("--prompt-field", default="english_query")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    a = load(args.a_file)
    b = load(args.b_file)
    common = sorted(set(a) & set(b))
    print(f"[{args.comparison}] common ids: {len(common)} (a={len(a)}, b={len(b)})")

    out_dir = ROOT / f"judge_input_precursor_{args.comparison}"
    judge_out = ROOT / f"judge_output_precursor_{args.comparison}"
    out_dir.mkdir(parents=True, exist_ok=True)
    judge_out.mkdir(parents=True, exist_ok=True)

    items = []
    for label, store, field in [(args.a_label, a, args.a_field),
                                (args.b_label, b, args.b_field)]:
        for pid in common:
            rec = store[pid]
            text = (rec.get(field) or "")
            prompt = rec.get(args.prompt_field) or rec.get("question") or ""
            if not usable(text):
                continue
            items.append({"_pid": pid, "_cond": label, "prompt": prompt, "response": text})

    rng = random.Random(args.seed)
    rng.shuffle(items)
    for i, it in enumerate(items):
        it["id"] = f"prec-{args.comparison}-{i:04d}"

    truth = {}
    n_batches = (len(items) + BATCH - 1) // BATCH
    for bi in range(n_batches):
        chunk = items[bi * BATCH:(bi + 1) * BATCH]
        bp = out_dir / f"batch_{bi + 1:02d}.jsonl"
        with open(bp, "w", encoding="utf-8") as f:
            for it in chunk:
                truth[it["id"]] = {"condition": it["_cond"], "prompt_id": it["_pid"]}
                f.write(json.dumps({"id": it["id"], "prompt": it["prompt"],
                                    "response": it["response"]}, ensure_ascii=False) + "\n")
    with open(out_dir / "truth.json", "w", encoding="utf-8") as f:
        json.dump(truth, f, indent=2)
    with open(out_dir / "JUDGE_INSTRUCTIONS.md", "w", encoding="utf-8") as f:
        f.write(JUDGE_INSTRUCTIONS)

    n_a = sum(1 for v in truth.values() if v["condition"] == args.a_label)
    n_b = sum(1 for v in truth.values() if v["condition"] == args.b_label)
    print(f"  wrote {n_batches} batches ({len(items)} items: "
          f"{args.a_label}={n_a}, {args.b_label}={n_b}) -> {out_dir}")
    print(f"  truth -> {out_dir / 'truth.json'}")
    print(f"  judge outputs go to -> {judge_out}")


if __name__ == "__main__":
    main()
