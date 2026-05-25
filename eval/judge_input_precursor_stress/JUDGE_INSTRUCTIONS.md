# Precursor judging — gold-English (P3) vs teacher-in-UGF

You are scoring single responses to philosophical/reasoning prompts on a
four-dimensional, anchored 0-4 rubric. Score each item independently.

## IMPORTANT — score content, not register
Some responses are written in unrestricted English. Others are written in a
restricted vocabulary of ~1000 common English words ("Up Goer Five"), so they
use circumlocutions ("the rules the world goes by" for "laws of physics").
Score the **reasoning content** — engagement, coherence, substance — on the
merits. Do NOT reward a response for sounding fluent/natural, and do NOT
penalize a response for using restricted vocabulary. A simply-worded response
that nails the question should outscore an eloquent one that drifts.

## Dimensions (0 / 2 / 4 anchored; interpolate 1 and 3)
- **engagement**: Does the response address the prompt's ACTUAL question?
  0 = wanders/restates/tangential; 2 = touches but misses the central ask;
  4 = engages the central question on its own terms.
- **coherence**: Internal logical consistency; each step follows from the prior.
  0 = self-contradictory/disconnected; 2 = mostly readable, sloppy steps/gaps;
  4 = connected chain, no contradictions.
- **substance**: Real philosophical work vs paraphrase (a counterexample, a
  traced analogy, a non-obvious distinction, what's at stake).
  0 = restatement/truisms; 2 = identifies a move but doesn't push it;
  4 = develops/advances the question.
- **expressive_adequacy**: Does the content come through cleanly, or does a
  vocabulary restriction visibly degrade it? **If the response is in
  unrestricted English, this dimension is N/A — report score -1.** For
  restricted-vocabulary responses: 0 = restriction breaks the argument;
  2 = restriction shows but point recoverable; 4 = reads as clean as English.

## Output — one JSON object per input id, as a JSONL list
For each item, output exactly:
{"id": "<the id>", "engagement": {"score": N, "justification": "..."},
 "coherence": {"score": N, "justification": "..."},
 "substance": {"score": N, "justification": "..."},
 "expressive_adequacy": {"score": N, "justification": "..."}}
Use score -1 for expressive_adequacy ONLY when the response is unrestricted English.
