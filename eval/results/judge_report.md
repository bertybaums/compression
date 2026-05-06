# Layer-3 LLM-judge results: Reasoner vs. Comparator on UGF

_Generated May 5, 2026._

This report presents per-dimension judge scores comparing the 200M
SFT Reasoner against the gpt-oss-120b teacher-in-UGF comparator,
on both Layer-2 benchmarks. Scoring follows the four-dimensional
0–4 rubric in [`eval/rubric.md`](../rubric.md).

The judge was 16 parallel Claude subagents (Opus 4.7, with one batch on
Sonnet 4.6 after a content-filter retry). The judge scored UGF responses
**directly** — not the post-Translator English — so these scores are not
contaminated by Translator(UGF→En) degeneracy (see
`memory/translator_degeneracy_insight.md`).

## Headline numbers

Per-system per-dimension means (0–4 scale):

| system                | n   | engagement | coherence | substance | expressive_adequacy |
|-----------------------|-----|-----------:|----------:|----------:|--------------------:|
| Reasoner — textbook   | 115 |       0.28 |      1.79 |      1.10 |                1.75 |
| Comparator — textbook | 115 |       3.63 |      3.83 |      2.98 |                3.68 |
| Reasoner — holdout    | 170 |       2.08 |      3.34 |      2.26 |                3.17 |
| Comparator — holdout  | 170 |       3.61 |      3.77 |      2.67 |                3.55 |

Reasoner − Comparator (positive favors Reasoner):

| benchmark | engagement | coherence | substance | expressive_adequacy |
|-----------|-----------:|----------:|----------:|--------------------:|
| textbook  |      −3.36 |     −2.04 |     −1.88 |               −1.93 |
| holdout   |      −1.53 |     −0.43 |     −0.41 |               −0.38 |

## What this shows

**The headline finding decomposes cleanly:**

1. **In-distribution (holdout), the small distilled Reasoner is close to
   the 120B teacher on three of four dimensions** (coherence, substance,
   and expressive_adequacy gaps are all under 0.5). Engagement is the only
   meaningful gap (−1.53), which we trace below to two specific failure modes.
2. **Out-of-distribution (textbook), the Reasoner is dramatically behind
   on every dimension.** This is consistent with — and partially attributable
   to — the Translator(English → UGF) corruption that mangles textbook
   prompts before they reach the Reasoner.
3. **Expressive adequacy under UGF is high on holdout (3.17 Reasoner / 3.55
   Comparator).** Both systems clear the rubric's "UGF use feels native"
   threshold on most items. The vocabulary restriction is *not* the bottleneck
   on philosophical content within distribution.

## Per-type breakdown (holdout)

Where the Reasoner ties or beats the comparator (within distribution):

| type                       | n  | engagement | coherence | substance | expressive_adequacy |
|----------------------------|----|-----------:|----------:|----------:|--------------------:|
| concept_explanation        | 25 |  **+0.32** |     −0.12 | **+0.76** |               −0.08 |
| chain_of_thought           | 14 |      −0.29 |     −0.86 | **+0.21** |               −0.50 |
| socratic_dialogue          | 15 |      −0.13 |     −0.20 | **+0.33** |               −0.33 |
| thought_experiment         |  7 |       0.00 |     −0.57 |     −0.43 |               −0.43 |
| argument_analysis          |  9 |      −0.33 |     −0.33 |     −0.44 |               −0.44 |
| analogical_analysis        | 23 |      −1.56 |     −0.65 |     −0.56 |               −0.52 |
| conditional_analysis       | 27 |      −2.07 |     −0.45 |     −0.70 |               −0.56 |
| counterexample_analysis    | 50 |      −3.34 |     −0.42 |     −1.16 |               −0.32 |

The Reasoner **wins on substance** in concept_explanation (+0.76),
chain_of_thought (+0.21), and socratic_dialogue (+0.33) — these are the
three CONTENT_TYPES on which it has the most direct training overlap
with what the comparator produces under the same UGF system prompt.

