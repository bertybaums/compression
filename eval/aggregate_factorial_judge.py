"""
Aggregate blinded judge scores for the form x prompt-diversity factorial and apply
the NARROWED decision rule (docs/form-retrain-clean-design-2026-06-03.md, THIRD
AMENDMENT).

Arms:
  ugf_n     ARM A -- essay responses, 380 unique prompts
  form_n    ARM B -- prompt-attentive responses, the SAME 380 unique prompts
  formdiv_n ARM C -- prompt-attentive responses, ~400K distinct specific prompts

Contrasts:
  A -> B    response form,    at fixed prompt diversity
  B -> C    prompt diversity, at fixed response form

THE NARROWED RULE, and why it matters. The original design pre-registered that
form ~ essay would mean "the deficit is a deep property of short-prompt->long-essay
distillation at this scale". The July 16 corpus audit voids that reading: arms A and
B BOTH carry only 380 unique prompts across ~400K examples (~1,053 distinct
responses per prompt), so p(response|prompt) is ~unconditional within a topic bucket
and prompt-attention earns nothing in training loss in EITHER arm. A null on A vs B
therefore licenses only:

    "response form, at fixed prompt diversity, is not the fix"

and NOT any claim about distillation as such. Reading it the original way would
close the project's last lever on a confound. B vs C is the contrast that tests the
variable the audit promotes to first place.

Usage:
  python3 eval/aggregate_factorial_judge.py
"""
import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent
DIMS = ["engagement", "coherence", "substance"]
MANIFEST = ROOT / "factorial_judge_manifest.json"


def main() -> int:
    manifest = json.loads(MANIFEST.read_text())
    scores = defaultdict(lambda: defaultdict(list))   # (arm,bench) -> dim -> [scores]
    missing = []

    for m in manifest:
        out = Path(m["output"])
        if not out.exists():
            missing.append(m["batch"])
            continue
        for line in out.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            for dim in DIMS:
                v = d.get(dim)
                if isinstance(v, dict) and v.get("score") is not None:
                    scores[(m["arm"], m["bench"])][dim].append(float(v["score"]))

    if missing:
        print(f"WARNING: {len(missing)} batch(es) not yet judged: {', '.join(missing)}\n")

    benches = sorted({m["bench"] for m in manifest})
    arms = [a for a in ["ugf_n", "form_n", "formdiv_n"] if any(m["arm"] == a for m in manifest)]
    label = {"ugf_n": "A essay/380", "form_n": "B form/380", "formdiv_n": "C form/diverse"}

    means = {}
    for bench in benches:
        print(f"=== bench: {bench} ===")
        print(f"{'arm':16} {'n':>4}  " + "  ".join(f"{d:>11}" for d in DIMS))
        for arm in arms:
            got = scores.get((arm, bench))
            if not got:
                continue
            n = max(len(got[d]) for d in DIMS)
            row = []
            for d in DIMS:
                mu = statistics.fmean(got[d]) if got[d] else float("nan")
                means[(arm, bench, d)] = mu
                row.append(f"{mu:>11.2f}")
            print(f"{label.get(arm, arm):16} {n:>4}  " + "  ".join(row))
        print()

    # Contrasts
    for lo, hi, what in [("ugf_n", "form_n", "A->B  response form (fixed prompt diversity)"),
                         ("form_n", "formdiv_n", "B->C  prompt diversity (fixed form)")]:
        if not any(m["arm"] == hi for m in manifest):
            continue
        print(f"=== {what} ===")
        for bench in benches:
            parts = []
            for d in DIMS:
                a, b = means.get((lo, bench, d)), means.get((hi, bench, d))
                if a is None or b is None:
                    continue
                parts.append(f"{d} {b - a:+.2f}")
            if parts:
                print(f"  {bench:12} " + "  ".join(parts))
        print()

    # Verdict on the primary metric.
    a = means.get(("ugf_n", "stress", "engagement"))
    b = means.get(("form_n", "stress", "engagement"))
    if a is not None and b is not None:
        d = b - a
        print(f"=== VERDICT: A->B stress engagement delta = {d:+.2f} ===")
        if abs(d) <= 0.3:
            print("  NULL. Reads ONLY as: response form, at fixed prompt diversity (380")
            print("  unique prompts, ~1,053 responses each), is not the fix.")
            print("  This does NOT license 'a deep property of essay distillation' --")
            print("  neither arm's corpus rewarded prompt-attention, so neither arm could")
            print("  have learned it. See the THIRD AMENDMENT. ARM C tests the live variable.")
        elif d >= 1.0:
            print("  FORM HELPS even at fixed prompt diversity. Response form installs")
            print("  input-recognition the essay corpus never taught. Then ARM C asks")
            print("  whether prompt diversity adds to it or subsumes it.")
        else:
            print("  PARTIAL. Form contributes at fixed prompt diversity; quantify its share")
            print("  against ARM C.")
        print("\n  Read with the noise in mind: 30 items, one judge per arm.")

    c = means.get(("formdiv_n", "stress", "engagement"))
    if b is not None and c is not None:
        d = c - b
        print(f"\n=== VERDICT: B->C stress engagement delta = {d:+.2f} ===")
        if d >= 1.0:
            print("  PROMPT DIVERSITY IS THE FIX. The deficit was a corpus property all")
            print("  along: capacity, vocabulary, DPO and RL were all varied while prompt")
            print("  diversity stayed pinned at 380, which is why they all came out flat.")
        elif abs(d) <= 0.3:
            print("  Prompt diversity is NOT the fix either. With form, capacity,")
            print("  vocabulary, post-training AND prompt diversity all ruled out, the")
            print("  deficit is a deeper property of this regime -- and NOW that")
            print("  conclusion is earned rather than confounded.")
        else:
            print("  PARTIAL. Prompt diversity contributes; quantify its share.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
