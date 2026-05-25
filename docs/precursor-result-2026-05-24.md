---
title: "English-baseline precursor — teacher-scale vocabulary tax (result)"
date: May 24, 2026
audience: project
status: result — feeds the 200M English-baseline decision (docs/english-baseline-design-2026-05-24.md)
---

# Precursor result: the vocabulary tax at teacher (120B) scale

## TL;DR

At teacher scale, gold-standard English (P3) scores meaningfully higher than the **same** 120B teacher constrained to UGF (the cached comparator, = P5) on engagement / coherence / substance, on both the target-probe and the stress prompts. The gap is largest and most consistent on **substance**. **But the magnitude is inflated by a cross-register contrast artifact** — proven directly below: identical UGF text scored ~1 point lower on substance when judged alongside English than it did in isolation in May. Net read: the vocabulary tax is **non-zero and substance-concentrated**, which (a) **validates running the 200M student experiment** (vocabulary is not obviously free, so isolating it at student scale carries real information), and (b) **refines its design** (judge arms in isolation; track substance as a co-primary). Crucially, the teacher's tax is a **substance** effect, not the **engagement collapse** the student shows — consistent with the paper's attribution of the student's prompt-attention deficit to form/capacity, not vocabulary.

## Numbers (blinded, Sonnet judges, 4-dim rubric, content-not-register instruction)

**Target-probe (n=32 each), gold-English P3 vs teacher-in-UGF:**

| condition | engage | cohere | subst | expr_ad |
|---|--:|--:|--:|--:|
| P3 gold-English | 3.91 | 3.94 | 3.00 | — (N/A) |
| teacher-in-UGF | 3.03 | 3.06 | 1.75 | 2.34 |
| **tax (P3 − UGF)** | **+0.88** | **+0.88** | **+1.25** | |

**Stress (n=30 each):**

| condition | engage | cohere | subst | expr_ad |
|---|--:|--:|--:|--:|
| P3 gold-English | 3.83 | 3.97 | 3.60 | — (N/A) |
| teacher-in-UGF | 3.20 | 3.57 | 1.87 | 2.93 |
| **tax (P3 − UGF)** | **+0.63** | **+0.40** | **+1.73** | |

Directionally identical across both benches and all four judge instances: English > UGF on engagement/coherence/substance; substance is the biggest, most consistent gap.

## The confound — read this before citing the magnitudes

The teacher-in-UGF **text is identical** to the May-14 target-probe P5 outputs (same cached file). Only the judging context changed (now mixed in blinded batches with gold-English P3, with a content-focused instruction). The scores moved a lot:

| teacher-in-UGF (same 32 texts) | engage | cohere | subst | expr_ad |
|---|--:|--:|--:|--:|
| May-14, judged in isolation (vs P4/Reasoner, all UGF) | 3.78 | 3.72 | 2.84 | 3.38 |
| precursor, judged alongside English P3 | 3.03 | 3.06 | 1.75 | 2.34 |
| **drop (pure judging-context effect)** | **−0.75** | **−0.66** | **−1.09** | **−1.04** |

So a large part of the measured "tax" is a **cross-register contrast effect**: putting a rich English answer next to a UGF answer to the same question drags the UGF score down, even under a "score content, not register" instruction. The true within-register vocabulary tax is therefore **smaller** than the +0.9/+1.25/+1.73 numbers above — those are an **upper bound**.

## Robust conclusions (survive the confound)

1. **The teacher-scale vocabulary tax is non-zero and directional** — every bench, every judge, English > UGF on the content dimensions.
2. **It is concentrated in substance**, not engagement. Even discounting contrast, the judges' notes identify specific prompts where UGF genuinely could not reach the move because the concept has no clean circumlocution: Frege sense/reference, universals, ersatzism/possible-worlds, ethical non-naturalism. That is a real vocabulary limitation, not only contrast.
3. **The teacher still engages the question in UGF** (engagement 3.0–3.2) — it answers what was asked; it just does **less philosophical work** under the constraint. Expressive adequacy stays ~2.3–2.9 ("restriction shows but recoverable"), so the content is still *expressible*; it is not *free*.
4. **The teacher's tax ≠ the student's deficit.** The teacher pays a SUBSTANCE tax with intact engagement; the v1 student's failure is an ENGAGEMENT collapse (stress 0.13 — off-topic essays). Different failure modes. This **supports** the paper's reading that the student's prompt-attention deficit is form/capacity, not vocabulary — while flagging that the paper under-acknowledges a genuine substance cost of UGF.

## Implications for the 200M English-baseline experiment

- **Proceed.** The de-risk question was "does the teacher pay a vocabulary tax?" Answer: yes, a substance-weighted one. So vocabulary is not obviously free, and isolating it at student scale (UGF-200M vs English-200M) has genuine information value — the student outcome is not a foregone conclusion.
- **Design refinement 1 — isolation judging.** Do NOT judge UGF-200M and English-200M in mixed cross-register batches; that contaminates with the contrast effect demonstrated above. Judge each arm's outputs in isolation (same-register context), aggregate separately, then compare. Update the design doc's eval section accordingly.
- **Design refinement 2 — substance is a co-primary metric.** The teacher tax lives in substance, so the student experiment should track substance alongside the stress-engagement headline. Prediction: if English-200M also collapses on stress *engagement*, vocabulary is exonerated for the deficit; independently, English-200M will likely beat UGF-200M on *substance*, replicating the teacher-scale tax at student scale.

## Artifacts

- Generators/prep: `eval/run_p3_gold_english.py`, `eval/prepare_precursor_judge_batches.py`, `eval/aggregate_precursor.py`
- Gold-English (P3): target-probe `en_intermediate` in `eval/results/_jsonl/cot_target_probe_p4_20260514_095547.jsonl`; stress `eval/results/_jsonl/p3_gold_english_stress_20260524_201808.jsonl`
- Teacher-in-UGF (cached): target-probe `cot_target_probe_p5_20260514_095547.jsonl`; stress `stress_bench_comparator_20260506_203612.jsonl`
- Blinded batches + truth: `eval/judge_input_precursor_{targetprobe,stress}/`; scores `eval/judge_output_precursor_{targetprobe,stress}/`
- Aggregates: `eval/results/precursor_{targetprobe,stress}_aggregate.json`