The two largest holdout-side weaknesses:
- **counterexample_analysis** (n=50, the largest type): −3.34 engagement,
  −1.16 substance. Inspection of low-scored items shows many cases where
  the Reasoner answers a *different prompt* than the truncated
  counterexample target (e.g., the prompt asked for a counterexample to a
  consistency biconditional in formal logic; the Reasoner produced an
  unrelated essay on testimony and repetition). Many of the counterexample
  prompts are heavily truncated in the corpus (cut off mid-sentence in the
  question field), which plausibly drives prompt/response mismatch.
- **conditional_analysis**: −2.07 engagement gap. Likely a similar
  prompt-coverage issue.

## Per-type breakdown (textbook)

Every type is heavily negative for the Reasoner. The pattern is most
extreme on:
- **statement_vs_nonstatement**: −3.93 engagement
- **missing_premise**: −3.80 engagement
- **validity_judgment**: −3.80 engagement
- **statistical_fallacy**: −3.60 engagement, **−3.40 coherence**, −3.07 substance

These are tasks where the prompt's analytical demand (e.g., "is this
sentence a statement or not?") is already a sentence-level operation, and
the Translator(En→UGF) step strips or distorts the very target phrase.
The Reasoner then produces a generic philosophical essay that misses the
narrow analytical question.

## Tier distribution

Sum-of-4-dimensions tiers per system:

| system                | high (≥14) | mid (8–12) | low (≤6) |
|-----------------------|-----------:|-----------:|---------:|
| Reasoner — textbook   |          0 |         39 |       71 |
| Comparator — textbook |         88 |         18 |        0 |
| Reasoner — holdout    |         42 |         80 |       19 |
| Comparator — holdout  |        102 |         46 |        1 |

The Reasoner produces top-tier (≥14/16) responses on **25% of holdout
items**. Zero top-tier responses on textbook is the headline failure of
the chatbot pipeline.

## Representative scored examples

### Reasoner — holdout, top-tier (sum 15/16)

**Prompt:** "how a group can agree on rules that are good for everyone"
(thought_experiment, holdout)

**UGF response (excerpt):**
> a group of people wants to live or work together in one place. To stay
> safe and feel good, they must agree on how they will act. […] First,
> some people might say that the best way is to do what makes the most
> people feel good. […] Second, other people might say that this is wrong.
> They think that every person is important and cannot be used just to
> make others feel good. They think that even if a way of acting makes
> many people feel good, it is bad if it hurts one person in a bad way.

**Scores:** engagement=4 ("Engages the social-contract / rule-justification
question directly and stages a real dialectic"), coherence=4, substance=3,
expressive_adequacy=4.

### Reasoner — textbook, low-tier (sum 2/16)

**Prompt:** "Identify whether each sentence is a statement (something
that can be true or false) or not. *Some things with wings cannot fly.*"

**UGF response (in full):**
> the air that we breathe moves and people can feel the hurt of that air.
> We see that these things are not like the world we live in.

**Scores:** engagement=0, coherence=1, substance=0, expressive_adequacy=1.
Judge note: "Severe truncation or generation failure."

This is the textbook-pipeline failure mode: the Translator(En→UGF) renders
"Some things with wings cannot fly" into an in-vocabulary form that no
longer triggers the analytical task in the Reasoner; the Reasoner then
emits two unrelated sentences.

### Comparator — textbook, top-tier (sum 16/16)

**Prompt:** survey-from-detention-students bias example.

**UGF response (excerpt):**
> The first idea is that the head teacher asked only the students who
> were being kept after class to answer a set of questions about how
> happy they feel with school. […] That thinking is not good because the
> group he asked is not like the whole school; the students who are kept
> after class are more likely to be upset, so using their answers to
> guess what all students think is a weak guess.

This is what the rubric calls a 4 across the board, in UGF — sample-bias
recognition rendered cleanly without the technical term "biased sample."
The comparator can do this on textbook prompts because the UGF system
prompt operates on its full English understanding of the question; it
only restricts the *output* vocabulary.

