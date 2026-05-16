---
title: Pickup list for next session
date: May 16, 2026
audience: future-Bert + future-Claude
---

# Pickup list — next session start

This is the authoritative "what to do first" list. Created at end of May 16 session.

## Read before doing anything

1. **`memory/session_status.md`** — current state, headline numbers, locked decisions.
2. **`memory/target_probe_rl_decision.md`** — the RL target + reward weighting decision and tradeoffs.
3. **This file** for the action queue.

## Critical-path actions (in order)

### 1. Verify CoT generation completed

Tmux session `cot` on fortyfive was at 90.2% (90,200/100,000) last checked May 14 16:11 PT. It should be done.

```bash
ssh fortyfive.hpc.uidaho.edu 'tmux ls; wc -l ~/compression/corpus/processed/ugf_cot.jsonl; tail -5 ~/compression/logs/cot_gen_latest.log'
```

Expected: ~100,000 records. Compliance ~73%, logic-accuracy ~90%. If the run died early, check the log and decide whether to restart for the remaining items.

### 2. Run Step 3 corpus audit

After CoT is verified complete:

```bash
# On fortyfive: pull CoT sample local first (sample is enough; full file is huge)
ssh fortyfive.hpc.uidaho.edu 'head -1000 ~/compression/corpus/processed/ugf_cot.jsonl > /tmp/cot_sample.jsonl; head -300 ~/compression/corpus/processed/ugf_forms_corpus.jsonl > /tmp/forms_sample.jsonl; head -3000 ~/compression/corpus/processed/ugf_reasoning.jsonl > /tmp/reasoning_sample.jsonl'
scp 'fortyfive.hpc.uidaho.edu:/tmp/cot_sample.jsonl' /tmp/
scp 'fortyfive.hpc.uidaho.edu:/tmp/forms_sample.jsonl' /tmp/
scp 'fortyfive.hpc.uidaho.edu:/tmp/reasoning_sample.jsonl' /tmp/

# Prep audit batches
python3 -m eval.prepare_corpus_audit_v2 \
  --existing-reasoning /tmp/reasoning_sample.jsonl \
  --forms /tmp/forms_sample.jsonl \
  --cot /tmp/cot_sample.jsonl \
  --n-per-corpus 300
```

Then dispatch parallel Claude subagents to score the batches against the Reasoner rubric (4-dim). Same pattern as May 13 head-to-head, with **opaque ids** — do NOT include the corpus label in the id field. (Lesson learned May 14.)

After all subagents complete, write/run an aggregator that gives per-corpus per-dimension means + comparison against the v1 Reasoner's own holdout scores. The headline question: **is corpus quality high enough that the v1 Reasoner is the bottleneck, or is the v1 Reasoner already at parity with its training data?**

### 3. Investigate the 18 P4 HTTP 422 errors

From the May 14 target-probe, these prompt ids triggered HTTP 422 from MR on the English-reasoning step:

```
probe-002, 003, 004, 009, 013, 016, 017, 018, 019, 024, 026, 029, 034, 035, 039, 046, 047, 049
```

Steps:
1. Look up those prompts in `eval/sets/cot_target_probe_50.jsonl`.
2. Inspect for shared structure (length, content_type, track, specific words).
3. Probe MR with one of them via curl to get the actual response body (not just HTTP code):

```bash
ssh fortyfive.hpc.uidaho.edu 'KEY=$(grep MINDROUTER_API_KEY ~/compression/.env | cut -d= -f2); curl -s -k -X POST -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" -d "{\"model\":\"openai/gpt-oss-120b\",\"messages\":[{\"role\":\"user\",\"content\":\"<failed prompt text>\"}],\"max_tokens\":4000,\"reasoning_effort\":\"medium\"}" https://mindrouter.uidaho.edu/v1/chat/completions | python3 -m json.tool'
```

4. If pattern is clear (e.g., a specific filter): adjust prompt format and re-run.
5. If pattern is unclear: bypass with gemma-4-26b as a fallback model for P4's English-reasoning step.
6. Re-run the failed prompts and update target-probe stats.

### 4. Investigate the P4 expressive_adequacy gap

P4 scored 2.84 on expressive_adequacy vs P5's 3.38 on the May 14 target-probe (with 5 translator retries). The translator's cruft is leaking through. Steps:

1. Audit the 27 compliant P4 references at `/tmp/cot_target_probe_p4_20260514_095547.jsonl` — what non-UGF words show up? (Wait, those were technically "compliant" — let me re-clarify: those 27 PASS the validator. The expressive_adequacy LOSS comes from judge perception of clunky paraphrases, not lexical violations per se. The 5 non-compliant P4 references DO have lexical issues.)
2. Re-run validate_ugf on all 32 with verbose output to see violation patterns on the 5 non-compliant.
3. Inspect the judge's `expressive_adequacy` justifications for the low-scoring P4 items — what specifically did the judge flag?
4. If common patterns emerge (specific stray words, awkward circumlocutions): add to translator's correction-prompt forbidden-word list.
5. Re-run target probe with tighter translator; check whether P4 expressive_adequacy closes toward P5's.

## After the critical-path: design the RL training loop

With the corpus quality audit, the 422 fix, and the expressive_adequacy probe complete, the next major work is designing the RL loop:

1. Reference generation: P4 references for all RL training prompts (filtered to compliant-only after the expressive_adequacy work). Generate offline, cache.
2. Compliance hard filter on Reasoner generations: reject any non-compliant rollout before reward computation.
3. Soft reward: the weighted combination locked in `memory/target_probe_rl_decision.md`:
   ```
   reward = 0.6 × substance + 0.2 × engagement + 0.1 × coherence + 0.1 × expressive_adequacy
   ```
   Per-rollout judge call against the Reasoner rubric.
4. RL algorithm choice: most likely GRPO or REINFORCE with SFT-mixing (per the Numerals project's lessons — see `Numerals/writeup.md` references in the project CLAUDE.md).
5. Per-dimension tracking at every RL checkpoint — recalibrate weights if any dimension collapses.

This is a big next phase. Approach it after the audit + the two open investigations land.

## Things still running on fortyfive at session end

- **tmux session `cot`** — should complete on its own; verify and then archive logs.
- Nothing else.

## Files that survive the session boundary (locations)

| Artefact | Path |
|---|---|
| Cached probe fixture | `eval/sets/cot_target_probe_50.jsonl` |
| Target-probe raw outputs (fortyfive) | `~/compression/eval/results/_jsonl/cot_target_probe_*_20260514_095547.jsonl` |
| Target-probe local copies | `/tmp/cot_target_probe_*.jsonl` |
| Target-probe judge inputs | `eval/judge_input_target_probe/` |
| Target-probe judge outputs | `eval/judge_output_target_probe/` |
| Target-probe aggregate | `eval/results/target_probe_aggregate.json` |
| Progress report | `docs/index.html` (live at https://bertybaums.github.io/compression/) |
| Admin probe writeup | `docs/mindrouter-structured-outputs-2026-05-13.md` |
| MR-based translator | `translator/mr_structured_translator.py` |
| Audit prep script | `eval/prepare_corpus_audit_v2.py` |

## Open task IDs at session end

#64 (Step 2c CoT generation runner) — in progress; mark completed once you verify the run completed.
#66 (Step 3 corpus audit) — pending; the next critical-path item.
#69 (Target-probe experiment) — in progress; mark completed once §18 ships and reward decision is locked (it's locked here).
Plus the two followups should be queued as new tasks at session start: P4 422 investigation, P4 expressive_adequacy probe.

Good luck.
