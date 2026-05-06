# Layer-4 stress benchmark — `stress_bench.jsonl`

Created May 6, 2026.

## Purpose

Tests UGF's expressive limits on philosophical concepts that are *intentionally
hard* to render in ~1000 common words. The point is to find:

- **Concepts UGF can't carry at all** (D4 → 0): vocabulary genuinely insufficient.
- **Concepts UGF carries with significant loss** (D4 → 2): meaning recoverable but degraded.
- **Concepts UGF surprisingly handles fine** (D4 → 4): the project's positive thesis vindicated.

This complements the holdout (which tests on training-distribution prompts) and
the textbook (which tests the chatbot pipeline). Together: holdout = capability,
textbook = pipeline, stress = expressive ceiling.

## Schema

Each item:

```json
{
  "id": "stress-{category}-{seq}",
  "type": "stress_<category>",
  "category": "<one of 10>",
  "instruction": "",
  "question": "<English prompt>",
  "english_query": "<same English prompt, for runner compatibility>",
  "ugf_query": "<hand-translated UGF version, for --skip-translate-en2ugf runs>",
  "difficulty_note": "<why this is UGF-hard>",
  "expected_difficulty": 1-5
}
```

`ugf_query` is **hand-translated** (not auto-translated) to eliminate
Translator(En→UGF) noise from the eval. Use the `--skip-translate-en2ugf`
flag in `run_logic_bench.py` and feed `ugf_query` to the Reasoner.

## Categories (3 items each, 30 total)

| category                     | what it stresses                                                |
|------------------------------|-----------------------------------------------------------------|
| `modal`                      | necessity / possibility / contingency, possible worlds          |
| `deontic`                    | obligation / permission / supererogation                        |
| `supervenience`              | abstract dependence (mental on physical, moral on natural)      |
| `use_mention`                | the meta-linguistic distinction                                 |
| `intensional_contexts`       | substitutivity failure under propositional attitudes            |
| `self_reference`             | Liar, Russell, Grelling                                         |
| `vagueness_sorites`          | heap paradox, gradable predicates, truth-value gaps             |
| `counterfactual_disposition` | counterfactual conditionals, dispositional properties           |
| `abstract_objects`           | universals vs particulars, types vs tokens                      |
| `phenomenal_qualia`          | hard problem, Mary's room, inverted qualia                      |

Difficulty 3 (n=14): paraphraseable but meaning at risk.
Difficulty 4 (n=16): meaning likely degraded; tests UGF's ceiling.

## Running

Same protocol as holdout (already-formatted UGF queries):

```bash
# Reasoner (on fortyfive)
python -m eval.run_logic_bench \
  --bench eval/sets/stress_bench.jsonl \
  --skip-translate-en2ugf \
  --output eval/results/stress_bench_reasoner.jsonl

# Comparator (locally via MR)
python eval/run_comparator.py \
  --bench eval/sets/stress_bench.jsonl \
  --output eval/results/stress_bench_comparator.jsonl

# Judge: same parallel-subagent pattern as Layer-3.
# Add stress_bench to eval/prepare_judge_batches.py SOURCES,
# rerun batch prep, dispatch agents, aggregate.
```

## What we hope to learn

The judge's `expressive_adequacy` (D4) score per category will give us a
heatmap: which concept families is UGF actually inadequate for? If D4
stays ≥ 3 across most categories, the project's positive thesis is
strongly vindicated. If it drops sharply for (e.g.) modal and intensional
contexts, we have a calibrated map of UGF's real limits — which is itself
a publishable result.

We expect lowest D4 on: `intensional_contexts`, `modal`, `phenomenal_qualia`,
`use_mention`. Highest expected D4 on: `vagueness_sorites`,
`counterfactual_disposition`, `deontic`. These predictions are worth
testing against actual judge scores.
