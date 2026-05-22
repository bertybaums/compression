---
title: Reasoner SFT v2 design — purist think-answer architecture
date: May 18, 2026
audience: project + future paper
status: design, not yet implemented
---

# Reasoner SFT v2 — design document

## Why we are reversing course on v1 SFT

The v1 SFT recipe was designed before three findings reframed what the
Reasoner needs to learn:

1. **May 5 — Layer-3 holdout**: D4 (expressive adequacy) ≥ 3. The *language*
   is adequate. UGF can carry the content of philosophical answers.
2. **May 7 — Layer-4 stress**: D1 (engagement) = 0.13. The *model* produces
   fluent off-topic UGF essays on OOD prompts. The deficit is not in the
   vocabulary; it is in the model's failure to plan, attend to prompts, or
   reason its way to an answer.
3. **May 14 — target probe**: P4 (English-reason → translate to UGF) wins
   87.5% pairwise over P5 (UGF-native generation). At teacher scale, having
   explicit reasoning *structure* preceding the UGF output dominates having
   the right *vocabulary* of output. **The bottleneck is reasoning structure,
   not lexical choice.**
4. **May 18 — corpus audit**: v1 Reasoner is below its training corpus on
   every dimension (+1.78 engagement, +1.00 substance). The corpus has the
   signal; v1 SFT doesn't extract it.

v1 SFT trains *format anchoring* (5 fixed templates → fluent in-style
response, loss masked on prompt). Nothing in that loop teaches the model to
plan, iterate, or decide. The May-7 deficit is what that recipe produces.

## The v2 thesis

The project's expressive-adequacy claim has two parts that v1 conflated:

- **Language question**: can UGF carry the *content* of a philosophical
  answer? (Settled in the affirmative by May 5.)
- **Model question**: can a model trained only on UGF *reason its way to* a
  good answer? (Open. May 7 says no.)

v2 SFT splits these by training an explicit think → answer separation, so
that:

- The "thinking" segment is the reasoning-structure test (does the model
  plan in UGF?)
- The "answer" segment is the expressive-adequacy test (can the model render
  its conclusion in UGF?)
- Judging happens on the answer span; the thinking span is the
  internal-reasoning trace.

## The purist choice: UGF-phrasal markers instead of special tokens

### What we chose

**Single canonical asymmetric marker, made of pure UGF tokens.**

```
[prompt]
[reasoning, in plain UGF prose]
So my answer is:
[final answer, in plain UGF]
```

The phrase "So my answer is:" delimits the answer span. Everything before
it (after the prompt) is reasoning; everything after it is the answer. All
tokens in the marker are UGF: `so` + `my` + `answer` + `is` + `:` (the
colon is the only non-word UGF-allowed punctuation, already in the
tokenizer).

No new tokens. No tokenizer change. No re-pretrain.

### Why this is purer than the frontier-standard approach

Industry standard for reasoning models is special-token-bracketed thinking
(`<think>...</think>` in DeepSeek-R1, OpenAI o1, Anthropic extended-thinking,
etc.). Special tokens are non-vocabulary; they are control symbols outside
the language being tested.

For our project specifically, special tokens sidestep half the
expressive-adequacy question. The project claim is about whether
**~1K-word UGF is expressively adequate for philosophical reasoning**. If
the model needs four extra control tokens to organize that reasoning, we've
shown "UGF + 4 control tokens" is adequate, not "UGF" alone. The pure-UGF
phrasal-marker version tests **both** layers at once:

- Can UGF carry the *content* of reasoning? (the original question)
- Can UGF carry the *structural cues* that organize reasoning? (a deeper
  layer of expressive adequacy that special tokens sidestep entirely)

### Why frontier companies didn't do it this way — and why those reasons don't bind us

We deliberately depart from industry standard. The frontier reasons for
special tokens, classified by whether they apply to us:

