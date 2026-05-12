# Followup: Vocabulary × parameter scaling

**Date:** May 12, 2026
**Status:** skeleton — seeded from compression-v1
**Anchor in main paper:** Future Work §6 of `docs/paper-draft.md`
**Thread in memory:** D (upgraded from one-axis to two-axis on May 12)

---

## Thesis

Vocabulary structure is partially substitutable for model parameters. A small model trained over a tightly constrained, semantically-rich vocabulary may approximate the performance of a much larger model with full-vocabulary access on the same cognitive domain. Compression-v1 provides one data point — a 200M-parameter model trained on 1K UGF words performs within 0.5 of a 120B teacher on three of four rubric dimensions for within-distribution philosophical reasoning. The 2D scan extracts the iso-performance curve in the (params, vocab) plane and gives us a *scaling law for restricted-vocabulary models*.

## The grid

|                  | 1K-word UGF | ~5K-word Basic English / Globish | ~50K-token standard tokenizer |
|------------------|:-----------:|:--------------------------------:|:-----------------------------:|
| **~50M params**  | (a)         | (b)                              | (c)                           |
| **~200M params** | compression-v1 | (d)                            | (e)                           |
| **~1B params**   | (f)         | (g)                              | (h)                           |

Compression-v1 is the (200M, 1K) cell. The 2D scan fills the remaining 8.

## Methods

- **Same eval pipeline** as compression-v1: 170-item holdout, 30-item stress bench, four-dim rubric judged by parallel Claude subagents.
- **Same teacher distillation source** (gpt-oss-120b + gemma-4-26b ensemble via MindRouter), with the system prompt re-tuned per vocab regime to produce on-vocab traces. Re-distillation across regimes introduces a teacher-artifact risk — see Risks.
- **Same architecture family** (decoder-only transformer) at each size point; widen rather than deepen to keep activations comparable.
- **Hold corpus topic distribution constant** by re-translating the same source documents through each vocab regime, rather than collecting independent corpora per cell.

## Output

- Per-cell scores on (engagement, coherence, substance, expressive_adequacy).
- Iso-performance contours (e.g. "what (params, vocab) pairs achieve D4 ≥ 3?").
- A functional form, if one emerges — possibly something like *effective parameters = f(actual params, vocab structure)*.

## Venue candidates

NeurIPS, ICLR, COLM. Workshops if scope tightens (e.g. NeurIPS workshops on scaling laws, on small language models, on data-centric ML).

## Compute estimate

- 9 training runs total. Compression-v1 is the (200M, 1K) cell, free.
- ~50M cells: ~3 days each = ~9 days.
- ~200M cells (besides v1): ~1 week each = 2 weeks.
- ~1B cells: ~2 weeks each = 6 weeks.
- Inference + eval: ~1 week.
- **Total:** ~10 weeks of mostly-serial compute on the gpu-8 partition. Could compress to ~6 weeks if multiple cells run in parallel on separate nodes.

## Dependencies

- **Thread G (paper drafting)** anchors the (200M, 1K) cell. Don't start D before G has a stable methods section.
- **Thread B2 (form-diverse retraining)** is now a hard prerequisite, not a "should land first" nice-to-have. See `docs/followups/corpus-diversification.md`. The argument: if we run the 2D scan on the v1 corpus, every cell of the 1K column inherits the prompt-attention deficit by construction, and the substitutability claim becomes "vocabulary structure substitutes for parameters, conditional on a corpus that may be artifactual" — which is not a result that travels. Run B2 first; train all D cells on the form-diverse corpus.
- **Thread A (judge calibration)** hardens every cell's evaluation, not just compression-v1.

### Corpus sequencing (added May 12 2026)

The original sequencing was "G → A → D." The revised sequencing is **G → A → B2 → D**, where B2 produces the corpus that D's grid runs on. B2 is roughly 3–4 weeks of work (see corpus-diversification.md) and adds materially to the scientific defensibility of D's substitutability claim. The compression-v1 cell of the grid stays as-is — its data is the anchor; subsequent cells are trained on the form-diverse corpus.

## Risks

- **Teacher artifact across vocab regimes.** Asking a teacher to write at 5K-word level is not the same as asking a fluent 5K-vocabulary human to write. Need a vocabulary-controlled prompt template per regime and manual review of a per-regime sample.
- **Vocabulary mismatch with tokenizer.** The 1K column requires a 1K-token tokenizer; the 50K column uses standard BPE. Token efficiency varies, which complicates loss comparisons. Report on a per-example basis and use the rubric scores (which are token-agnostic) as primary metrics.
- **Cost.** A 1B-parameter run is real money. Justifying it requires landing the smaller cells first.

## Why it matters

Connects compression-v1 to three existing literatures simultaneously: scaling laws (Kaplan et al.; Hoffmann et al.), restricted-vocabulary linguistics (Basic English; controlled languages), and interpretability via vocabulary constraint (Ramji et al. 2026 abstract-CoT). Produces a clean substitutability claim — "vocabulary structure substitutes for parameters at rate r" — which is the kind of result that travels.

## What to write into paper G's Future Work

> **Vocabulary × parameter scaling.** A 2D scan over {50M, 200M, 1B} × {1K, 5K, 50K} would let us extract iso-performance curves and test whether vocabulary structure substitutes for parameters in a regular way. Compression-v1 is one cell of this grid; eight remain.
