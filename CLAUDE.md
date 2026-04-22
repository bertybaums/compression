# Compression project — Claude Code notes

One-line mission: **Test whether Up Goer Five (~1K-word restricted English) is expressively adequate for practical philosophical reasoning**, by training a 1.5B-param from-scratch Reasoner on a pure-UGF corpus. See `~/.claude/projects/-Users-bbaum-Documents--RCDS-compression/memory/project_overview.md` for the fuller framing.

---

## MindRouter (MR) rate strategy — READ THIS BEFORE RUNNING ANY GENERATION

The hardest-won engineering lesson on this project. Getting MR rate-limiting right took several painful iterations on April 17, 2026. Don't relitigate those.

### The enforced cap
- **MR enforces 200 req/min per account** (admin-set, confirmed April 17). Not globally shared — it's our account's budget.
- **No per-account token quota** as of April 17 (the earlier "Token quota exceeded" wall was lifted by admin).
- Thinking-mode tokens (e.g. gpt-oss-120b's reasoning budget) are "free" in the sense that they don't cost quota — only req/min matters.

### Our self-imposed cap (the actual knob)
- Set in `corpus/generation/config.yaml` under `mindrouter.max_req_per_minute`.
- **Default on `main` branch: 100.** Operational setting on fortyfive (uncommitted): **200.** Leave it at 200 unless you have reason to go lower.
- `mindrouter.burst_capacity: 10` — allows a small initial burst before steady-rate enforcement.

### The client-side token-bucket rate limiter (`AsyncTokenBucket`)
Located in `corpus/generation/generate_reasoning.py`. Process-global, shared across ALL teacher workers. Every outgoing API call — including retries — acquires a token before firing. This is critical because:

- 429 responses return in ~200ms (MR does no LLM work to reject).
- Without the limiter, retries fire immediately on 429, amplifying outgoing rate 2–5× over the per-worker success-path rate.
- That amplification blew the cap and caused self-reinforcing 429 cascades (April 17 morning). Progress dropped from steady-state to near-zero.
- With the limiter, retries burn tokens at the configured rate and the cascade is impossible.

**Do not run `generate_reasoning.py` without the limiter, and do not raise the limit above 200.**

### Teacher ensemble (as of April 17)
From `config.yaml`:
- `openai/gpt-oss-120b` — weight 40, max_concurrent 10, reasoning_effort medium, max_tokens_overhead 8192
- `google/gemma-4-26b` — weight 60, max_concurrent 12, max_tokens_overhead 4096
- Total 22 workers. Steady ~83–85 compliant traces/min at 200 rpm.
- Ensemble choices were made after empirical probes — see the commit message on `6f9a758` for the rejected alternatives (qwen3.5-122b and Nemotron-3-Super-120b both produce empty or tiny outputs under our UGF prompt; gpt-oss-20b is fast but too terse at low effort).

### Launch recipe

SSH to `fortyfive.hpc.uidaho.edu` (full hostname — the short `fortyfive` alias does NOT resolve):

```bash
ssh fortyfive.hpc.uidaho.edu "tmux new-session -d -s reasoning 'source ~/venvs/compression/bin/activate && cd ~/compression && TS=\$(date +%Y%m%d_%H%M%S) && LOG=logs/reasoning_generation_\${TS}.log && ln -sfn reasoning_generation_\${TS}.log logs/reasoning_generation_latest.log && python3 -u corpus/generation/generate_reasoning.py --limit 2000000 2>&1 | tee \$LOG'"
```

Use `python3 -u` or set `PYTHONUNBUFFERED=1` — otherwise stdout block-buffers through tee and you see no log output for 30+ min even though the process is running fine.

### How to monitor
- `cat ~/compression/corpus/processed/reasoning_progress.json` — completion counts per-teacher, per-model compliance stats
- `tail ~/compression/logs/reasoning_generation_latest.log` — last progress lines (every 100 completions)
- `grep -c '429' ~/compression/logs/reasoning_generation_latest.log` — total 429 count. Single-digit/day is healthy; hundreds/minute means a cascade.

### Diagnosing 429 floods

If the log fills with `429 rate-limited` messages:

1. **Kill reasoning-gen immediately**: `ssh fortyfive.hpc.uidaho.edu "tmux kill-session -t reasoning"`
2. **Wait ~60 sec**, then probe MR with a single call:
   ```bash
   ssh fortyfive.hpc.uidaho.edu "curl -s -k -X POST -H \"Authorization: Bearer \$(grep MINDROUTER_API_KEY ~/compression/.env | cut -d= -f2)\" -H 'Content-Type: application/json' -d '{\"model\":\"google/gemma-4-26b\",\"messages\":[{\"role\":\"user\",\"content\":\"OK\"}],\"max_tokens\":4}' https://mindrouter.uidaho.edu/v1/chat/completions"
   ```
3. **If probe returns 200 OK**, the rate limit drained normally — relaunch reasoning-gen and it should behave.
4. **If probe still returns 429 with `"current: 200"`** despite no activity from us, it's an **MR-side hiccup** (not our fault). Wait and retry; if it persists, ping the MR admin.

Resume is safe: `reasoning_progress.json` tracks completed IDs, and the script skips them on restart.

### Do NOT run generate_parallel.py concurrently

`corpus/generation/generate_parallel.py` (used for Translator parallel corpus + misc-corpora translation) has **no rate limiter**. Its default `max_concurrent: 16` can easily blast past the 200 rpm cap on its own. If you need to run it:

- Pause `generate_reasoning.py` first.
- Reduce `mindrouter.max_concurrent` (the top-level one, NOT the per-teacher ones) to **≤ 8** to naturally stay under 200 rpm.
- Restore afterward.

Or (cleaner, not yet done): port the `AsyncTokenBucket` pattern into `generate_parallel.py` so they can safely coexist.

---

## Quick reference

- **Rate limiter implementation**: `corpus/generation/generate_reasoning.py`, class `AsyncTokenBucket`, initialized in `main()`.
- **Config**: `corpus/generation/config.yaml`, keys under `mindrouter:`.
- **Generated corpus**: `corpus/processed/ugf_reasoning.jsonl` (main) + `ugf_reasoning_cxbot.jsonl` + `ugf_reasoning_misccorpora.jsonl`.
- **Heldout**: `corpus/processed/heldout_ids.json` — 5% stratified per source. Applied by Reasoner data loader via doc-key match.
- **Admin writeup**: `docs/mindrouter-usage-notes-2026-04-16.md` — context on our relationship with the MR service.
- **Model-size literature scan**: `docs/small-model-cot-literature-2026-04-22.md` — what published work tells us about whether CoT works at small sizes in restricted-vocab, narrow-domain, distillation settings. Summary: encouraging. Suggests 200M–500M Reasoner is viable; a three-size scaling study would strengthen the paper.

---

## Historical episodes worth not repeating (dated)

- **April 17 AM — 120-worker overnight thrashing**: original config was 60+100=160 workers, then bumped to 120 (24 gpt-oss + 96 gemma) overnight. Blew what was then a token quota and triggered a full-service 429 storm. Admin cleared the quota and reduced it to the current no-token-quota / 200-rpm-only model. Lesson: conservative beats aggressive on a shared service.
- **April 17 midday — phantom saturation**: MR was 429ing every request even when we were running at ~25 rpm. Initially diagnosed as shared-pool contention with other users, but admin later clarified it was an MR-side hiccup. Lesson: if you're under your cap and still 429ing, probe with single calls and suspect MR, not yourself.
- **April 17 late — gemma latency underestimate**: 22-worker config was provisioned assuming gemma takes ~12s/call (based on throttled-overnight observations). Fresh-socket probe showed 2.8s. That 4× error meant 22 workers could hit ~220 rpm under normal load — exceeding the 200 cap. Lesson: trust probe data over inferred rates from stressed runs.

See `memory/session_status.md` and `memory/feedback_mindrouter_concurrency.md` (in the persistent Claude memory dir) for even more detail.
