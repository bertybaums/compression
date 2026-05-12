---
title: Compressed Vocabulary, Preserved Reasoning — A 200M-Parameter Test of Expressive Adequacy for Practical Philosophy
date: May 12, 2026
authors: Bert Baumgaertner (PI); Claude (research collaborator)
status: SKELETON — seed sentences planted for Intro / Discussion / Future Work; remaining sections marked [stub]
---

# Compressed Vocabulary, Preserved Reasoning: A 200M-Parameter Test of Expressive Adequacy for Practical Philosophy

> **About this file.** This is a skeleton, not a draft. The three sections most relevant to the followup-program seeding (Intro §1, Discussion §5.2 inferentialist reading, Future Work §6) are written in full Bert-voice. Other sections are marked `[stub: …]` with the content they should carry. Section numbers are placeholders; reorganize freely. Companion followup skeletons:
>
> - `docs/followups/scaling.md` — the 2D vocabulary × parameter scan
> - `docs/followups/sheffer.md` — the multi-domain minimal-vocabulary program
> - `docs/followups/inferentialism.md` — the philosophy-side companion paper

---

## Abstract

[stub: ~150 words. Draft order: (1) the question — is UGF expressively adequate for practical philosophical reasoning; (2) the method — 200M from-scratch decoder over 1K-word tokenizer, 1.96M-trace teacher-distilled corpus, four-dim rubric eval; (3) the within-distribution result — within 0.5 of 120B teacher on three of four dimensions; (4) the out-of-distribution finding — prompt-attention deficit, separable from vocabulary question; (5) the upshot — UGF is expressively adequate within calibrated limits, and we identify a specific small-model-on-narrow-corpus failure mode worth characterizing in its own right.]

---

## 1. Introduction

You can do quite a lot with one connective. The Sheffer stroke — NAND — is functionally complete for classical propositional logic: every truth function on Boolean inputs can be expressed using only NAND, at the cost of longer sentences. Nothing of importance becomes inexpressible. The vocabulary shrinks; the expressive power does not. This is a familiar move in the foundations of logic, but it points to a more interesting question in natural language: how much can you shrink an everyday vocabulary before something matters disappears?

Randall Munroe's *Thing Explainer* (2015) is a playful experiment in radical vocabulary reduction. The text restricts itself to the 1,000 most common English words — call this the **Up Goer Five** (UGF) vocabulary — and uses it to explain the periodic table, the constitution, the human cell, and the Saturn V rocket. Munroe's exercise is whimsical. But it raises a serious question: is this 1K-word fragment of English expressively adequate for *practical philosophical reasoning* — for the kind of disciplined argument that fills logic textbooks, ethics seminars, and decision-theory papers?

We test the question directly. We train a 200-million-parameter decoder-only transformer from scratch, with a custom tokenizer whose entire vocabulary is the ~1K UGF words plus minimal punctuation. We distill the model on 1.96 million teacher-generated traces of philosophical reasoning written in UGF. We then evaluate, on both within-distribution prompts and a hand-crafted stress benchmark, whether the model produces what a competent rubric reader would call good philosophical reasoning.

The result is, at first pass, encouraging: on within-distribution prompts the model scores within 0.5 of a 120B-parameter teacher on three of four rubric dimensions, and at the 3.0-of-4 threshold on expressive adequacy across every content type we measured. On a more demanding read, the story splits. The Up Goer Five vocabulary *is* expressively adequate for the philosophical content of our benchmark, within calibrated limits we will map. But our trained model exhibits a specific failure mode worth flagging in its own right: on out-of-distribution prompt forms, it produces fluent, structurally-correct UGF reasoning about something other than what was asked. We call this the prompt-attention deficit.

**This work bears on three threads that have until now stayed mostly separate:** inferentialist accounts of conceptual content (Brandom 1994; Sellars 1956), scaling laws for language models, and the program of identifying minimal sufficient vocabularies for cognitive domains. The first lets us interpret what it means that vocabulary compression preserves reasoning; the second positions a 200M-parameter result in a literature that is increasingly interested in small specialized models; the third generalizes the methodology. We touch each thread briefly in the discussion and develop the inferentialist reading in §5.2.

