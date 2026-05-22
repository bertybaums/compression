---
title: Structured-outputs probe results on MindRouter
author: Bert Baumgaertner
date: May 13, 2026
audience: MindRouter admin
---

# Structured-outputs probe results on MindRouter

## Summary

We empirically tested `response_format` (OpenAI-compatible structured outputs)
on `openai/gpt-oss-120b` via the MindRouter chat-completions endpoint with
the aim of using JSON-schema `pattern` regex enforcement to constrain
model output to our ~3,600-word Up Goer Five (UGF) vocabulary. The
mechanism works correctly for small/medium alternation patterns
(~500 word alternation, ≤14K char regex) but **silently fails for larger
patterns**: at ≥1,000 word alternation (≥29K char regex) the server
returns natural unconstrained output as if no `pattern` had been
supplied — no 4xx/5xx, no warning, no fallback indication. The compiled
regex appears to be discarded above some threshold; we have not been
able to determine that threshold precisely from the client side.

vLLM-specific extension parameters (`guided_regex`, `guided_grammar`)
appear to be filtered by the OpenAI-compat layer and do not reach the
backend, so we cannot work around the JSON-schema-pattern path.

This document collects the probe payloads and observed responses so the
admin can reproduce. We also have specific questions at the end.

## Context

The compression project trains a small-model pipeline that converts
between natural English and a ~1,000-word restricted-English vocabulary
("Up Goer Five"). The translator direction (English → UGF) is currently
served by a fine-tuned T5-small. We want to test whether a strong base
model + a hard structured-output constraint can match or beat the
trained translator without training.

The mechanism we wanted to use:

```jsonc
{
  "model": "openai/gpt-oss-120b",
  "messages": [...],
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "answer",
      "schema": {
        "type": "object",
        "properties": {
          "answer": { "type": "string", "pattern": "<UGF regex>" }
        },
        "required": ["answer"]
      }
    }
  }
}
```

where `<UGF regex>` is an alternation over the ~3,616 UGF inflected
forms (plus capitalized variants and whitespace/punctuation). The
expectation is that the server enforces the pattern during decoding,
so the model is forced to find a UGF-compliant rendering of its
intended answer.

## Probe sequence

All requests are POST `https://mindrouter.uidaho.edu/v1/chat/completions`
from the fortyfive login node. Common parameters across probes:
`reasoning_effort: "low"`, `max_tokens: 1500–3000`, single non-streaming
request.

### Probe 1 — `response_format: {type: "json_object"}` ✅ works

Request body (abbreviated):

```json
{
  "model": "openai/gpt-oss-120b",
  "messages": [{"role":"user","content":"Reply with a JSON object containing a key called color whose value is the string blue."}],
  "response_format": {"type": "json_object"},
  "max_tokens": 80
}
```

Observed (id `8d725679-…`):

```json
{
  "role": "assistant",
  "content": "{\n  \"color\": \"blue\"\n}",
  "finish_reason": "stop"
}
```

Conclusion: simple JSON-object mode works as documented.

### Probe 2 — `response_format: {type: "json_schema"}` (no pattern) ✅ works

Schema requires an object with a `color` string field. The model returns
JSON conforming to the schema. Equivalent to probe 1 in effect; just
confirms `json_schema` mode is accepted.

### Probe 3 — `pattern: "^[A-Z]+$"` on a question begging for a digit ✅ enforced

```json
{
  "model": "openai/gpt-oss-120b",
  "messages": [{"role":"user","content":"What is 2 plus 2? Reply with JSON."}],
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "answer",
      "schema": {
        "type": "object",
        "properties": {"value": {"type": "string", "pattern": "^[A-Z]+$"}},
        "required": ["value"]
      }
    }
  },
  "max_tokens": 2000,
  "reasoning_effort": "low"
}
```

Observed:

```json
{
  "content": "{\n  \"value\":  \"IUPMIRUUGVLMJMPXUSYPNMXOFGPKSKOOOQCKYYQHFNZOFPGFKLHBVFLPDIRFRFCVQHZNRRSMNQQQLMQQP\"\n}",
  "finish_reason": "stop"
}
```