## What we now know about UGF expressive adequacy

The project's animating question is whether ~1000 common-word UGF can
support practical philosophical reasoning. The judge's
expressive_adequacy scores answer this clearly **for the holdout
distribution**:

- Comparator-holdout: 3.55 / 4 — gpt-oss-120b can reason well in UGF.
- Reasoner-holdout: 3.17 / 4 — the from-scratch 200M Reasoner also
  produces UGF that the judge rates as cleanly carrying the philosophical
  content most of the time.
- Both well above the rubric's "2" anchor ("recoverable but clunky").

The textbook expressive_adequacy drop on the Reasoner side (1.75) is
**not** a UGF-vocabulary failure — those low scores arise because
Reasoner outputs on the textbook benchmark are often off-topic or
truncated, which pulls down D4 along with the other dimensions. This is
not the Sheffer-stroke regime that the rubric warns about.

## Caveats and limitations

1. **Single judge.** All scores come from one judge model (Claude Opus
   4.7, with one batch via Sonnet 4.6). Inter-rater calibration with
   Bert (planned: 30–50 prompts hand-rated blind) has not yet been run.
   Until that's done, ρ between judge and Bert is unknown.
2. **Judge-system overlap.** The judge is from the same model family as
   one of the *generators* of items the judge scores. We are scoring
   Reasoner responses (which were produced by a from-scratch 200M model
   trained on a corpus that includes some Sonnet-generated traces — but
   only ~485 / 1.96M ≈ 0.025%, negligible) and Comparator responses
   (gpt-oss-120b — different family). The judge has no direct
   self-favoring bias.
3. **Blinding within batches.** Each batch contains items from a single
   system. The judge does not know which system but the batch is
   homogeneous; cross-batch calibration relies on the rubric anchors
   alone. Mixed-batch design would be more robust if we re-run.
4. **Sample size.** 115 textbook + 170 holdout = 285 items per system.
   Per-type cells in holdout range from 7 to 50; small-cell deltas
   should be read with that uncertainty in mind.
5. **One filtering refusal during scoring.** Reasoner-textbook batch 02
   was refused once by Opus on policy grounds and successfully scored on
   retry by Sonnet 4.6. Substance of the items (logic-textbook fallacy
   examples) likely tripped a content classifier; the items themselves
   are unobjectionable.

## Implications

1. **The 200M Reasoner is doing its job in distribution.** The headline
   "Reasoner shines on holdout" claim from the Layer-2 length-stats
   report — which we had to walk back after the Translator-degeneracy
   diagnosis — is *re-validated* here at the rubric level, this time
   directly on the UGF responses. Coherence, substance, and expressive
   adequacy are all near-comparator on holdout.
2. **The chatbot pipeline is still the bottleneck.** Both the
   Translator(En→UGF) on textbook prompts AND the Translator(UGF→En)
   on Reasoner outputs (separate workstream) need fixing before user-
   visible English-in / English-out chatbot use is viable.
3. **Counterexample-analysis and conditional-analysis prompts in the
   corpus are partially broken at the data level.** Many are truncated
   mid-sentence, which leaks into a real Reasoner failure mode (answers
   the wrong thing). A future corpus pass could clean these.
4. **D4 ≥ 3 on holdout for both systems.** The vocabulary-restriction
   does not, on this evidence, prevent practical philosophical reasoning
   at the level of the prompts in the holdout benchmark.

## Files

- `eval/results/judge_aggregate.json` — full structured aggregate (per-system,
  per-dimension, per-type, including histograms)
- `eval/results/judge_examples.json` — sampled high/mid/low examples per system
- `eval/judge_input/*.jsonl` — 16 blinded input batches
- `eval/judge_output/*.jsonl` — 16 judge output batches
- `eval/aggregate_judge_scores.py` — reproducible aggregator
- `eval/sample_judge_examples.py` — reproducible example sampler
- `eval/prepare_judge_batches.py` — batch prep
