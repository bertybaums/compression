---
title: Notes on MindRouter usage for the compression project
author: Bert Baumgaertner
date: April 16, 2026
audience: MindRouter admin
---

# Notes on MindRouter usage for the compression project

## What this project is doing

Distilling a small from-scratch model (1.5B params) from an ensemble of
teachers on MindRouter. The training corpus is synthetic — every token
originates from a MindRouter API call. Two pipelines:

1. **Parallel corpus (English ↔ Up Goer Five translation).** ~262K passages,
   already complete. Single-teacher (`openai/gpt-oss-120b`) with a validate-
   and-correct loop. 99.8% compliance on final output.
2. **Reasoning-trace corpus (pure Up Goer Five reasoning, 5 content types).**
   Target 200K–2M traces. Currently in progress, ~5K complete.

## Teacher mix (after 4-teacher pilot)

After a 50-trace-per-model pilot, we narrowed to two teachers:

| Teacher | Backends | Compliance | API reliability |
|---|---|---|---|
| `openai/gpt-oss-120b` | 6 | 92–98% | 0% fail up to 60 concurrent |
| `google/gemma-4-26b` | 2 (MoE) | 95–99% | 0% fail at 100 concurrent |

Dropped from the pilot due to low UGF compliance or API instability at
concurrency: `qwen/qwen3.5-122b` (verbose reasoning_content exhausts the
token budget, content=null ~95% of the time), `Nemotron-3-Super-120b`
(73% fail rate at concurrency 10, short outputs), `phi4-reasoning:14b`
(41% compliance), `magistral:24b` (26% compliance).

## Usage pattern

- Async Python (aiohttp) client on the `fortyfive` login node.
- Per-teacher semaphores cap concurrent requests.
- System prompt + 3-retry validate-and-correct loop per trace.
- Resume-safe progress file; kill-and-restart picks up where we left off.
- Runs in tmux on the login node (compute nodes have no internet).
- Thinking-token budget currently `generation.max_tokens + 12288` for
  gpt-oss-120b, `+ 8192` for gemma-4-26b.

## Throughput observations (April 16, 2026)

We've been scaling concurrency to probe the effective ceiling:

| Total concurrent | gpt-oss | gemma | Pattern | Traces/min | Notes |
|---|---|---|---|---|---|
| 50 | 30 | 20 | gather(batch=50) | 47 | baseline |
| 75 | 45 | 30 | gather(batch=100) | 56 | +20% for +50% conc. |
| 100 | 60 | 40 | gather(batch=100) | 69 | +24% for +33% conc. |
| 140 | 80 | 60 | gather(batch=100) | 94 | +36% for +40% conc., **7% fail on gpt-oss** |
| 160 | 60 | 100 | gather(batch=100) | 77 | 0% fail, but regressed |
| 160 | 60 | 100 | as_completed(200K tasks) | 47 | smooth tok/s (see below), total regressed |

Across all runs MindRouter itself showed no queue backup (per the
dashboard) and responded well. `gemma-4-26b` appears to scale linearly
and cleanly up to 100 concurrent — the MoE architecture seems to absorb
load better than `gpt-oss-120b`, which starts dropping calls (content=null
or timeouts) around 13 concurrent per backend.

## The interesting part: tok/s shape vs total throughput

When we switched from `asyncio.gather(batch=100)` to `asyncio.as_completed`
on the full 200K-task pool, the tok/s curve went from **oscillating**
(peaks during each batch's fan-out, valleys while the slowest call in
the batch blocked the next dispatch) to **smooth and constant**. But
total traces/minute regressed from ~77 to ~47.

Our read on this:

- Smooth tok/s confirms the batch-boundary tail-latency coupling is gone.
  Before, ~half the concurrency slots sat idle while the batch waited
  for its slowest call to finish. Now each slot is always working.
- Total regression is most likely **client-side**, not MindRouter-side:
  (1) `asyncio.as_completed` on 200K tasks is O(n) per completion to
  scan for ready futures (O(n²) total); (2) we `out_f.flush()` on every
  write, so fsync per trace instead of per batch.

Planned next step: replace `as_completed` with a producer-consumer
(`asyncio.Queue` + N workers per teacher, N = per-teacher concurrency).
That gives the decoupling benefit without the O(n²).

## Questions for the admin

1. **Are we close to a per-user ceiling we should be aware of?** We are
   pushing concurrency steadily and haven't seen 429s or queue buildup,
   but we don't know the actual WDRR bucket limits for our account and
   don't want to silently degrade priority for other users.
2. **Is `gpt-oss-120b` near its effective per-backend capacity at ~13
   concurrent requests, or is the failure mode we see at 80 concurrent
   caused by something else (e.g., thinking-mode token budget
   interactions)?**
3. **`Nemotron-3-Super-120b` worked reliably in isolation for us but
   failed on 73% of calls at concurrency 10.** Is Nemotron known to be
   sensitive to concurrency, or is this about a specific backend's
   health?
4. **`qwen/qwen3.5-122b` produced content=null on ~95% of calls** — its
   `reasoning_content` was extremely verbose (15+ self-deliberations
   even for trivial prompts). Is there a recommended max_tokens budget
   that avoids exhaustion, or a way to cap reasoning_content?
5. **Is there a recommended pattern for long-running high-volume batch
   jobs** (multiple teachers, 100+ concurrent, running for hours/days)?
   We're happy to adjust if there's a friendlier pattern — e.g.,
   scheduled windows, specific time-of-day preferences, or a signal
   we should watch to back off.

Thank you — please let me know if any of our observations contradict
what you see server-side, and if there's anything we should change.

— Bert (compression project)