The pattern is correctly enforced: the model wanted to say `4` but was
forced to emit only uppercase letters and produced gibberish that
satisfies the regex. This is the behavior we want at scale.

Note: an earlier version of this probe used `max_tokens: 80` and the
server returned:

```json
{"detail":"Structured output was requested but the model's reasoning/thinking
 consumed the entire token budget before generating content. Increase
 max_tokens or use a lower reasoning_effort."}
```

This is a useful and well-documented failure mode for tight-constraint
+ thinking-mode interactions. Raising `max_tokens` to 1500–3000 was
sufficient.

### Probe 4 — 157-word custom alternation (1,395 char regex) ✅ enforced

A small alternation of ~80 common English words (with capitalized
variants → 157 alternatives). Prompt: *"What color is the sky during
the day? Reply with JSON."*

Observed: `{"answer": "The sky is blue."}` — every word in the
alternation, sensible answer. Cannot distinguish enforcement from
fortunate model output on this probe alone, but combined with probe 3
the mechanism is clearly working.

### Probe 5 — full UGF alternation (3,616 words → 100K char regex), first attempt ❌ 502

Initial pattern included `[ \n]` (newline in character class):

```
^(alt)(([ \n]|[.,;:!?\x27]+[ \n]?)(alt))*[ .,;:!?\n]*$
```

Response:

```json
{"detail":"All 3 backend attempts failed. Last error: Server error
 '500 Internal Server Error' for url
 'https://aspen1.hpc.uidaho.edu:8002/v1/chat/completions'"}
```

Reproduced with `aspen4.hpc.uidaho.edu:8002` on retry.

We suspect this was a pattern-format issue (the `\n` and/or `\x27`
escape interacting badly with the regex compiler), not a size issue
directly — the size sweep in probe 6 shows that a 100K-char pattern
with a different shape does *not* 500.

### Probe 6 — size sweep with corrected pattern shape

Pattern shape that did not trigger 500s:

```
^(alt)([ ,.;:!?]+(alt))*[ .,;:!?]*$
```

Where `alt` is `|`-separated UGF words plus capitalized variants. We
swept `n_words` from 200 to the full 3,616 and tested each constraint
on the same English-to-UGF translation prompt:

> *Rewrite using only the simplest English words. Preserve meaning.
> Reply JSON with field answer. Sentence: Alligators are on average
> larger than crocodiles.*

Out-of-pool leakage check: words like *alligators*, *crocodiles*,
*generally*, *normally* are not in our wordlist. If the pattern is
enforced, they cannot appear in the output.

| `n_words` | regex length | model output (truncated) | leaked words | enforced? |
|---:|---:|---|---|:---:|
| 500   |  14,331 | `All all, all, all.` | — | ✅ |
| 1,000 |  29,303 | `Alligators areusually biggerthan crocodiles.` | alligators, areusually, biggerthan, crocodiles | ❌ |
| 1,500 |  43,323 | `Alligators are generally biggerthan crocodiles.` | alligators, generally, biggerthan, crocodiles | ❌ |
| 2,000 |  57,011 | `Alligators are generally biggerthan crocodiles.` | alligators, generally, biggerthan, crocodiles | ❌ |
| 2,500 |  71,723 | `Alligators are normally biggerthan crocodiles.` | alligators, normally, biggerthan, crocodiles | ❌ |
| 3,000 |  86,303 | `Alligators are normally bigger at size compared a crocodiles.` | alligators, normally, compared, crocodiles | ❌ |
| 3,616 (full UGF) | 103,875 | `Alligators are usually bigger than crocodiles.` | alligators, crocodiles | ❌ |

The breakdown between 500 and 1,000 words is striking: at 500 the
constraint is enforced (the model produces "All all, all, all." —
clearly fighting the regex, accepting it, and emitting a degenerate
compliant string). At 1,000 and above the model produces natural
unconstrained English with words that are not in the alternation pool.

Two observations on the 1,000–3,000 range outputs:

1. Words like `areusually` and `biggerthan` suggest the model is being
   nudged toward compliance somehow — possibly partial enforcement
   that strips required whitespace — but the result is still not in
   the declared alternation.
2. At full vocabulary (3,616), the output is fully natural and almost
   identical to what the model produces with no constraint at all.

