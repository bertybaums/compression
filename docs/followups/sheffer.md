# Followup: Minimal sufficient vocabularies for cognitive domains — a research program

**Date:** May 12, 2026
**Status:** skeleton — seeded from compression-v1
**Anchor in main paper:** Future Work §6 of `docs/paper-draft.md`
**Thread in memory:** I (with C as the in-domain English baseline)

---

## Thesis

For each cognitive domain D, there exists some minimal vocabulary V<sub>D</sub> such that a model trained over V<sub>D</sub> can perform the inferences signature to D. Compression-v1 gives evidence that V<sub>philosophy</sub> ≤ 1K UGF words. The program is to find the analogous minima for other domains, and eventually to characterize what *features* of a vocabulary make it "expressively complete" for a given kind of reasoning.

## The Sheffer-stroke analogy, fully unpacked

The Sheffer stroke (NAND) is functionally complete for classical propositional logic: every truth function on Boolean inputs can be expressed using only NAND. The vocabulary size is 1; the sentences get longer; nothing in propositional logic becomes inexpressible.

The natural-language version: given a cognitive domain, what is the smallest vocabulary V such that everything expressible in the full natural language about that domain is still expressible in V (possibly at the cost of longer sentences)? Compression-v1 takes one cognitive domain (practical philosophical reasoning) and one candidate V (Munroe's UGF) and asks whether the candidate works. The result is a partial yes — within calibrated limits.

The program generalizes: pick another D, pick a candidate V<sub>D</sub>, run the same methodology.

## Candidate domains and candidate vocabularies

| Domain D | Candidate vocabulary V<sub>D</sub> | Source |
|---|---|---|
| Mathematical reasoning (high-school / undergrad) | ~1K headwords from an intro-math textbook + numeric forms | Curated from open math textbooks; cross-check against Lakoff & Núñez 2000 |
| Legal reasoning | Plain-English Legal Glossary (~1500 words) | US Courts plain-language initiatives; UK Legal Aid simplified-language docs |
| Ethics-only | Subset of UGF tuned to moral vocabulary | Derive from compression-v1 corpus by filtering for normative-content traces |
| Scientific explanation | Voice of America Special English (~1500 words) | VOA Learning English archive |

Each candidate has a defensible provenance — none invented from scratch. The methodology is to *test* candidates, not to invent them.

## Three phases

### Phase 1 — Replication

Pick one second domain (likely math, because corpora are most available). Replicate compression-v1 methodology end to end: teacher distillation, ~200M from-scratch model with custom tokenizer, four-dim rubric eval. Compare against a same-size, same-corpus full-vocabulary baseline (this is essentially thread C generalized).

**Expected effort:** ~3 months. Most of the cost is corpus generation; training and eval are mostly automated.

### Phase 2 — Cross-domain transfer

Once two domains are done, ask: does the UGF-philosophy Reasoner generalize to math word problems? Where exactly does it fail? Conversely, does the math-vocabulary Reasoner generalize to ethics?

This phase is the cheap one — no new training, just eval re-runs across domains.

**Expected output:** a transferability matrix. Cells show how each (model, vocabulary) pair scores on each domain's eval.

### Phase 3 — Theory

After three or four domains, ask the abstract question: what *features* of a vocabulary make it expressively complete for a domain D? Candidate features:

- **Coverage of polysemy.** Does V<sub>D</sub> contain enough words to disambiguate the senses needed in D?
- **Compositional structure.** Does V<sub>D</sub> contain the productive morphology / syntactic frames that D's inferences require?
- **Frequency profile.** Is V<sub>D</sub> Zipf-shaped over D's actual content, or uniformly distributed?
- **Closure under definition.** Can every D-content word *outside* V<sub>D</sub> be defined using only V<sub>D</sub>?

Phase 3 is the theoretical payoff and the natural home for cross-domain comparative work.

## Venue candidates

- *Cognition*, *Cognitive Science*, *Mind* — for phase-1 and phase-2 papers framed as cognitive-science contributions.
- *Topics in Cognitive Science* — for the cross-domain phase.
- AGI conference, *Philosophical Studies*, *Synthese* — for phase 3 if framed theoretically.
- Standalone book chapters or a monograph at the program's mature stage.

## Compute estimate

Phase 1 alone: ~3 months and ~$X in compute. Equivalent to running a fresh compression-v1 on a new domain. Each subsequent domain marginally cheaper as tooling matures.

## Dependencies

- **Thread G (compression-v1 paper)** — establishes the methodology and the proof-of-concept that the program rests on. Phase 1 starts after G is in submission.
- **Thread B (prompt-attention diagnosis)** — if the deficit is corpus-driven rather than vocabulary-driven, the same fix needs to apply to each phase-1 domain replication. Don't replicate a bug.
- **Thread A (judge calibration)** — the rubric travels across domains; calibration needs to as well.

## Why it matters

Turns one paper into a research program with a 5–10 year horizon. Positions compression-v1 not as an ML curiosity but as the first data point in a generalizable cognitive-science project. The Sheffer-stroke framing has a clear elevator pitch and bridges philosophy of language, cognitive science, and ML — three fields that rarely cite each other.

## What to write into paper G's Future Work

> **Minimal sufficient vocabularies for other cognitive domains.** UGF-philosophy is one instance of a generalizable question: for each domain D, what is the smallest vocabulary V<sub>D</sub> such that D's signature inferences are still expressible? Mathematical reasoning, legal reasoning, and scientific explanation are natural next replications. Eventually the project becomes characterizing the features of V<sub>D</sub> that make a vocabulary expressively complete for a domain.
