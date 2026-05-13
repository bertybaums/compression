# Translator output rubric (v1)

May 12, 2026

A four-dimensional 0–4 rubric used by an LLM judge to score the *quality of an
EN→UGF translation*. The translator's job is: given an English source
sentence, produce a UGF rewrite that preserves the meaning while using only
words from the ~1,000-word UGF vocabulary.

This is a different rubric from `rubric.md`, which scores *philosophical
reasoning quality* of Reasoner outputs. Here we are scoring *translation
fidelity and naturalness*.

## Scale

0 / 1 / 2 / 3 / 4. Anchored at 0, 2, and 4 — the judge interpolates 1 and 3.
Each dimension is scored independently, with a 1–2 sentence justification.

## Dimensions

### D1 — Meaning preservation
*Does the UGF rewrite convey the same propositional content as the English source?*

- **0:** Meaning is lost, garbled, or changed; the UGF says something materially different from the English. Includes cases where two distinct entities in the source collapse to one paraphrase (e.g. "alligator" and "crocodile" both rendered as the same UGF phrase).
- **2:** Core point is recoverable but with noticeable distortion — one important nuance dropped, one ambiguity introduced, or one technical term mapped to a vague-enough UGF phrase that recovery requires guessing.
- **4:** Meaning is preserved cleanly. A competent reader of the UGF could reconstruct the propositional content of the English source.

### D2 — Fluency
*Does the UGF read as natural simple-English prose, or does the constraint break the sentence?*

- **0:** The UGF is broken — fragments, looped repetition, ungrammatical strings, or impossible-to-parse word salad.
- **2:** Readable but strained — clunky paraphrases, awkward word choices, over-long circumlocutions for simple ideas.
- **4:** The UGF reads as natural simple English. A reader unaware of the source would not flag it as machine-generated or vocabulary-constrained.

### D3 — No fabrication
*Does the UGF add content, entities, or claims that are not in the English source?*

- **0:** Significant fabrication — invented names, invented examples, invented arguments, or content from elsewhere stitched in.
- **2:** Minor scaffolding artifacts (e.g. unprompted "Premises: 1." framing) or a small added qualifier, but no invented entities or claims.
- **4:** Output is faithful to the source — no additions, no inventions, no scaffolding the source did not request.

### D4 — Paraphrase sensibility
*When the English uses concepts UGF cannot directly name (e.g. "alligator", "reptile", "syllogism"), is the substituted phrase a sensible and informative paraphrase?*

This is the dimension that tests whether the model can do good *translation
reasoning* under the constraint — finding UGF phrases that distinguish the
concepts in question rather than collapsing them.

- **0:** Substitutions are nonsensical, factually wrong, or collapse distinctions. (E.g. "alligator" → "big sea animal that eats dead things" — alligators aren't sea animals and don't primarily eat carrion.)
- **2:** Substitutions are technically valid but lossy — they capture *some* aspect of the original concept while losing important features, or they make distinct concepts hard to tell apart.
- **4:** Substitutions are sensible, distinguishing, and informative — a reader could recover the original concept from the paraphrase or at least understand what kind of thing was meant.

## Judge output format (JSON, one per input item)

```json
{
  "id": "<item id>",
  "meaning_preservation":   {"score": 3, "justification": "..."},
  "fluency":                {"score": 4, "justification": "..."},
  "no_fabrication":         {"score": 2, "justification": "..."},
  "paraphrase_sensibility": {"score": 3, "justification": "..."},
  "notes": "optional cross-dimension observations"
}
```

## Operational rules

1. **Blinding.** Each judge agent sees only `{id, english_source, ugf_translation}` — no labels indicating which translator system produced the UGF. Comparison happens post-hoc on aggregated scores.
2. **Don't reward "more complete UGF".** A translation that *adds* useful explanation is committing fabrication (D3 < 4). Faithfulness to the source matters more than expansiveness.
3. **D4 is the project-relevant dimension.** If both translators score high on D1–D3 but the structured-output translator scores higher on D4, that's evidence the trained T5 was under-capacity for paraphrase reasoning, not that the vocabulary itself is inadequate.