### Probe 7 — confirm enforcement-vs-leakage with a definitive test

```jsonc
{
  "pattern": "^(yes|no)$",
  "user_content": "What color is the sky? JSON."
}
```

Observed: `{"answer": "yes"}` — clearly enforced, the model picked the
constraint-satisfying option over the semantically natural one.

```jsonc
{
  "pattern": "^(are|usually|bigger|than|crocodile|crocodiles|the|is|sky|cat|dog|big|small)( (are|usually|bigger|than|crocodile|crocodiles|the|is|sky|cat|dog|big|small))*[.,]?$",
  "user_content": "Rewrite ... Alligators are on average larger than crocodiles."
}
```

Observed: `{"answer": "are usually bigger than crocodiles"}` — note the
absence of "alligators" (excluded from the pool), and the model dropped
the subject rather than violating the constraint. Definitive evidence
of enforcement at small pool sizes.

### Probe 8 — vLLM extension parameters

We tested whether `guided_regex` is accepted via three common locations:

```jsonc
{ ..., "guided_regex": "<full UGF regex>" }                       // top-level
{ ..., "nvext": { "guided_regex": "<...>" } }                     // NVIDIA-style
{ ..., "extra_body": { "guided_regex": "<...>" } }                // explicit extra_body
```

All three returned identical unconstrained output to a baseline request
with no constraint at all. No errors, no acknowledgement; the
parameters appear to be silently filtered by the OpenAI-compat layer
before reaching the backend.

## Diagnosis

The most likely failure mode, given the silent-fall-through behavior:

1. MR / vLLM receives the JSON schema with a `pattern` field.
2. The constraint compiler (likely xgrammar or outlines) attempts to
   compile the regex into a finite-state automaton over the model's
   tokenizer.
3. Compilation either times out or exceeds a memory budget for large
   alternations.
4. The error is caught silently and decoding proceeds without the
   constraint.

A 3,616-element alternation compiles to a trie with ~10K transitions;
tokenizer-aware compilation multiplies this by per-token branching
factor. This is well within published xgrammar working ranges, but the
specific configuration MR is running may have a tighter compile budget,
a different compiler, or no FSA caching across requests.

Two observations support this diagnosis:

- The 1,000-word regex appears to be *partially* respected ("areusually",
  "biggerthan" look like normalization artifacts that could come from a
  partially-compiled DFA). This suggests compilation is starting and
  bailing out partway through, not skipped entirely.
- vLLM's native `guided_grammar` parameter (which compiles a GBNF trie
  much more efficiently than alternation-regex) is not exposed.

## Questions for the admin

1. **What is the configured regex compile budget** (time and/or
   memory) for `response_format` patterns on the gpt-oss-120b
   deployment? We can adapt to a stated limit, but the silent fallback
   makes it impossible to detect from the client.
2. **Would it be feasible to surface a hard error** when constraint
   compilation fails, rather than falling back to unconstrained
   decoding? Even a 400-class error with `detail: "pattern too complex
   to compile"` would let us trim the vocabulary or split the request.
3. **Is `guided_grammar` / `guided_regex` available** through any
   request shape (top-level, extra body, nvext, or a custom field)?
   A GBNF grammar built as a trie over our ~3,600 words compiles to a
   much smaller FSA than the equivalent alternation regex and would
   likely fit any reasonable budget.
4. **What inference engine and version** is currently serving
   gpt-oss-120b's structured-output requests? If it's recent vLLM
   (≥ 0.6) with xgrammar, the upstream constraint engine should handle
   our scale; that would point to a gateway-level limit.
5. **For our use case specifically** — a single-shot translation call
   with a fixed wordlist, repeated O(thousands) of times — would
   prewarming or caching the compiled DFA be possible? The wordlist
   is identical across every call.

Reproduction scripts (the eight probes above) live in this repository
on the `main` branch; happy to package them as a single self-contained
script if useful. Estimated total cost of the probes that produced
this report: ~30 API calls, mostly small.

Thank you — and apologies for the load these probes put on the
backend, particularly the 502s on probes 5 and 6 early. Each probe
since has been a single call at `reasoning_effort: low`.

— Bert (compression project)
