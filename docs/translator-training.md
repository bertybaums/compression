# Translator training — technical writeup

**Date:** May 12, 2026 (writeup); training itself completed April 16, 2026
**Audience:** RCDS / cluster operators (primary) and ML research collaborators (secondary)
**Repository:** [`bertybaums/compression`](https://github.com/bertybaums/compression)

This document pulls together everything needed to understand how the project's Translator was trained: what it is, what it does, where the code lives, what data it saw, and what we learned the hard way after deploying it. It is meant to stand on its own — if you have not read the [progress report](index.html), this writeup gives you enough to reason about the Translator as an artifact.

> **Status note.** The Translator was originally meant to be a scientific instrument: it would let us round-trip English questions through a UGF-only Reasoner and read the Reasoner's UGF outputs back in English. On May 5, 2026 we discovered the UGF → English direction is degenerate on Reasoner-style UGF (catalogued below). We pivoted the evaluation methodology to UGF-direct LLM-judge scoring; the Translator is now a chatbot-pipeline concern rather than part of the scientific apparatus. This writeup describes the model as it was trained, with the degeneracy discussion in §7.

---

## 1. Goal and scope

The Translator is a small encoder–decoder model whose job is to bridge full English and Up Goer Five (UGF, the ~1,000-word common-English vocabulary used by the Reasoner). It has two operating directions:

- **English → UGF.** Used to convert natural-English user inputs into the constrained vocabulary the Reasoner can consume.
- **UGF → English.** Used to convert the Reasoner's UGF output back into idiomatic English for display.

There is exactly one model fulfilling both roles, conditioned on the direction via a prefix token in the input (see §3). The model is **fine-tuned from a pretrained T5-small** rather than trained from scratch, because (a) we want the English encoder to already understand idiomatic input, and (b) for the small-data fine-tuning regime we are in, starting from a pretrained checkpoint is dominant over starting from scratch.

The Translator is *not* the scientific instrument. The Reasoner is. The Translator is infrastructure — its job is to make the Reasoner accessible from outside the UGF vocabulary.

---

## 2. Architecture

- **Base model:** `google/flan-t5-small`. ~60M parameters. Encoder–decoder, 8 layers each, T5's standard SentencePiece BPE tokenizer (~32K tokens), instruction-tuned.
- **What gets fine-tuned:** all parameters. No frozen layers, no adapters. T5-small is small enough that full fine-tuning is cheap.
- **Why T5 specifically:**
  - T5's encoder–decoder shape natively matches the translation task (an encoder reads English / UGF; a decoder generates UGF / English).
  - Flan-T5's instruction tuning gives us a sensible default response to natural-language prefix instructions (`"translate to simple:"` etc.), which our two-direction scheme uses.
  - It's small enough to fit comfortably on a single A6000 with room for batch_size ≥ 32 at full precision and to train end-to-end in ~2 hours.
- **Why T5-small (not T5-base or larger):** dataset size dominated the size choice. The parallel corpus is ~262K passage pairs (see §5); at 524K training examples after both-direction augmentation, T5-small has plenty of capacity. Going to T5-base would have ~4× the parameter count for marginal expected gain.

Implementation: [`translator/model.py`](../translator/model.py).

---

## 3. Bidirectional prefix scheme

T5 was originally trained with a "task prefix" convention (`"translate English to German:"`, `"summarize:"`, etc.). We follow that pattern for the two directions:

| Input prefix | Source side | Target side |
|---|---|---|
| `translate to simple: <english>` | full English | UGF |
| `translate to full: <ugf>` | UGF | full English |

Every passage pair `(english, ugf)` in the training corpus yields **two** training examples — one in each direction — built in `translator/train.py::ParallelCorpusDataset.__init__`. This doubles the example count and lets a single model serve both directions.

The convention extends to inference: `Translator.to_ugf(english_text)` prepends the `translate to simple:` prefix and runs constrained decoding; `Translator.to_english(ugf_text)` prepends `translate to full:` and runs free decoding. See `Translator.to_ugf` and `Translator.to_english` in `translator/model.py`.

---

## 4. Constrained decoding for English → UGF

The hard requirement on the English → UGF direction is that **every output token must spell out a word that is in the UGF vocabulary** (or a piece of punctuation). T5's BPE tokenizer is not aware of UGF; it can happily emit sub-word pieces of "virtue", "epistemic", and other non-UGF words. To enforce the constraint at decode time we use a **`StateMachineLogitsProcessor`** (also in `translator/model.py`) which intercepts the decoder's per-step logits and masks out illegal token IDs.

### Construction

At initialization the processor builds an "allowed BPE token id" set:

1. Load the UGF vocabulary from `wordlist/vocab_final.json` (3,643 tokens — the curated ~1,000 lemmas × inflected forms).
2. For each UGF word, encode it twice via the T5 BPE tokenizer — once as `word`, once as `" word"` (T5's tokenizer is sensitive to leading space) — and union the resulting BPE token IDs into a set.
3. Add the IDs for whitespace, common punctuation (`. , ! ? ; : - ' " ( ) <space> <newline>`), and the ten digit characters.
4. Add T5's EOS and PAD token IDs.

The resulting `allowed_token_ids` set covers every BPE token that *could* appear inside a valid UGF rendering. Anything outside the set is permanently illegal.

### Application

At every decoding step the processor builds a `[vocab_size]` mask tensor with `0.0` for allowed tokens and `-inf` for disallowed tokens, and **adds** it to the logits. This is mathematically equivalent to renormalizing the softmax over only the allowed tokens. The mask is computed once per device and cached.

> **Caveat worth flagging.** The current implementation is a *simplified* constraint: it allows any BPE token whose ID could appear inside a valid UGF rendering, not a trie-walking state machine that enforces "the BPE tokens so far must spell a UGF-vocabulary prefix." A motivated decoder could string together BPE pieces that, recombined, spell a word that is not in UGF — for example, the BPE pieces of `"some"` and `"thing"` are both allowed because they appear in UGF words, but the combined word `"something"` might not be. In practice this is rare because the model is fine-tuned on a corpus where UGF compliance is enforced; the constraint is a backstop, not the primary mechanism. A trie-state-machine version would close this gap and is on the followup list.

---

## 5. Parallel corpus (data)

The training data is a single JSONL at `corpus/processed/parallel_corpus.jsonl` (gitignored — regenerable from sources). Each record:

```json
{"id": "...", "english": "...", "ugf": "...", "metadata": {...}, "compliant": true}
```

### Source material

Two sibling projects contribute the English side:

- **good-thinking-bot** (~27K records across 182 taxonomy codes covering logic, decision theory, game theory, cognitive biases, Dennett's thinking tools). The English passages here are short, didactic, definition-style.
- **Intro ethics textbook manuscript** (142 passages spanning virtue ethics, justice, deontology, utilitarianism, care ethics, AI ethics). Longer, more discursive, academic-register prose.

Both source projects were extracted via `corpus/generation/extract_sources.py` to a flat list of English passages, ~262K total after deduplication.

### UGF side generation

The UGF side is produced by **teacher distillation**: each English passage is passed to gpt-oss-120b via the MindRouter institutional gateway with a system prompt that instructs strict UGF-vocabulary use, followed by a vocabulary-validation retry loop:

1. Generate UGF rendering.
2. Run `validate_ugf()` on the result; if any out-of-vocabulary words are found, send a correction prompt naming the violations.
3. Up to `max_validation_retries=4` retries per passage.
4. Mark `compliant=True` only if the final output passes validation.

Implementation: `corpus/generation/generate_parallel.py`. The pipeline runs async with a configurable concurrency cap (default 16 workers); the validation loop and retries mean that post-pipeline, ~99% of records have `compliant=True` (the 1% that don't are excluded from training via the `filter_compliant=True` flag in the data loader).

### Holdout split

A **document-stratified 5% holdout** is computed by `corpus/generation/make_holdout_split.py` and saved to `corpus/processed/heldout_ids.json`. The split is by *source document*, not by passage — so all passages from one good-thinking-bot document, or one ethics-textbook chapter, end up either entirely in training or entirely in holdout. This avoids the leakage problem where two near-duplicate passages from the same document end up split across train/eval.

Both the Translator and the Reasoner read the same holdout file. This was deliberate: the Reasoner's training data (UGF reasoning traces) is generated from the same English passages, so a random per-passage split would risk a Translator holdout passage leaking into the Reasoner via the reasoning-trace pipeline. The coordinated split keeps the two evaluations honest.

### Final training-data size

After holdout filtering and the both-directions augmentation in §3, the Translator saw **~524K training examples** (262K passage pairs × 2 directions). 95% / 5% train/val split within that for early-stopping purposes.

---

## 6. Training procedure

### Hyperparameters (`configs/translator.yaml`)

| | Value |
|---|---|
| Base model | `google/flan-t5-small` |
| Batch size | 32 |
| Learning rate | 3e-4 |
| LR schedule | Cosine with 500 warmup steps |
| Optimizer | AdamW (weight decay 0.01) |
| Epochs | 10 |
| Max source length | 256 BPE tokens |
| Max target length | 384 BPE tokens (UGF is longer than its English source by ~30–50% because words like "essence" expand to "what something really is") |
| Gradient clip | 1.0 |
| Mixed precision | bf16 if supported, else fp16 |
| Loss | Standard label-smoothed cross-entropy from HuggingFace's T5ForConditionalGeneration |

Implementation: [`translator/train.py`](../translator/train.py). The training loop is intentionally vanilla — no custom losses, no curriculum, no auxiliary objectives. The combination of (i) a strong pretrained encoder, (ii) a teacher-distilled corpus with ~99% UGF compliance, and (iii) the inference-time constraint mask was the simplest design we could justify, and it worked.

### Cluster operations (RCDS / fortyfive)

- **Partition:** `gpu-8` (RTX A6000, 48GB).
- **Resources requested:** 1 GPU, 8 CPUs, 32 GB RAM, 48 h wall-time cap (real runtime was ~2 hours).
- **SLURM script:** `slurm/train_translator.sbatch`.
- **Environment:** `~/venvs/compression` Python venv. PyTorch 2.x with CUDA 12.x. Activated before launching the trainer.
- **Excluded nodes:** `n113,n118,n121,n122` — historically flaky for this project's workloads. Carry the exclude in if you reuse this template.

To launch:

```bash
ssh fortyfive.hpc.uidaho.edu
cd ~/compression
git pull
sbatch slurm/train_translator.sbatch
# Then monitor with squeue -j <jobid> and tail logs/<jobid>_translator.out
```

The training data file (`corpus/processed/parallel_corpus.jsonl`) is read **once at the start of training**; if the parallel-corpus generator is still appending to it, snapshot first (`cp parallel_corpus.jsonl parallel_corpus_final.jsonl`) to avoid reader/writer races.

### Result

| Metric | Value |
|---|---|
| Total training steps | ~163K (epochs × steps-per-epoch ≈ 10 × 16,375) |
| Final train loss | converged in epoch ~8–9 |
| Final val loss | **0.8807** |
| Best-val checkpoint | `~/compression/checkpoints/translator/best/` |
| Final-epoch checkpoint | `~/compression/checkpoints/translator/final/` |
| Wall-time | ~2 hours on a single A6000 |
| SLURM job | 5126226 (April 16, 2026) |

Both `best/` and `final/` are saved in HuggingFace's standard format (`config.json`, `pytorch_model.bin`, `spiece.model`, `tokenizer_config.json`). To load:

```python
from translator.model import Translator
t = Translator(model_name_or_path="~/compression/checkpoints/translator/best")
print(t.to_ugf("Justice requires impartiality."))
print(t.to_english("being right means treating everyone the same."))
```

---

## 7. Evaluation and the May 5 degeneracy discovery

### What we measured during training

Held-out validation cross-entropy (val_loss). 0.8807 looked reasonable for a T5-small fine-tune on a well-behaved parallel corpus.

### What we *didn't* measure during training, and should have

We did not directly evaluate the UGF → English direction on out-of-distribution UGF — specifically on UGF produced by the Reasoner rather than by the teacher distillation pipeline. The Translator's training data has gpt-oss-120b's UGF on one side; the Reasoner's output, while stylistically plausible, sits on a slightly different surface distribution (different scaffolding tokens, different line-break conventions, certain idiosyncratic phrasings). On Reasoner-style UGF the UGF → English decoder **does not just degrade gracefully; it produces dramatic hallucinations**.

### Failure modes (from the May 5 discovery)

Catalogued in [`memory/translator_degeneracy_insight.md`](../memory/translator_degeneracy_insight.md), but worth reproducing for the technical audience:

1. **Repetition loops.** A multi-claim UGF passage collapses to the same English clause repeated. E.g., the UGF *"a person can be kind and still be wrong about a fact. a person can be mean and still be right about a fact."* renders as *"We don't care if the person is good or bad. 4. We don't care if the person is kind or mean. 5. We don't care if the person is kind or mean."*
2. **Jargon hallucination.** Specific technical terms appear in the English output that are nowhere in the UGF input: "Levelk thinking", "Fourfold Pattern", "Expected Utility Theory (MEU)", "Premises: (1)…". The Translator is reaching into its pretraining and emitting plausible English-academic boilerplate it associates with the topic, not actually translating.
3. **Name hallucination.** Where the UGF input uses generic role descriptions ("the first person", "the second person") because the v1 corpus stripped proper nouns, the Translator invents specific names: "Mara", "Lira", "Thorne", "Red". This is a particularly clean case — it is *adding* referential content that has no source in the input.
4. **Infinite-loop generation.** The most extreme observed case: the UGF *"It is a good life"* was rendered as *"It is a good life. (3) It is a good life. (4) It is a good life. (5)…"* repeating fourteen times.

### Why val_loss 0.88 did not predict this

The Translator is fine on its training-distribution UGF — teacher-generated, with `Premises: 1.` scaffolds and the corpus's specific punctuation conventions. The Reasoner's UGF distribution is *close but not identical*, and T5-small fine-tuned with no robustness training is brittle on the difference. The held-out teacher UGF is closer to the Translator's training distribution than the Reasoner's UGF is, so the holdout val_loss does not exercise this failure mode at all.

### What this means for the evaluation pipeline

We pivoted in May to **scoring UGF directly** with an LLM judge (the four-dim rubric in `eval/rubric.md`, judged by parallel Claude subagents) rather than going through Translator(UGF→English). The judge can read UGF natively — it's just English with restricted vocabulary. Bypassing the Translator removed the hallucination layer between the Reasoner's actual output and what the judge sees. This is documented in the progress report §10–11.

The Translator-as-scientific-instrument story ended here. The Translator-as-chatbot-component story is alive — a user-facing demo still needs a UGF → English step — and is on the followup list as a separate workstream.

---

## 8. Known limitations and what would need to change

### Open issues

1. **Surface-distribution shift on Reasoner UGF.** The dominant problem. Two repair paths:
   - **Augment the training corpus with Reasoner-output UGF.** Round-trip: generate Reasoner UGF on a held-out set of English passages, hand-curate or teacher-rewrite the English target, add the pairs to the parallel corpus, retrain.
   - **Train with stylistic noise.** Perturb the UGF side of training pairs during data loading (whitespace jitter, scaffold rewriting, phrasing substitutions) so the Translator sees a broader UGF surface distribution.
2. **The constrained-decoding mask is over-permissive.** §4's caveat: a BPE token that appears inside any UGF word is whitelisted, but combining whitelisted tokens does not guarantee a UGF word. A trie-walking state-machine version of `StateMachineLogitsProcessor` would close this.
3. **English → UGF on out-of-distribution natural English** (proper nouns lost, technical jargon dropped). Less catastrophic than the reverse direction, but a real limitation in the chatbot pipeline.
4. **No direct evaluation of either direction on the actually-deployed distribution.** The training-time val_loss was the only signal during training; the May 5 discovery was post-hoc. A more responsible procedure: at end of training, generate a small Reasoner-UGF probe set and inspect 50–100 round-trip outputs by hand before declaring done.

### What we'd do differently

- **Probe before declaring done.** End-of-training, hand-inspect 50–100 round-trip samples on the actually-intended input distribution (Reasoner output, not teacher output). Catches degenerate behaviors invisible to val_loss.
- **Include some held-out targets in the input distribution.** If you know the deployed inputs will differ from training inputs (we did — Reasoner UGF vs teacher UGF), bake that into the train/dev/test split.
- **Maybe move to from-scratch.** A small from-scratch encoder–decoder trained jointly with the Reasoner might give us a cleaner mutual representation. T5's pretraining adds English priors we then have to fight (the jargon-hallucination failure mode looks exactly like T5 reaching into its prior).

---

## 9. File map (for the RCDS audience)

Everything you'd want to inspect or rerun, by path:

```
configs/translator.yaml                    # Training config (lr, batch, epochs, paths)
slurm/train_translator.sbatch              # SLURM submission script
translator/__init__.py
translator/model.py                        # Translator class + StateMachineLogitsProcessor
translator/train.py                        # ParallelCorpusDataset + training loop

corpus/generation/generate_parallel.py     # Parallel-corpus generator (teacher distillation)
corpus/generation/validate_ugf.py          # UGF vocabulary validator (used by generator and judge)
corpus/generation/make_holdout_split.py    # 5% doc-stratified holdout
corpus/generation/extract_sources.py       # English-passage extraction from source projects

corpus/processed/parallel_corpus.jsonl     # Final training data (gitignored — regenerable)
corpus/processed/heldout_ids.json          # Holdout doc IDs (committed)

wordlist/vocab_final.json                  # 3,643-token UGF vocabulary
wordlist/curate_wordlist.py                # Vocabulary curation pipeline

# On fortyfive (not in this repo):
~/compression/checkpoints/translator/best/      # Best-val checkpoint (HuggingFace format)
~/compression/checkpoints/translator/final/     # Final-epoch checkpoint
```

To verify Translator outputs interactively (on fortyfive, with a GPU allocation):

```bash
source ~/venvs/compression/bin/activate
cd ~/compression
python3 -c "
from translator.model import Translator
t = Translator(model_name_or_path='checkpoints/translator/best')
print('EN→UGF:', t.to_ugf('Justice requires impartiality.'))
print('UGF→EN:', t.to_english('being right means treating everyone the same.'))
"
```

---

## 10. Open questions for collaborators

If you're reading this because you're considering working on the Translator side of the project:

- **The repair priority is the UGF → English degeneracy on Reasoner-style UGF.** Round-tripping the existing Reasoner output through a teacher to create training-pair augmentation is the most direct path. Estimated effort: 1–2 days of teacher API time + 2 hours of training.
- **The form-diverse corpus pipeline** (`docs/followups/corpus-diversification.md`) is producing a new generation of UGF training data with deliberately-varied surface structure (Plato-style dialogue, Aquinas-style objection-and-reply, Sextus-style skeptical-mode, etc.). When that lands, retraining the Translator on the broader UGF distribution may close the degeneracy gap without bespoke round-trip augmentation.
- **A from-scratch encoder–decoder** trained jointly with the Reasoner is the high-effort high-reward alternative. We have no current plan to do this but it would be a clean fix.

For deeper context on why the project structurally de-emphasized the Translator after May 5, see the [progress report §10–11](index.html) and the project's CLAUDE.md.
