# Reasoner evaluation rubric (v1)

April 29, 2026

A four-dimensional, anchored 0–4 rubric used by an LLM judge to score Reasoner
generations against the same prompts answered by the primary comparator
(teacher-in-UGF, `openai/gpt-oss-120b` with the UGF system prompt).

The rubric is the centerpiece of Layer 3 of the eval plan (see
`docs/eval-plan.md` if/when written, or the project-memory entry
`eval_comparator_strategy.md`).

## Scale

0 / 1 / 2 / 3 / 4. Anchored at 0, 2, and 4 — the judge interpolates 1 and 3.
Each dimension is scored independently, with a 1–2 sentence justification.
Aggregation across dimensions is post-hoc, so we can re-weight without
re-running the judge.

## Dimensions

### D1 — Engagement
*Does the response address the prompt's actual question?*

- **0:** Wanders off, restates the prompt only, or addresses something tangential.
- **2:** Touches the question but misses the central ask — answers an adjacent or weaker version.
- **4:** Engages the prompt's central question on its own terms.

### D2 — Coherence
*Internal logical consistency. No self-contradiction; each step follows from prior.*

- **0:** Self-contradictory, or sequence of disconnected fragments.
- **2:** Mostly readable but with sloppy steps, gaps in reasoning, or one contradiction recoverable in context.
- **4:** Each move follows from the prior; no internal contradictions; readable as a connected chain of thought.

### D3 — Philosophical substance
*Does it do real work, or only paraphrase? Real work might be: developing a counterexample, following an analogy through, drawing a distinction the prompt didn't supply, identifying what's at stake.*

- **0:** Mere restatement; truisms; no work beyond paraphrase.
- **2:** Identifies a relevant case, distinction, or move but does not push it — gestures without follow-through.
- **4:** Substantive work — develops a counterexample, traces an analogy, surfaces a non-obvious distinction, or otherwise advances the question.

### D4 — Expressive adequacy under UGF
*Does the philosophical content come through cleanly, or does the vocabulary restriction visibly degrade the argument?*

This is the project-question dimension.

- **0:** Restriction breaks the argument — circumlocutions obscure the point, key distinctions collapse into ambiguous everyday words, or central concepts go unrendered. A reader needs a charitable reconstruction to recover what was meant.
- **2:** Restriction shows but the point is recoverable — clunky paraphrases, occasional ambiguity, but the core argument is readable on first pass.
- **4:** UGF use feels native; the philosophical point comes through as clearly as it would in unrestricted English.

**Reading guide for D4 results:**

- Reasoner and teacher-in-UGF both score high → UGF is expressively adequate; the small distilled model carries the teacher's reasoning ability.
- Both score low → UGF is the bottleneck (vocabulary inadequate for the prompts in question).
- Teacher-in-UGF scores high but Reasoner scores low → model-capacity or capacity-vs-derivation-length issue (Sheffer-stroke regime). Triggers consideration of the deferred 200M English-reasoning comparator.

## Judge output format (JSON)

```json
{
  "engagement":          {"score": 3, "justification": "..."},
  "coherence":           {"score": 4, "justification": "..."},
  "substance":           {"score": 2, "justification": "..."},
  "expressive_adequacy": {"score": 3, "justification": "..."},
  "notes": "optional cross-dimension observations"
}
```

## Operational rules

1. **Judge model is NOT one of our teachers.** gpt-oss-120b and gemma-4-26b are excluded (they'd score their own style favorably). Use external Claude (Opus 4.7 or Sonnet 4.6) via the Anthropic API.
2. **Blinding.** Reasoner and teacher-in-UGF responses scored independently (separate judge calls), not paired A/B. Comparison happens post-hoc on aggregated scores. Avoids label-bias.
3. **Length budget at inference.** Generous `max_new_tokens` for both systems. Track generation length distribution per system; a systematic length deficit on the Reasoner is a Sheffer-stroke-style tell.
4. **Inter-rater calibration.** Bert hand-rates 30–50 prompts blind. Compute Spearman ρ between Bert's scores and the judge's scores per dimension. Decision rule: ρ > 0.7 → judge is acceptable; ρ < 0.5 → redesign anchors.