**Do not apply (frontier reason → why it's null for us):**

| Frontier consideration | Why it doesn't bind |
|---|---|
| Multi-task collision — "So my answer is:" appears in pretrain text constantly as non-delimiter prose | We control the entire training distribution. The phrase can be reserved as a structural marker by construction in our generated corpus. |
| Trust / hiding — o1 and Anthropic extended-thinking deliberately hide reasoning from the user via a non-emittable boundary | We are not building a product. There is nothing to hide. |
| Adversarial robustness — natural-language delimiters are prompt-injectable; users could write "...and the answer is:" to manipulate parsing | Research benchmark, not user-facing. No adversarial input surface. |
| Industry tooling — vLLM, TGI, HF evals all assume special tokens for reasoning models | We write our own training, inference, and eval. No tooling pressure. |
| Multi-stage interleaving — frontier models interleave thinking and tool calls (`<think>...</think><tool>...</tool><think>...`) | Single-turn reasoning, no tools. The pure linear `prompt → reasoning → marker → answer` is sufficient. |

**Do apply, and how we mitigate / accept:**

1. **Embedding inductive bias.** A discrete `<think>` token has an embedding
   learned exclusively for "thinking-boundary" semantics. The phrase
   "So my answer is:" has embeddings already shaped by their natural
   pretrain use as informal conversational lead-in. The model must overcome
   this prior to repurpose them as structural delimiters.

   For us, this turns the frontier engineering objection into our actual
   research question. The phrasal-marker design explicitly tests whether the
   language can repurpose its own discourse markers as structural signals.
   Special tokens trivialize this question; we are running it.

2. **Loss / gradient targeting cleanliness.** Frontier setups can mask loss
   specifically on the special tokens. With phrasal markers we have to mask
   only the *specific positional occurrences* of the marker, not all
   occurrences of `so` / `my` / `answer` / `is` / `:` (which appear elsewhere
   in UGF reasoning). Doable but more bookkeeping in the data loader.

3. **Parse reliability at scale.** At frontier scale, 0.01% parse failures
   matter. At our scale, 1% is an annoyance. The model could emit
   "So, my answer is:" (extra comma) or "So the answer is:" (no "my") or
   doubled markers in long generations. We commit to a tolerance of ~99%
   parse-success in RL reward extraction; below that, we fall back.

### Fallback decision criterion

We commit *in advance* to the following fallback decision rule, so the call
is not rationalized mid-RL:

> If, after SFT v2 warm-up, the RL parse-failure rate on the answer-extraction
> regex exceeds 5% across a 200-prompt validation set, OR if the answer-span
> mean length is < 30 UGF words across that set, we add special tokens
> (`<think>`, `</think>`, `<answer>`, `</answer>`) and re-do SFT v2 with the
> token-bracketed format. We lose the strong claim about UGF's structural
> adequacy and document the negative result.

## Data pipeline

### Source data

- **Primary**: `corpus/processed/ugf_cot.jsonl` (100K records, 64,499
  compliant; schema: `prompt_text`, `reasoning`, `verdict` for logic /
  `conclusion` for philosophy, `compliant`).
- **Secondary** (open question — see below): the
  `chain_of_thought` slice of `corpus/processed/ugf_reasoning.jsonl`
  (proportion estimated ~20% × 1.96M ≈ 400K traces, ~95% compliant).

### Reformatting

For each compliant record in `ugf_cot.jsonl`:

```
[prompt = prompt_text]
[reasoning = reasoning]
So my answer is:
[answer = verdict | conclusion]
```

Joined as a single training sequence:

```
{prompt_text}\n{reasoning}\nSo my answer is:\n{answer}
```

For records from `ugf_reasoning.jsonl` (chain_of_thought subset), if we
include them, we need to split the existing `ugf_text` into reasoning and
answer spans. Two options:

- **Heuristic split**: take the last sentence (or last clause after
  "So" / "Therefore" / "This means") as the answer; everything before as
  reasoning.
- **Skip**: train SFT v2 on CoT corpus only; bring in reasoning later in v3.

I lean *skip*. CoT corpus alone gives us 64K compliant records that already
have a clean reasoning/answer split. Reasoning-corpus splitting introduces
noise.

### Loss masking

```
[prompt]           → masked (labels = -100), per v1 convention
[reasoning]        → trained
So my answer is:   → trained (the model learns to emit the marker)
[answer]           → trained
```

Train on the marker rather than masking it: we want the model to learn to
emit the transition phrase as part of its reasoning structure, not have it
injected. The single-canonical-marker convention (always exactly one
"So my answer is:" per sequence, always in the same position) keeps this
clean.

### Special handling

- **Sequence length**: pretrain checkpoint is `max_seq_len=512`. Some CoT
  traces will exceed this when combined with prompt + marker. We truncate
  the reasoning span (preserve prompt + marker + answer; chop reasoning
  from the middle if needed). Drop records where prompt + marker + answer
  alone exceeds 512.
- **Compliance filter**: only train on `compliant=true` records.
- **Marker placement validation**: confirm in the data loader that exactly
  one "So my answer is:" appears in each formatted sequence.

## Training config (SFT v2)

Start from `checkpoints/reasoner_pretrain_v1/final.pt` (not the v1-SFT
checkpoint). Reasons:

- Cleaner experimental control. We are testing the SFT v2 *recipe*, not
  stacking it on top of v1-SFT's recipe.
- Avoids potential interference from v1-SFT's format-anchoring weights
  if those work against the think-answer separation.
- v1-SFT remains on disk as a comparator if we want to A/B.

Proposed hyperparameters (mostly mirror v1-SFT for comparability):

| Param | v1-SFT | v2-SFT (proposed) | Notes |
|---|---|---|---|
| batch_size | 8 | 8 | Same |
| grad_accum | 8 (eff. 64) | 8 (eff. 64) | Same |
| max_lr | 5e-5 | 5e-5 | Same |
| warmup_steps | 500 | 500 | Same |
| max_steps | 30,000 | **20,000** | CoT corpus is smaller (~64K compliant); ~1.25 epochs at eff. batch 64 |
| eval_interval | 500 | 500 | Same |
| checkpoint_dir | reasoner_sft_v1 | **reasoner_sft_v2** | Strict separation |

## Eval plan

Two-phase eval — quick milestone check before committing to a long run:

1. **Milestone eval at step 5K**: generate on stress (30) + cx-patched (50)
   + holdout (170). Score with the same May-5 judge pipeline (4-dim,
   parallel subagents). Compare deltas against v1-SFT baseline.

2. **Final eval at step 20K**: same benchmarks. Headline question — does
   stress engagement close from 0.13 to ≥ 1.0?

Parse-success check at both milestones: regex-extract the answer span from
each generation. Report parse-failure rate (should be < 5% per the fallback
criterion).

## Success criteria

- **Primary**: stress engagement ≥ 1.0 (up from 0.13). Validates the
  hypothesis that explicit think-answer separation closes the prompt-attention
  deficit.
- **Regression guard**: holdout doesn't drop > 0.3 on any dimension. Confirms
  we're not paying a forgetting cost.
- **Parse reliability**: < 5% parse failure on answer extraction. Confirms
  phrasal markers are learnable.
- **Stretch**: holdout *improves* on engagement and substance. Would suggest
  v1-SFT was actively suboptimal, not merely insufficient.

## Open questions for review before launch

1. **CoT only, or CoT + reasoning-corpus chain_of_thought slice?** I lean
   CoT only for v2; bring in reasoning later if results warrant.
2. **Symmetric vs asymmetric marker**: confirmed asymmetric (single
   "So my answer is:" marker only).
3. **Marker exact phrasing**: confirmed "So my answer is:" with capital S.
4. **Eval cadence**: 5K milestone + 20K final, or more frequent (every 5K)?

## Out-of-scope (deferred to v3 or paper)

- Re-pretrain with the new CoT and forms corpora folded in. The audit
  suggested pretrain may be underfit; this experiment is downstream of
  that question.
- Forms-SFT for prompt-attention. Complementary signal but distinct from
  reasoning-structure. Likely a v3 follow-up.
- RL with the locked weighted reward. Comes after SFT v2 validates.

## Paper notes (drafted here for future use)

The methods section will say something like:

> "Following industry practice for reasoning models, we trained the
> Reasoner with explicit reasoning structure. We departed from the standard
> practice of bracketing reasoning with special tokens (e.g.,
> `<think>...</think>`); instead, we used a single UGF-native phrasal
> marker, 'So my answer is:', composed entirely of words already in the
> ~1,000-word UGF vocabulary. This design choice serves our central
> expressive-adequacy claim: a special-token bracketing would test whether
> UGF + four control tokens supports philosophical reasoning, while the
> phrasal-marker version tests whether UGF alone — including its capacity
> to structure its own reasoning — is adequate.
>
> Frontier reasons for adopting special tokens (multi-task pretrain
> collision, hidden-reasoning UX, adversarial robustness, tooling
> compatibility, multi-stage tool interleaving) do not apply to our
> single-turn research setup. The remaining concerns (embedding inductive
> bias and loss-mask cleanliness) are explicitly part of what we test.
> We commit *a priori* to a fallback: if the SFT model fails to learn
> reliable marker placement (parse-failure > 5%), we add special tokens
> and document the negative result."
