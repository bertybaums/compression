# Layer-2 evaluation: summary across two benchmarks

_Generated May 5, 2026._

This document explains why the project evaluates the SFT Reasoner on **two benchmarks that measure different things**, summarizes headline numbers from each, and links to the detailed reports.

## The two benchmarks measure different things

### Textbook benchmark (`logic_textbook_bench.jsonl`, 115 items)

**Question it answers:** if a student types a plain English logic-textbook question into the chatbot, can the *full pipeline* produce a useful answer?

**What it stresses:**
- The **whole user-facing system**: English in, English out
- Translator(English → UGF) on out-of-distribution input (proper nouns, technical phrasing)
- Reasoner on prompts whose *content* is in distribution but whose *form* (wrapped in CONTENT_TYPES around a translated query) is slightly off-distribution
- Translator(UGF → English) on Reasoner output

**Pipeline:**
> English question → Translator(En→UGF) → wrap in CONTENT_TYPES template → SFT Reasoner → UGF response → Translator(UGF→En) → English response

### Holdout benchmark (`holdout_bench.jsonl`, 170 items)

**Question it answers:** if we feed the Reasoner exactly the kind of prompt it was trained on, does it produce something teacher-quality?

**What it stresses:**
- The **Reasoner alone**, isolated from Translator-induced distribution shift
- Whether the Reasoner has internalized the teacher distribution well enough to reproduce equivalent traces on *held-out* topics

**Pipeline:**
> (already-formatted prompt from corpus) → SFT Reasoner → UGF response → Translator(UGF→En) → English response

The Translator(En → UGF) step is *skipped* (`--skip-translate-en2ugf`) because holdout prompts are already in the corpus prompt format.

### Why the two together is informative

The benchmarks decompose the Reasoner-vs-pipeline question:

| holdout | textbook | implication |
|---|---|---|
| strong | strong | full system works |
| **strong** | **weak** | **Reasoner is fine; chatbot pipeline is the bottleneck** |
| weak | strong | unlikely (Reasoner doesn't reproduce its training but works on harder input) |
| weak | weak | Reasoner needs more training |

What we observe falls in row 2.

## Headline numbers

| metric | Reasoner (textbook) | Comparator (textbook) | Reasoner (holdout) | Comparator (holdout) |
|---|---|---|---|---|
| n | 115 | 115 | 170 | 170 |
| Short responses (<20 words) | **8 (7.0%)** | 0 (0.0%) | **1 (0.6%)** | 0 (0.0%) |
| English response mean words | 159 | 175 | **204** | 180 |
| English response median words | 158 | 165 | 184 | 173 |
| UGF response mean words | 205 | 236 | 233 | 257 |
| Median per-item latency (s) | 7.8 | 6.9 | 7.1 | 7.8 |

**Key observation:** the Reasoner's failure rate drops from 7% → 0.6% when moving from the chatbot pipeline (textbook) to direct prompting (holdout). The Reasoner produces *more* English-side content than the comparator on holdout (204 vs 180 mean words), and *less* on textbook (159 vs 175). The 30+ word reduction in the textbook setting is consistent with truncated / short / off-topic Reasoner outputs that don't survive the round-trip through the Translator.

## Per-type holdout (Reasoner-side: where it shines)

The Reasoner produces meaningfully *longer* output than the comparator on its training-distribution prompts in:

| type | Reasoner mean words | Comparator mean words | difference |
|---|---|---|---|
| concept_explanation | **241** | 128 | +113 |
| socratic_dialogue | **212** | 154 | +58 |
| chain_of_thought | **146** | 98 | +48 |
| conditional_analysis | **201** | 166 | +35 |

It's roughly equal on `argument_analysis`, `thought_experiment`, and slightly behind on `analogical_analysis`, `counterexample_analysis`. Even the "behind" gaps are within 1 standard deviation of length variance.

## Implications for next steps

- The holdout result is encouraging: **the SFT Reasoner is doing approximately what we want** within its training distribution. It produces traces of comparable length and (qualitatively, from sample inspection) comparable structure to the gpt-oss-120b teacher under the same UGF system prompt.
- The textbook result identifies the **chatbot pipeline as the next thing to improve**, specifically:
  - Translator(English → UGF) on out-of-distribution natural-English questions (proper nouns lost, wording simplified)
  - Translator(UGF → English) hallucinating proper names ("Mara", "Lira", "Thorne") when given UGF that contains "the first person" / "the second person" patterns
  - The wrapping-then-Translator-then-Reasoner-then-Translator chain may compound minor distortions
- These are **fixable independently**: the Reasoner doesn't need re-training right now; the Translator and the prompt-formatting between Translator and Reasoner do.
- Layer 3 LLM-judge scoring (when we run it) will turn these length/short-rate observations into per-dimension rubric scores. The rubric (engagement, coherence, substance, expressive_adequacy) will pick up quality differences that length doesn't capture.

## Detailed reports

| file | what's in it |
|---|---|
| `eval/results/report_logic_textbook.html` | Interactive textbook-benchmark report (115 items, full pipeline detail per item, filters, search) |
| `eval/results/report_logic_textbook.md` | Markdown version of the textbook report |
| `eval/results/report_holdout.html` | Interactive holdout-benchmark report (170 items, full pipeline detail per item, filters, search) |
| `eval/results/report_holdout.md` | Markdown version of the holdout report |
| `eval/results/eval_summary.md` | This file |

Both HTML reports are self-contained — open them in any browser, no server needed. Each has filter dropdowns (by type, "only short responses", free-text search) and per-type collapsible sections.
