# Compression

**Expressive Adequacy of a Radically Constrained Vocabulary for Philosophical Reasoning**

> ⚠️ **Preliminary research, work in progress.** This repository hosts active research artifacts — code, intermediate results, a draft paper skeleton, and a presentation that walks through what we have learned so far. Numbers and architectural details have changed during the project and may change again. Treat anything here as a snapshot, not a final claim, until the paper lands.

---

## The question

Is the ~1,000-word **Up Goer Five** fragment of English (Randall Munroe's *Thing Explainer*) **expressively adequate** for practical philosophical reasoning — logic, ethics, decision theory, critical thinking? The motivating analogy is the Sheffer stroke: NAND is functionally complete for propositional logic at the cost of longer formulas. We ask whether ~1,000 common English words can do the analogous work for natural-language philosophical content.

## What we have learned so far (as of May 12, 2026)

The headline answer splits into two pieces:

1. **Up Goer Five appears expressively adequate for the philosophical content of our benchmark, within calibrated limits.** A teacher in UGF (gpt-oss-120b under our system prompt) scores ≥ 2.67 / 4 on expressive adequacy across every stress-bench category we measured, and ≥ 3.0 on the within-distribution holdout. The vocabulary does not break — it thins out at the edges (modal contingency, supervenience, type/token distinctions, recursive self-reference). That thinning is itself a positive, interpretable result.

2. **Our 200M-parameter from-scratch Reasoner has a *prompt-attention deficit*.** It produces fluent UGF reliably, and on within-distribution prompts (170-item holdout) it scores within 0.5 of the 120B teacher on three of four rubric dimensions. But on prompts whose *form* differs from the training corpus (longer, interrogative, more specific), engagement collapses — the model produces fluent UGF *about something other than what was asked*. This is a model-capability finding, separable from the expressive-adequacy question.

The discovery-first writeup is in the RCDS presentation (link below). The amended headline of the project is now: *Up Goer Five appears expressively adequate; learning to do practical philosophy in it on a small model from scratch is a separate problem, and we have characterized a specific way the small-model version fails.*

## View the RCDS presentation online (no install needed)

The 16-section presentation is a self-contained HTML file that works as either slides (arrow-key navigation) or a long-form web essay. Render it in any browser via githack — a free CDN that serves raw GitHub content with correct MIME types:

**👉 [Open the presentation](https://rawcdn.githack.com/bertybaums/compression/main/docs/rcds-presentation-2026-05-11.html)**

Or, if githack is unavailable, the htmlpreview wrapper works as a fallback:
[htmlpreview.github.io fallback](https://htmlpreview.github.io/?https://github.com/bertybaums/compression/blob/main/docs/rcds-presentation-2026-05-11.html).

The raw source is at [`docs/rcds-presentation-2026-05-11.html`](docs/rcds-presentation-2026-05-11.html).

## Current architecture

Two models, but only one is doing scientific work right now.

### Reasoner — the scientific instrument

- 200M-parameter Llama-style decoder-only transformer, trained from scratch.
- Custom word-level tokenizer with **only** ~3,643 tokens: the ~1,000 most common English words (with inflections), basic punctuation, numerals, and special tokens.
- Both input and output strictly constrained to the UGF vocabulary.
- Trained via teacher distillation: ~1.96M (compliant) UGF reasoning traces produced by an ensemble of gpt-oss-120b + qwen3.6-27b + gemma-4-26b via MindRouter.

### Translator — separate workstream

A bidirectional English ↔ UGF model (T5-small with constrained decoding) was originally meant to enable round-trip evaluation. **The UGF → English direction turned out to be degenerate** on Reasoner-style UGF (May 5, 2026 discovery — see `docs/rcds-presentation-2026-05-11.html` §10). We pivoted the evaluation methodology to UGF-direct LLM-judge scoring; the Translator is now a chatbot-pipeline concern, not part of the scientific apparatus.

## Evaluation

Four-dimension rubric (engagement, coherence, substance, expressive_adequacy), 0–4 anchored, judged by parallel Claude subagents writing scored JSONL files (research-grade LLM-as-judge methodology; see `eval/rubric.md`). Three benchmarks:

- `eval/sets/holdout_bench.jsonl` — 170 within-distribution items, doc-stratified 5% holdout from the corpus.
- `eval/sets/stress_bench.jsonl` — 30 hand-crafted UGF-hard prompts spanning 10 categories (modal, supervenience, abstract objects, self-reference, use/mention, counterfactual, deontic, intensional, phenomenal, vagueness/sorites).
- `eval/sets/logic_textbook_bench.jsonl` — 115 items from Van Cleave's *Introduction to Logic and Critical Thinking* (CC-BY 4.0).

All four eval-layer reports + raw run JSONLs are in `eval/results/`. The current canonical reading is `eval/results/may7_full_report.md`.

## Three followup programs (the research-program reframe)

Compression-v1 is the proof of concept for three followup programs, each with a skeleton in `docs/followups/`:

- **Vocabulary × parameter scaling** ([`scaling.md`](docs/followups/scaling.md)) — a 2D scan over {~50M, ~200M, ~1B} params × {1K UGF, ~5K Basic English, ~50K standard} vocabularies. Extracts iso-performance curves to test whether vocabulary structure is substitutable for parameters.
- **Minimal sufficient vocabularies for cognitive domains** ([`sheffer.md`](docs/followups/sheffer.md)) — the Sheffer-stroke-for-cognition program. UGF-philosophy is data point one; math reasoning, legal reasoning, scientific explanation are natural next replications.
- **Inferentialism, empirically** ([`inferentialism.md`](docs/followups/inferentialism.md)) — the philosophy paper. The prompt-attention deficit is an empirical purchase on Brandom-style inferentialism about predicates; the descriptor-based name-stripping policy (see below) gives a parallel test for inferentialism about singular terms.

## Form-diverse corpus pipeline (Phase 1 ready to launch)

The v1 Reasoner's prompt-attention deficit is most likely a corpus-*form* artifact: v1's prompts are uniformly short topic phrases, and the model has internalized that form. The fix is to retrain on a corpus drawn from canonical philosophical *forms* — Platonic dialogue, Aquinas-style objection-and-reply, Pyrrhonist skeptical mode, and others. Plan and rationale: [`docs/followups/corpus-diversification.md`](docs/followups/corpus-diversification.md).

### What's built

- **Source parsers** (`corpus/poc/parse_*.py`): Plato dialogues (Meno, Crito, Euthyphro, Phaedo, Gorgias, Theaetetus, Protagoras — seven dialogues so far, all Jowett translations via Project Gutenberg), Hume's *Dialogues Concerning Natural Religion*, Aquinas's *Summa Theologica I*, Sextus Empiricus's *Outlines of Pyrrhonism I* (via Mary Mills Patrick's 1899 translation — covers all Ten Tropes of Aenesidemus plus the Five Tropes of Agrippa and the Two Tropes).
- **Per-form prompt templates** with few-shot exemplars and per-form correction templates: `corpus/generation/forms.py`.
- **Production runner** with multi-teacher dispatch, retry-on-violations loop, JSON-discipline retry, progress tracking, and resumable runs: `corpus/generation/generate_forms.py`.
- **Shared rate limiter with time-of-day scheduling**: `corpus/generation/rate_limiter.py`. Caps 100 req/min 5am–5pm PT and 200 req/min 5pm–5am PT so other RCDS users have MR headroom during business hours.
- **SLURM submission**: `slurm/generate_forms_corpus.sbatch`.

### Names policy

Zero proper nouns in the training data — *including* dialogue speakers. Each character is replaced by a stable UGF-vocabulary descriptor: Socrates → "the old teacher"; Demea → "the church man"; Cleanthes → "the man who sees plans"; Philo → "the careful one". Whether the descriptors come to function as names is an empirical post-training test (the "name-recovery experiment" — see `docs/followups/inferentialism.md`).

### Phase 1 numbers (verified May 12)

- **~2,800 compliant training pairs** from the current 10-source registry
- **~300K tokens** at the UGF tokenizer's roughly 1.1 tokens/word ratio
- **~5 MB on disk** (full archive including metadata for audit)
- **~3 hours** wall time to generate on the daytime rate cap; faster overnight

Scaling commentary and the bytes/tokens table at multiple scales (Phase 1 → Phase 2 → Path A → Path B) is documented in `docs/followups/corpus-diversification.md`.

## Paper

A skeleton with seeded prose for Introduction, Methods §3.1a (the names-as-referential-apparatus design choice), Discussion §5.2 (the inferentialist reading of the prompt-attention deficit), and Future Work §6 (pointers to all three followup programs) is at [`docs/paper-draft.md`](docs/paper-draft.md). The remaining sections are marked `[stub]` with the content they will carry.

## Reproducing what we have

Models and large data live on the U-Idaho HPC, not here. What this repo gives you:

1. The Reasoner architecture and training script (`reasoner/`).
2. The eval pipeline + rubric + benchmarks + scored JSONL outputs from every evaluation layer (`eval/`).
3. The full corpus generation pipeline — both the v1 reasoning-trace generator and the new form-diverse extractor (`corpus/generation/`).
4. The four parsers for public-domain philosophical source texts (`corpus/poc/parse_*.py`) and the resulting (source-pair) JSONL files.
5. The discovery-first RCDS presentation as a single self-contained HTML file (`docs/rcds-presentation-2026-05-11.html`).
6. The paper draft skeleton and the three followup-program skeletons (`docs/`, `docs/followups/`).

To regenerate the form-diverse corpus pipeline locally (against the institutional MindRouter endpoint, which requires a `MINDROUTER_API_KEY` we don't share):

```bash
# 1. Source-pair JSONLs (parsers auto-download from Project Gutenberg)
python3 corpus/poc/parse_plato.py --all
python3 corpus/poc/parse_hume.py --all
python3 corpus/poc/parse_aquinas.py --all
python3 corpus/poc/parse_sextus.py --all

# 2. Small smoke test (25 pairs per source, ~30 seconds, ~$0 in MR budget)
python3 corpus/generation/generate_forms.py \
    --sources corpus/generation/forms_sources.yaml \
    --output corpus/processed/ugf_forms_corpus.jsonl \
    --progress corpus/processed/forms_progress.json \
    --limit-per-source 25

# 3. Full Phase 1 run (~2,800 compliant pairs, ~3 hours)
python3 corpus/generation/generate_forms.py \
    --sources corpus/generation/forms_sources.yaml \
    --output corpus/processed/ugf_forms_corpus.jsonl \
    --progress corpus/processed/forms_progress.json
```

The pipeline is resumable: `forms_progress.json` tracks completed IDs, and kill-and-restart skips them.

## Acknowledgements

Research Computing and Data Services, University of Idaho; the fortyfive HPC cluster; the MindRouter institutional LLM gateway; the [`cx-bot`](https://github.com/bertybaums/good-thinking-bot) counterexample corpus; J. M. Van Cleave's *Introduction to Logic and Critical Thinking* (CC-BY 4.0); Project Gutenberg for the Plato / Hume / Aquinas / Sextus translations.

## Status — what's done, what's preliminary, what's next

- ✅ UGF vocabulary curation (3,643 tokens) and word-level tokenizer
- ✅ Source material extraction (good-thinking-bot, intro-ethics textbook, cx-bot, misccorpora)
- ✅ v1 reasoning corpus: **1.96M compliant traces** via teacher distillation
- ✅ 200M-parameter Reasoner trained from scratch (100K pretrain + 30K SFT, val loss 0.74)
- ✅ Four-dim eval rubric + four benchmarks (holdout, stress, textbook, patched-cx)
- ✅ Layer 1–4 evaluation with parallel Claude subagent judges
- ✅ Form-diverse corpus pipeline (parsers + generator + SLURM, ~2,800 pairs Phase 1 ready)
- ✅ Three followup-program skeletons with venue candidates and effort estimates
- 🔶 Inter-rater calibration (Bert hand-rates 30–50 items vs the LLM judge) — blocks paper
- 🔶 Form-diverse corpus continuation-SFT on the v1 Reasoner — Path A proof of concept
- ⬜ Second judge family for cross-judge validation
- ⬜ Translator(UGF→En) retraining (chatbot workstream; separate from the science)
- ⬜ Paper drafting (skeleton seeded; full draft requires calibration first)
- ⬜ 2D vocabulary × parameter scaling sweep (compute-heavy followup)
- ⬜ Multi-domain replication of the methodology (math, legal, scientific reasoning)
- ⬜ Inferentialism philosophy paper

## License

Code: TBD. Documents and presentation: TBD. Project Gutenberg sources are public domain. Van Cleave textbook excerpts in `eval/sets/logic_textbook_bench.jsonl` are CC-BY 4.0.