[stub: a closing orienting paragraph — "we proceed as follows: §2 background, §3 method, §4 results, §5 discussion, §6 future work."]

---

## 2. Background and related work

[stub: four short subsections.]

### 2.1 Restricted English

[stub: Ogden's *Basic English* (1930); Voice of America Special English; Globish (Nerrière 2006); plain-language movements in law and medicine. Note that prior empirical work has focused on *human* uptake of these vocabularies, not on training computational reasoners over them.]

### 2.2 Latent reasoning and abstract vocabularies

[stub: Ramji et al. 2026 "Thinking Without Words" — latent reasoning over abstract token vocabularies; 11.6× compression; Zipfian emergence. Position UGF as a *concrete* (lexical) version of the same general phenomenon.]

### 2.3 Inferentialism

[stub: brief — Sellars 1956 EPM; Brandom 1994 *Making It Explicit*; McDowell 1994 *Mind and World*. The claim: conceptual content is constituted by inferential role rather than by lexical label. Empirical tests of inferentialism have been rare; we offer one.]

### 2.4 Small-model and CoT-at-scale literature

[stub: Reference the Numerals project; the small-CoT literature scan (Wei et al.; Phi-series; Orca). Position 200M as the lower end of "credible reasoner" in the current literature.]

---

## 3. Method

[stub: standard methods section, ~3 pages.]

### 3.1 Vocabulary and tokenizer

[stub: UGF source — Munroe's curated 1K-word list; preprocessing; final tokenizer is ~1,050 tokens including punctuation and special tokens.]

### 3.1a Proper nouns: stripped, not preserved

The 1K-word vocabulary is the *conceptual* vocabulary of the Reasoner — predicates, common nouns, function words, and the inferentially-active material that does philosophical work. **Proper nouns are not part of the vocabulary, and they are stripped from the training corpus, including from dialogue passages where they would conventionally identify interlocutors.** Where the source text uses a name, the corpus-curation pipeline substitutes a stable UGF-vocabulary *descriptor* (e.g., Socrates → "the old teacher"; Cleanthes → "the man who sees plans"; Anytus → "the angry man"). The same descriptor is used for the same character across every passage drawn from the same source, so the descriptor functions as a stable referring expression composed of inferentially-active vocabulary.

We adopt this policy for three reasons. First, it preserves a clean statement of the project's expressive-adequacy claim: zero proper nouns, no asterisk. Second, it matches what the original UGF parallel corpus already did (proper-noun stripping was the default behavior of the teacher pipeline). Third — and this is the most interesting reason — it turns the question of whether trained-on-descriptors behavior can develop name-like properties (rigid designation, opaque-context substitution, cross-context identity tracking) into an *empirical post-training test* rather than an architectural assumption. We do not hard-code a separate token class for names. We let the model see only descriptions and ask what it learns.

Whether the descriptors come to behave like rigid designators in the Kripkean sense (Kripke 1972) is the *Reasoner-side* counterpart to the inferentialism question raised by the prompt-attention deficit. We return to this in §5.2 and develop it more fully in a companion paper.

[stub: cite Kripke 1972, Donnellan 1966, Brandom 1994 ch. 6, Frege 1892; outline the name-recovery experiment as the operational test.]

### 3.2 Corpus

[stub: teacher ensemble (gpt-oss-120b + gemma-4-26b via MindRouter); 1.96M traces; content-type taxonomy (concept_explanation, socratic_dialogue, chain_of_thought, thought_experiment, argument_analysis, analogical_analysis, conditional_analysis, counterexample_analysis); compliance rate ~99% post April-10 prompt fixes.]

### 3.3 Model and training

[stub: 200M-param decoder; pretrain 100K steps; SFT 30K steps; final val_loss 0.74.]

### 3.4 Evaluation

[stub: four-dim rubric (engagement, coherence, substance, expressive_adequacy), 0–4 anchored; benchmarks — 170-item holdout, 30-item stress, 115-item textbook; judge = parallel Claude subagents, calibration pending.]

---

## 4. Results

[stub: ~3 pages, tables + bar charts ported from `eval/results/may7_full_report.md` and the RCDS presentation.]

### 4.1 Within-distribution: Layer-3 holdout

[stub: the main table — Reasoner vs Comparator on (170 items, four dimensions). Reasoner−Comparator deltas: engagement −1.53, coherence −0.43, substance −0.41, expressive_adequacy −0.38. Three of four dimensions within 0.5. Reasoner *wins* substance on three content types.]

### 4.2 Out-of-distribution: Layer-4 stress

[stub: Comparator D4 by category — use_mention 3.67, counterfactual 3.33, … modal/supervenience/abstract_objects/self_reference all ~2.67. UGF strains modestly on these; nothing breaks. Reasoner engagement collapses to 0.13. Distinguish *vocabulary* limit (Comparator's drop) from *model* limit (Reasoner's collapse).]

### 4.3 The split finding

[stub: two findings, separable.]

---

## 5. Discussion

### 5.1 Two questions, two answers

[stub: pivot paragraph. The clean headline ("small model, restricted vocabulary, near-teacher reasoning") is wrong: the question is not one question but two. (1) Is UGF expressively adequate? Answer: yes, within calibrated limits we map in §4.2. (2) Did our Reasoner learn philosophical reasoning *in UGF*? Answer: on within-distribution prompts, recognizably yes; on out-of-distribution prompts, no — and the failure mode is specific and characterizable.]

### 5.2 An inferentialist reading

The prompt-attention deficit is the most original empirical finding of this paper, and it admits a philosophical reading worth developing. **Inferentialism** — the view, defended by Sellars (1956) and Brandom (1994), that conceptual content is constituted by inferential role rather than by lexical label — has been mostly an armchair commitment. Empirical tests are scarce, because we cannot ordinarily strip away vocabulary without also stripping away the inferential structure attached to it. Our setup gives us such a test, almost by accident: the teacher writes *in UGF* but retains full inferential machinery, and the student model inherits inferential structure expressed in radically compressed vocabulary. The question is whether the inference survives the compression.

On within-distribution prompts, it does. The 200M model produces UGF whose inferential moves the judge rates as recognizable philosophical content: a thesis is stated, examples are deployed, counterexamples are considered, conclusions are drawn. The vocabulary is doing real inferential work, not just labeling. So far, inferentialism's first-pass prediction is vindicated.

But the deficit is the interesting part. On out-of-distribution prompts the model produces fluent, structurally-correct UGF that fails to engage what was actually asked. The inferential machinery runs; the input-recognition layer does not. We take this as a partial vindication of inferentialism, with an important caveat: inferential role gives you the content of the moves *internal* to reasoning, but it does not, by itself, fix how an agent reads a prompt as a *call for* particular inferences. Prompt-attention is a separate cognitive capacity, and our model has a fully functional inferential interior with a defective input-recognition layer.

Two readings of this fact suggest themselves. On the mild reading, the deficit is an engineering artifact of training-distribution narrowness — fixable, irrelevant to the theory. On the strong reading, the deficit reveals a lacuna in inferentialism as usually stated: the theory does not specify a mechanism by which an agent identifies the inferential demand of a particular input, and our data show that this is an empirically consequential gap. The mild and strong readings make different predictions about engineering follow-ups, and we treat the question of which is correct as open. A fuller development of this argument appears in a companion paper (`docs/followups/inferentialism.md`).

[stub: optional final sentence pulling the discussion back to the practical philosophical reasoning audience.]

### 5.3 Limitations

[stub: single judge family, calibration pending; single domain; single (size, vocabulary) point; chatbot pipeline degenerate as a separate workstream. Be honest. Avoid grand claims.]

---

## 6. Future work

The compression-v1 result is one data point in three directions of inquiry. Each direction has a skeleton paper already drafted as a followup; we summarize the program here.

**Vocabulary × parameter scaling.** A 2D scan over {~50M, ~200M, ~1B} × {1K-UGF, ~5K Basic English/Globish, ~50K standard tokenizer} would let us extract iso-performance curves in the (params, vocab) plane and test, empirically, whether vocabulary structure substitutes for parameters in a regular way. Compression-v1 is one cell of this grid; eight remain. The expected output is a substitutability claim: "a model with vocabulary V<sub>1</sub> and parameter count p performs as a model with vocabulary V<sub>2</sub> and parameter count p′ on this task, where p′/p depends on the structural properties of V<sub>1</sub>/V<sub>2</sub>." Such a result speaks to scaling-law work (Kaplan et al.; Hoffmann et al.) and to interpretability work on vocabulary-as-compression simultaneously. See `docs/followups/scaling.md`.

**Minimal sufficient vocabularies for other cognitive domains.** UGF-philosophy is one instance of a more general question: for each cognitive domain D, what is the smallest vocabulary V<sub>D</sub> such that D's signature inferences are still expressible? Mathematical reasoning, legal reasoning, and scientific explanation are natural next replications; each has an existing controlled-vocabulary candidate (intro-textbook headwords for math; Plain English Legal Glossary for law; VOA Special English for science). After two or three domains the project takes on a theoretical layer: what features of a vocabulary — polysemy coverage, compositional structure, closure under definition — make it expressively complete for a domain? This is the Sheffer-stroke program for cognition, and compression-v1 is its first data point. See `docs/followups/sheffer.md`.

**An inferentialist reading, developed.** The argument in §5.2 deserves a longer treatment in a philosophy venue. The compression-v1 data are, to our knowledge, the first vocabulary-stripping empirical test of inferentialism; the prompt-attention deficit identifies a specific frontier (input-recognition as a separate capacity from inferential role) where the theory needs supplementation. The followup paper develops this argument for an analytic philosophy audience and proposes a programmatic distinction between *internal* and *recognitional* components of conceptual content. A second pillar of the same paper tests inferentialism's reach to singular terms: do the UGF-descriptor stand-ins for names (§3.1a) come to behave like rigid designators, or do they remain merely predicational? Brandom's *Making It Explicit* ch. 6 argues that singular-term content reduces to substitutional-inferential role; our descriptor-only training provides an empirical purchase. No new compute; all data are in hand. See `docs/followups/inferentialism.md`.

These three directions are not mutually exclusive. The empirical scaling program and the multi-domain program share infrastructure: the 2D scan is naturally extended to a 3D scan over (params, vocab, domain). The philosophical paper rides on the data of all three. The shared anchor in every direction is the compression-v1 methodology and result.

---

## 7. Conclusion

[stub: end with honest open questions, not grand claims. Likely points to make: (1) the answer to the title question is "yes, within calibrated limits, and the limits are interesting"; (2) the prompt-attention deficit is the more original empirical finding and deserves its own treatment; (3) the methodology generalizes, and the three directions sketched in §6 each carry the project forward without requiring any of the others. A small contribution; much remains.]

---

## References

[stub: assemble from `docs/followups/*.md` and from the project's reading list. Key entries to include:]

- Brandom, R. (1994). *Making It Explicit*. Harvard University Press.
- Sellars, W. (1956). "Empiricism and the Philosophy of Mind." *Minnesota Studies in the Philosophy of Science* 1: 253–329.
- McDowell, J. (1994). *Mind and World*. Harvard University Press.
- Munroe, R. (2015). *Thing Explainer*. Houghton Mifflin Harcourt.
- Ramji, K. et al. (2026). "Thinking Without Words." (Layer-3 abstract-CoT compression paper; see `memory/abstract_cot_paper.md`.)
- Kaplan, J. et al. (2020). "Scaling Laws for Neural Language Models." arXiv:2001.08361.
- Hoffmann, J. et al. (2022). "Training Compute-Optimal Large Language Models." arXiv:2203.15556.
- [stub: complete bibliography in final draft.]
