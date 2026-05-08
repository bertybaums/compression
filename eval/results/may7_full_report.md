# Layer-4 stress + patched-cx: full Reasoner-vs-Comparator results

_Generated May 7, 2026._

This report combines Reasoner and Comparator scores on the two May-6/7
runs:

1. **Layer-4 stress bench** (30 hand-crafted UGF-hard prompts)
2. **Patched counterexample subset** (50 items, full definitions
   restored after the May-5 truncation diagnosis)

The headline finding is **not** what the May-6 partial report
predicted. The Reasoner exhibits a previously-invisible prompt-attention
deficit that the holdout benchmark masked.

## Headline numbers

### Layer-4 stress bench

| system     | n  | engagement | coherence | substance | expressive_adequacy |
|------------|----|-----------:|----------:|----------:|--------------------:|
| Reasoner   | 30 |   **0.13** |      2.10 |      1.03 |                2.07 |
| Comparator | 30 |       3.77 |      3.43 |      2.43 |                2.97 |
| Δ (R−C)    |    |     −3.63  |    −1.33  |    −1.40  |              −0.90  |

### Patched cx subset

| system     | n  | engagement | coherence | substance | expressive_adequacy |
|------------|----|-----------:|----------:|----------:|--------------------:|
| Reasoner   | 50 |   **0.02** |      2.30 |      1.38 |                2.24 |
| Comparator | 50 |       2.86 |      3.16 |      2.34 |                3.04 |
| Δ (R−C)    |    |     −2.84  |    −0.86  |    −0.96  |              −0.80  |

## The major finding: a prompt-attention deficit

**Reasoner engagement is essentially zero on both new sets.** Per-category
engagement on the stress bench:

- Every category 0.0 or 0.3 (out of 4)
- 100% across modal, deontic, supervenience, intensional_contexts,
  self_reference, vagueness_sorites, counterfactual_disposition,
  abstract_objects, phenomenal_qualia, use_mention.

Inspection of raw outputs reveals the failure mode: the Reasoner produces
**fluent, philosophy-shaped UGF essays that have no relation to the
prompt's actual question**.

Examples (from the stress bench Reasoner outputs):

| prompt | Reasoner response (start) |
|---|---|
| "Could the laws of physics have been different?" | "First, we look at what it means to follow the ways we are told to act. These ways are made by people who say what is right or wrong. They help keep order in a group..." |
| "What are 'possible worlds'?" | "First, we think about a situation that we want to know or act on. Second, we think about what may happen after we act..." |
| "counterexample to: A set of sentences is consistent iff..." | "The person is talking about how to tell if a way of thinking is good. The first idea they give is that we must look at the things they say are true..." |

These are not failed translations or truncations — they are fully
formed philosophical paragraphs about *something else*. Coherence (D2)
stays at ~2 because the prose is internally connected. Substance (D3)
is at ~1 because the prose isn't really about anything specific.
Expressive adequacy (D4) is at ~2 because the UGF is fine — it's just
not answering anything.

## Why the holdout report missed this

The Layer-3 (May-5) holdout numbers showed Reasoner engagement at 2.08,
roughly half the comparator's 3.61, with three CONTENT_TYPES where the
Reasoner *won* on substance:

- concept_explanation: D1 +0.32, D3 +0.76
- socratic_dialogue: D3 +0.33
- chain_of_thought: D3 +0.21

The interpretation we landed on (in `judge_report.md`) was: "the 200M
Reasoner is doing approximately what we want in distribution."

What the new runs reveal is that the holdout's "in-distribution" success
was concentrated on a **narrow window of prompt types**: short topic
phrases ("why X matters", "the way to think about Y") that match the
Reasoner's generic-philosophical-essay output template by accident. The
Reasoner appears to have learned **"produce a philosophical essay in
UGF"** without learning **"respond to the specific prompt"**.

Per-type engagement breakdown from Layer-3 (Reasoner side, derived
from `judge_aggregate.json`):

| holdout type | Reasoner engagement |
|---|---:|
| concept_explanation | 3.92 |
| socratic_dialogue | 3.47 |
| chain_of_thought | 3.07 |
| thought_experiment | 3.43 |
| argument_analysis | 3.11 |
| analogical_analysis | 2.04 |
| conditional_analysis | 1.54 |
| **counterexample_analysis** | **0.27** |

Counterexample_analysis was already near-zero engagement on
holdout. The other types where Reasoner engagement looked acceptable
share a feature: the prompt is a short topic phrase that matches the
Reasoner's output template even if the model is producing a generic
essay. The new stress bench breaks this match — the prompts are
interrogative, longer, or pose specific philosophical puzzles —
and the Reasoner has nowhere to hide.

