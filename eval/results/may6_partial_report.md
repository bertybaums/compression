# May 6, 2026 — partial Layer-3/4 update (comparator only)

_Generated May 6, 2026._

This report covers the comparator-only side of two May-6 runs:

1. **Layer-4 stress bench** (30 items, 10 UGF-hard categories × 3)
2. **Patched counterexample subset** (50 items, full definitions restored
   from cx-bot after the May-5 truncation diagnosis)

The Reasoner side of both runs requires SLURM on fortyfive and is
pending. These numbers are the **comparator (gpt-oss-120b in UGF)
ceiling** — what the rubric would score if a 120B teacher with full
English understanding produced UGF responses.

## 1. Layer-4 stress bench (comparator on 30 items)

### Per-category means (0–4 scale)

| category                     | n | engagement | coherence | substance | expressive_adequacy |
|------------------------------|---|-----------:|----------:|----------:|--------------------:|
| use_mention                  | 3 |       4.00 |      4.00 |      2.67 |          **3.67**   |
| counterfactual_disposition   | 3 |       3.67 |      4.00 |      3.00 |          **3.33**   |
| phenomenal_qualia            | 3 |       4.00 |      4.00 |      3.33 |              3.00   |
| deontic                      | 3 |       3.67 |      3.00 |      1.67 |              3.00   |
| intensional_contexts         | 3 |       3.67 |      3.00 |      2.00 |              3.00   |
| vagueness_sorites            | 3 |       3.67 |      3.33 |      2.33 |              3.00   |
| modal                        | 3 |       3.67 |      3.33 |      2.33 |              2.67   |
| supervenience                | 3 |       4.00 |      3.67 |      2.67 |              2.67   |
| self_reference               | 3 |       3.67 |      3.00 |      2.33 |              2.67   |
| abstract_objects             | 3 |       3.67 |      3.00 |      2.00 |              2.67   |
| **OVERALL**                  | 30 |     3.77 |      3.43 |      2.43 |          **2.97**   |

### What this tells us about UGF expressive adequacy

**D4 dropped from 3.55 (holdout) to 2.97 (stress).** This is the first
clear evidence of a real UGF expressive ceiling. The drop is meaningful
(0.58 / 16% relative) — the stress bench was designed to find this and it
did.

**Predictions vs reality (D4):**
- Predicted lowest: `intensional_contexts`, `modal`, `phenomenal_qualia`, `use_mention`.
- Actual lowest: `abstract_objects` (2.67), `modal` (2.67), `supervenience` (2.67), `self_reference` (2.67).
- Modal: predicted ✓
- Use_mention: **predicted poorly** (actual best: 3.67). UGF handles "the word X" / "X" distinctions cleanly with available common words.
- Phenomenal_qualia: predicted poorly (actual mid: 3.00). "What it feels like" paraphrases work better than expected.
- Surprises: `abstract_objects` and `supervenience` were both lower than expected. Universals/types-vs-tokens and "rests on" / asymmetric-dependence are harder to carry than I predicted.

**Substance (D3) is more revealing than D4 here.** Comparator engagement
and coherence stay high (3.7+), but substance drops to 2.43. The model
*talks about* these topics fluently in UGF but doesn't develop them
deeply. `deontic` is particularly low at 1.67 — the
permissions/obligations/supererogation distinction structure stays at
the gestural level. This is consistent with the UGF restriction
preventing the discursive moves that generate philosophical depth on
these topics.

**Key observation:** Engagement (D1) is uniformly high across all
categories. The comparator is *willing* to attempt every prompt. The
adequacy + substance gaps tell us where the vocabulary actually limits
what can be said.

## 2. Patched counterexample subset (comparator on 50 items)

### Patched (NEW, full definitions) vs Original (Layer-3 truncated)

| | engagement | coherence | substance | expressive_adequacy |
|---|---:|---:|---:|---:|
| Original cx (truncated, n=50) |   3.42 | 3.70 | 2.58 | 3.10 |
| Patched cx (full defs, n=50)  |   2.86 | 3.16 | 2.34 | 3.04 |
| Δ (NEW − ORIGINAL)            | **−0.56** | **−0.54** | −0.24 | −0.06 |

### What this tells us — and the surprise

**Counterintuitive finding: the patch made comparator scores WORSE, not
better.** I had expected the full definitions to help. Instead:
engagement and coherence both dropped by ~0.55.

**Diagnosis.** The truncated prompts let the comparator produce a
**generic "evaluate the rule" template response** that scored well
on D1/D2 because it was structurally coherent — even though it
wasn't really engaging with the missing technical content.
Sample original (truncated): *"...a talk that tries to show the big
power is real can be strong only when it does a certain set of
things. They say this point is true and that without those things
the talk cannot be strong..."* — abstract, pattern-following,
high D1/D2 by design.

The full definitions have specific formal-logic / mathematical /
modal-logic content (e.g., "consistent if and only if there exists a
model that satisfies all members of the set, no sentence in the set is
the negation of another, and the set is finite"). Engaging this *as
posed* in UGF is much harder, and the comparator's scores reflect that.

**Implication for Layer-3 numbers.** The original Layer-3 cx-subset
numbers were **inflated for both systems** by the truncation — the
comparator could fake a generic answer; the Reasoner couldn't tell
what was being asked. Patched numbers are the truer ceiling.

**Implication for the headline finding.** When we have the patched
Reasoner numbers, the right comparison is patched-vs-patched. The
holdout `counterexample_analysis` slice was the largest negative type
in the May-5 report (n=50, engagement -3.34); the patched version is
likely to show:
- Comparator dropping from 3.42 to 2.86 ✓ (already observed)
- Reasoner *possibly* improving (now seeing real prompts) — TBD pending
  fortyfive run

Either outcome is informative.

## 3. What's still needed

- **Reasoner side** of both stress bench (30 items) and patched cx (50
  items). Both require fortyfive. Recipe in
  `eval/RERUN_PATCHED_COUNTEREXAMPLES.md` and the analogous
  `--bench eval/sets/stress_bench.jsonl --skip-translate-en2ugf` for
  the stress side.
- **Reasoner-side judge** — same parallel-subagent pattern as before.
- **Final aggregate** — reasoner-vs-comparator deltas on both new sets,
  per-dimension and (for stress) per-category.

## Files

- `eval/results/_jsonl/stress_bench_comparator_20260506_203612.jsonl` — comparator on stress (30 items)
- `eval/results/_jsonl/comparator_cx_patched_20260506_203745.jsonl` — comparator on patched cx (50 items)
- `eval/judge_output/comparator_stress_batch_01.jsonl` — judge scores (30)
- `eval/judge_output/comparator_cx_patched_batch_{01,02}.jsonl` — judge scores (50 total)
- `eval/analyze_new_runs.py` — reproducible aggregator for these runs
