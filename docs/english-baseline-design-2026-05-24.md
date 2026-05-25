---
title: "200M English-vocab baseline — design (the Sheffer-stroke contingency, activated)"
date: May 24, 2026
audience: project
status: design (pre-build) — decisions locked, pre-registered
---

# 200M English-vocab baseline: design

## The short version

The v1 paper attributes the prompt-attention deficit to "capability/training-form" and sets the *vocabulary* aside on the grounds that teacher-in-UGF is fine. But the teacher is 120B. That a 120B model has no deficit in UGF does not show a *200M* model's deficit is vocabulary-independent. This experiment isolates the vocabulary axis **at the student scale**: train a 200M model on the *same prompts, same teachers, same content-types, same recipe* — only the vocabulary changes from ~1K-word UGF to ~40K-word English — and ask whether the deficit travels.

The deferred "Sheffer-stroke contingency" comparator (`eval_comparator_strategy.md`, deferred April 29) is now activated.

## Why there is no losing outcome

The deficit's cause is ambiguous between *form*, *capacity*, and *vocabulary*. This experiment is decisive on the vocabulary axis, and **every outcome is informative** (pre-registered interpretation):

| 200M-English stress engagement vs UGF | Reading | Effect on the paper |
|---|---|---|
| within ~0.3 (also deficient) | Vocabulary **exonerated** — the deficit is form/capacity, shared with English | *Strengthens* the expressive-adequacy thesis: the restriction is not what breaks the model |
| ≥ ~1.5 higher (no deficit) | Vocabulary **implicated** — UGF specifically costs prompt-attention at 200M | A *sharper* paper: empirical Sheffer-stroke — restricted-vocabulary derivations exceed the capacity budget |
| in between | Partial — vocabulary contributes but is not the whole story | Quantifies the vocabulary's *share* of the deficit |

**Honest expected value:** the first row is most likely, because the English corpus inherits the identical short-prompt→long-essay form, so the English model should learn the same essay-reflex. This is probably a confirmation, not a discovery. It is still worth ~1.5–2 weeks because it (a) converts the paper's central attribution from assumption to measurement, (b) answers the first question a reviewer asks ("how do you know it's not the vocabulary?"), which "the teacher's fine" does not answer at student scale, (c) carries option value on the low-probability reframe, and (d) is the first cell of the scaling grid (`docs/followups/scaling.md`, cell e) — compute is not wasted either way.

## Locked decisions (May 24, 2026)

1. **Matched fresh pair at N≈300–500K** (not reuse-v1-at-2M). Subsample existing UGF traces for N matched `(topic, content_type)` prompts; generate English for the *same* N; train both 200M models fresh and identically. Scale is an explicit control; vocabulary is the only variable; the fresh UGF model replicates the deficit as a robustness check. The published v1-UGF-2M model is kept as an anchor.
2. **Word-level English tokenizer, ~40K words** (not BPE). Mirrors the UGF model's word-level design so vocabulary *size* is the sole variable. Hold the transformer block (~193M params) equal across arms; report totals.
3. **Run the P3 teacher-scale precursor first** before committing the 200M training compute.

## Controls — what is held constant

The corpus record schema retains `topic` and `content_type`, and the prompt is rebuilt deterministically as `CONTENT_TYPES[content_type].format(topic=topic)` (verified in `corpus/generation/generate_reasoning.py`). So a properly matched English corpus is the same prompts with the UGF system prompt removed.

| Held constant | How |
|---|---|
| Content / topic | Same `(topic, content_type)` pairs as the UGF-N arm |
| Form | Same short-prompt→reasoning structure, same content-type templates |
| Teacher ensemble | Same gpt-oss-120b + gemma-4-26b mix, same decoding params |
| Data scale | Same N traces both arms |
| Recipe | v1 schedule: 100K pretrain (`train.py`) + 30K SFT (`train_sft.py`), plain prompt→response format |
| Transformer capacity | ~193M non-embedding params both arms (the "reasoning engine") |
| Eval | Same benches, rubric, blinded Claude-subagent judge |
| **Vocabulary (the variable)** | ~1K-word UGF (3,643 tokens) vs ~40K-word English |

**Parameter accounting.** UGF embeddings ≈ 3,643 × 1024 ≈ 3.7M; English embeddings ≈ 40K × 1024 ≈ 41M. Holding the transformer equal (~193M) gives totals ~197M (UGF) vs ~234M (English). The embedding difference is a *direct consequence of the variable under study*, not a separate confound. Report both totals and **per-episode token counts** — if UGF needs more tokens for the same content, that is the Sheffer-stroke "longer derivations" cost, quantified.

**Residual asymmetries — disclose, do not fix:**
- UGF corpus passed a compliance filter + retry loop; the English arm does not need one (minor process difference).
- The English word-level tokenizer will hit OOV on bench prompts (the UGF model cannot, by construction). Define an `<unk>` policy and report OOV rate.
- `expressive_adequacy` is N/A for the English arm; the comparison dims are engagement, coherence, substance.
- The judge now grades English for one arm; engagement and substance are language-agnostic enough, but note it.