## What patching the cx prompts actually did

The May-6 partial report observed that patching the truncation made
**comparator** scores worse, not better. The completed picture:

| | engagement | coherence | substance | expressive_adequacy |
|---|---:|---:|---:|---:|
| Reasoner: NEW − ORIGINAL | −0.06 | −0.98 | −0.04 | −0.54 |
| Comparator: NEW − ORIGINAL | −0.56 | −0.54 | −0.24 | −0.06 |

The Reasoner's coherence dropped substantially (3.28 → 2.30) — the
patched (real) prompts make the off-topic-ness more visible than the
truncated prompts did. The Reasoner's *engagement* didn't move because
it was already at the floor (0.08 → 0.02). The truncation hadn't been
hiding a Reasoner-can't-tell-what's-asked bug; it had been hiding a
Reasoner-doesn't-attend-to-the-prompt bug.

## What UGF expressive adequacy looks like, separated from the Reasoner

The Comparator-side numbers isolate the UGF question from the Reasoner
question. They show:

- **Stress D4 = 2.97** (vs holdout 3.55) — UGF has a real but
  modest expressive ceiling on these topics. Not a collapse.
- **Per-category D4 lows (2.67):** abstract_objects, modal,
  supervenience, self_reference. Type/token, modal contingency,
  asymmetric dependence, and recursive contradictions are the genuinely
  hard categories.
- **Per-category D4 highs:** use_mention (3.67), counterfactual
  (3.33). UGF handles these fine.
- **Substance (D3) is a more revealing dimension than D4 here.**
  Comparator D3 drops to 2.43 overall on stress, with deontic at 1.67
  — the obligation/supererogation distinction is real-but-shallow in
  UGF when the model commits to it.

These numbers are the project's actual answer to *"is UGF
expressively adequate for philosophical reasoning?"*: **modestly yes
with calibrated exceptions**, when produced by a competent reasoner.

## Reconsidering the project narrative

The May-5 reading — "Reasoner near-comparator on holdout, chatbot
pipeline is the bottleneck" — is no longer the most defensible
summary. The new reading:

1. **UGF is expressively adequate enough** for practical philosophical
   reasoning (Comparator D4 ≥ 3 across most categories; specific lows
   are defensible). This is the project's positive thesis and remains
   supported.
2. **The 200M from-scratch Reasoner has a prompt-attention deficit**
   that's invisible on holdout-distribution prompts but appears as
   ~zero engagement on prompts whose form differs from the corpus
   distribution. This is a model-capability finding, separable from the
   UGF question.
3. **The holdout success on concept_explanation, socratic_dialogue, and
   chain_of_thought is real but qualified.** The Reasoner produces
   structured UGF essays in those forms; that the essays match the
   prompt's intent on holdout is partly because the holdout prompts are
   short topic phrases the Reasoner's output template fits.

## Implications for next steps

**For the paper:**
- The expressive-adequacy thesis can stand, supported by Comparator
  numbers + the Reasoner's holdout successes on three content types.
- The Reasoner section needs to be honest about the prompt-attention
  deficit: report holdout numbers with the per-type breakdown, report
  stress + cx-patched as evidence of the failure mode, document the
  asymmetry.
- The Layer-4 stress bench is a useful contribution — the per-category
  Comparator D4 map is the cleanest UGF-only diagnostic we have.

**For modeling work (if continued):**
- Prompt-attention diagnosis: is this a training-distribution issue
  (corpus prompts too short/templated)? An RLHF-style fix? A
  decoding/sampling issue?
- Consider augmenting the corpus with longer, interrogative,
  diverse-form prompts to see if attention improves.
- Inter-rater calibration with Bert is now more important — these are
  surprising findings and the judge's calibration matters.

**For Translator workstream (separate):**
- Less urgent now. The chatbot pipeline isn't the dominant bottleneck;
  the Reasoner's prompt-attention is.

## Files

- `eval/results/_jsonl/stress_bench_reasoner_20260506_210418.jsonl` — Reasoner on stress
- `eval/results/_jsonl/holdout_cx_patched_reasoner_20260506_210418.jsonl` — Reasoner on patched cx
- `eval/results/_jsonl/stress_bench_comparator_20260506_203612.jsonl` — Comparator on stress
- `eval/results/_jsonl/comparator_cx_patched_20260506_203745.jsonl` — Comparator on patched cx
- `eval/judge_output/{reasoner,comparator}_{stress,cx_patched}_batch_*.jsonl` — judge scores
- `eval/analyze_new_runs.py` — reproducible aggregator