## Precursor — P3 teacher-scale vocabulary tax (~1 day)

Before any training, get the *teacher-scale* version of the same question nearly for free:

1. **Target-probe (free):** the 50 target-probe prompts already have cached gold-English reasoning in the `en_intermediate` field of the P4 outputs (`eval/run_target_probe.py:generate_p4`). Score those against the existing P5 (teacher-in-UGF) scores on engagement/coherence/substance.
2. **Benches (~1 cheap gen pass):** generate gold-English teacher answers for the stress + holdout prompts (one MR call each, no translation, no training, via the rate limiter), score against the existing teacher-in-UGF comparator.
3. **Read:** the gap (gold-English − teacher-in-UGF) on engagement/substance = the vocabulary cost *at 120B*. If even the teacher pays a measurable cost, that reshapes how we read the student result. Either way this fills the P1–P5 gap (P3 was generated as an intermediate but never scored).

## Main experiment — build

### 1. English word-level tokenizer (~40K)
- Curate a ~40K English wordlist (analog of `wordlist/curate_wordlist.py`; candidate source: top-40K by frequency over `corpus/processed/english_passages.jsonl` ∪ the teacher English traces).
- Build a word-level tokenizer mirroring `tokenizer/ugf_tokenizer.py` (same special tokens, same casing/punctuation handling, `<unk>` for OOV).

### 2. Matched corpus (N≈400K default, tunable 300–500K)
- **UGF-N arm:** subsample N records from `corpus/processed/ugf_reasoning.jsonl` preserving the `(topic, content_type)` distribution (reuse the sampling logic in `reasoner/build_phase0_essay_control.py`). No new UGF generation.
- **English-N arm:** for the *same* N `(topic, content_type)` pairs, generate English traces via the `generate_reasoning` pipeline with the UGF system prompt removed (plain reasoning prompt) — P3-at-scale. Same teachers, same decoding, same rate limiter. Faster than UGF gen (no compliance-retry loop).

### 3. Configs
- `configs/reasoner_ugf_n.yaml` — existing UGF tokenizer, UGF-N corpus, base 200M transformer.
- `configs/reasoner_en_n.yaml` — new English tokenizer (vocab ~40K), English-N corpus, **same transformer block** (~193M); report total params.

### 4. Train both, fresh, identical recipe
- `train.py` (100K pretrain) → `train_sft.py` (30K SFT), plain format, both arms. Run on separate gpu-8 GPUs in parallel.

### 5. Eval (pre-registered)
- Benches: **stress (primary)**, holdout, cx_patched. Reuse `slurm/eval_ckpt_bench.sbatch` + the blinded judge pipeline (`eval/prepare_*`, `eval/aggregate_*`).
- **Primary metric: stress-bench engagement.** UGF-N is expected to reproduce the ~0.13 deficit; the open question is English-N.
- Decision rule = the pre-registered interpretation table above (Δ vs UGF-N: within ~0.3 → exonerated; ≥ ~1.5 → implicated; between → partial).
- Also report per-episode token counts and English OOV rate.
- **Refinements from the precursor (May 24, `docs/precursor-result-2026-05-24.md`):** (1) judge the two arms in **isolation**, NOT mixed cross-register batches — the precursor proved cross-register contrast depresses the restricted-vocabulary arm by ~1 substance point on *identical* text. (2) Track **substance** as a co-primary metric alongside stress-engagement: the teacher-scale vocabulary tax is substance-concentrated, so expect English-200M to beat UGF-200M on substance even if both behave the same on engagement.

## Compute / cost estimate

| Stage | Estimate |
|---|---|
| Precursor (P3 teacher-scale) | ~1 day |
| English tokenizer + corpus build | ~1 day |
| English-N generation (~400K, no retry loop) | ~2 days within the rate cap |
| Training (2 models × pretrain+SFT, parallel on gpu-8) | ~3–5 days wall-clock |
| Eval (gen + blinded judge) | ~1 day |
| **Total** | **~1.5–2 weeks** |

## Risks & honest caveats

- **UGF-N may not reproduce the deficit at reduced N.** If so, bump N, or note the deficit is partly scale-dependent (itself informative). The comparison (UGF-N vs English-N) holds regardless.
- **English OOV on benches** is a real asymmetry the UGF arm doesn't have; mitigate with a sensible `<unk>` policy and report the rate.
- **English may distill more cleanly** because it's the teacher's native register — but that is the vocabulary effect we are measuring, not a confound.
- **First-pass English vs compliance-filtered UGF** — minor process difference, disclose.
- **A null/exonerating result is the likely one** and is fine — it strengthens the thesis. The experiment is framed so the expected outcome is still publishable.

## First concrete steps

1. **Precursor:** recover the 50 cached `en_intermediate` traces; generate gold-English for stress+holdout; score on the rubric; report the teacher-scale vocabulary tax.
2. Curate the ~40K English wordlist and build the word-level tokenizer.
3. Subsample UGF-N; generate English-N for the matched prompts.
4. Write the two configs (transformer held equal); train both fresh.
5. Bench-gen + blinded judge both arms; aggregate; apply the pre-registered decision rule.
