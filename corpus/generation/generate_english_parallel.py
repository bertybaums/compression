"""
Generate plain-English teacher traces for the matched prompt set — the English
arm of the 200M English-vocab baseline (docs/english-baseline-design-2026-05-24.md).

This is P3-at-scale: the SAME (topic, content_type) prompts as the UGF-N subset,
answered by the SAME teacher per prompt (routed by each prompt's source_model),
but in UNRESTRICTED English — no UGF system prompt, no few-shot, no validation /
retry-on-violation. The single controlled difference from the UGF arm is the
output vocabulary.

Reuses the shared rate machinery (corpus/generation/rate_limiter.py: make_bucket +
rate_schedule_ticker — same path generate_forms.py uses) and the producer-consumer
+ resume design from generate_reasoning.py. Resumable via the progress file.

Usage (fortyfive login node, in tmux, unbuffered + tee):
  python3 -u -m corpus.generation.generate_english_parallel \
      --assignments corpus/processed/matched_prompts_400k.jsonl \
      --output corpus/processed/english_n.jsonl \
      --progress corpus/processed/english_n_progress.json
"""
import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from corpus.generation.generate_reasoning import (
    CONTENT_TYPES, CONFIG, MINDROUTER_BASE_URL, MINDROUTER_API_KEY,
    MAX_TOKENS, TEMPERATURE, MAX_RETRIES, RETRY_BACKOFF,
    load_progress, save_progress,
)
from corpus.generation.rate_limiter import make_bucket, rate_schedule_ticker, AsyncTokenBucket

# Per-teacher worker settings keyed by the source_model strings recorded in the
# corpus. NOT taken from config.yaml (whose reasoning_teachers list has drifted to
# a qwen-heavy run); the matched experiment must reuse the same two teachers that
# produced the UGF-N subset. Both confirmed live on MR (May 25). Overhead +
# reasoning_effort mirror how the corpus was generated.
TEACHER_SETTINGS = {
    "openai/gpt-oss-120b": {"max_concurrent": 10, "max_tokens_overhead": 8192, "reasoning_effort": "medium"},
    "google/gemma-4-26b":  {"max_concurrent": 12, "max_tokens_overhead": 4096},
}
DEFAULT_SETTINGS = {"max_concurrent": 8, "max_tokens_overhead": 4096}

_RATE_LIMITER: AsyncTokenBucket | None = None


async def api_call(session: aiohttp.ClientSession, messages: list[dict], teacher: dict) -> str | None:
    """Single MR call. Mirrors generate_reasoning.api_call (same per-teacher
    settings — reasoning_effort, enable_thinking, max_tokens overhead, retries,
    rate-bucket-before-every-attempt) so the English arm matches the UGF arm's
    teacher behaviour exactly, minus the system prompt."""
    url = f"{MINDROUTER_BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {MINDROUTER_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": teacher["id"],
        "messages": messages,
        "max_tokens": MAX_TOKENS + teacher.get("max_tokens_overhead", 3072),
        "temperature": TEMPERATURE,
    }
    if "reasoning_effort" in teacher:
        payload["reasoning_effort"] = teacher["reasoning_effort"]
    if "enable_thinking" in teacher:
        payload["chat_template_kwargs"] = {"enable_thinking": teacher["enable_thinking"]}

    tag = teacher["id"].split("/")[-1][:20]
    for attempt in range(MAX_RETRIES):
        if _RATE_LIMITER is not None:
            await _RATE_LIMITER.acquire()
        try:
            async with session.post(url, json=payload, headers=headers,
                                    timeout=aiohttp.ClientTimeout(total=360)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    content = data["choices"][0]["message"].get("content")
                    if content is None:
                        return None
                    return content.strip()
                elif resp.status == 429:
                    wait = RETRY_BACKOFF * (2 ** attempt)
                    print(f"  [{tag}] 429 rate-limited, waiting {wait:.0f}s ({attempt+1}/{MAX_RETRIES})", flush=True)
                    await asyncio.sleep(wait)
                else:
                    body = (await resp.text())[:120]
                    print(f"  [{tag}] HTTP {resp.status}: {body} ({attempt+1}/{MAX_RETRIES})", flush=True)
                    await asyncio.sleep(RETRY_BACKOFF * (2 ** attempt))
        except asyncio.TimeoutError:
            print(f"  [{tag}] timeout ({attempt+1}/{MAX_RETRIES})", flush=True)
            await asyncio.sleep(RETRY_BACKOFF * (2 ** attempt))
        except aiohttp.ClientError as e:
            print(f"  [{tag}] {type(e).__name__}: {e} ({attempt+1}/{MAX_RETRIES})", flush=True)
            await asyncio.sleep(RETRY_BACKOFF * (2 ** attempt))
    return None


async def generate_one_english(session: aiohttp.ClientSession, a: dict, teacher: dict) -> dict | None:
    """English answer to one matched prompt — no UGF system prompt, no few-shot,
    no validation. Same content-type template + teacher as the UGF counterpart."""
    user_prompt = CONTENT_TYPES[a["content_type"]].format(topic=a["topic"])
    text = await api_call(session, [{"role": "user", "content": user_prompt}], teacher)
    if text is None:
        return None
    return {
        "id": a["id"], "english_text": text, "content_type": a["content_type"],
        "topic": a["topic"], "source_model": teacher["id"],
        "metadata": {"domain": a.get("domain", "")}, "compliant": True,
    }


def load_assignments(path: str) -> list[dict]:
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


async def main(args):
    global _RATE_LIMITER
    _RATE_LIMITER, sched = make_bucket(CONFIG)
    if sched is not None:
        asyncio.create_task(rate_schedule_ticker(_RATE_LIMITER, sched))

    if not MINDROUTER_API_KEY:
        sys.exit("MINDROUTER_API_KEY not set")

    assignments = load_assignments(args.assignments)
    present = sorted({a["source_model"] for a in assignments})
    teachers = [{"id": sm, **TEACHER_SETTINGS.get(sm, DEFAULT_SETTINGS)} for sm in present]
    teachers_by_id = {t["id"]: t for t in teachers}
    for sm in present:
        if sm not in TEACHER_SETTINGS:
            print(f"  WARNING: {sm} not in TEACHER_SETTINGS; using defaults", flush=True)

    completed = load_progress(Path(args.progress))
    remaining = [a for a in assignments if a["id"] not in completed]
    print(f"Total {len(assignments)}; done {len(completed)}; remaining {len(remaining)}", flush=True)
    print(f"teachers: {[t['id'] for t in teachers]}", flush=True)
    print(f"teacher mix (remaining): {dict(Counter(a['source_model'] for a in remaining))}", flush=True)
    if not remaining:
        print("nothing to do")
        return

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    per_teacher_queues = {t["id"]: asyncio.Queue() for t in teachers}
    for a in remaining:
        per_teacher_queues[a["source_model"]].put_nowait(a)
    results_queue: asyncio.Queue = asyncio.Queue(maxsize=1024)
    stats = {"completed": len(completed), "ok": 0, "failed": 0}
    t_start = time.time()

    async def worker(teacher, session):
        q = per_teacher_queues[teacher["id"]]
        while True:
            try:
                a = q.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                res = await generate_one_english(session, a, teacher)
            except Exception as e:
                print(f"  worker err ({teacher['id']}): {type(e).__name__}: {e}", flush=True)
                res = None
            await results_queue.put((a, res))

    async def writer(total):
        done = last_save = last_flush = 0
        with open(args.output, "a", encoding="utf-8") as out_f:
            while done < total:
                a, res = await results_queue.get()
                done += 1
                if res is None:
                    stats["failed"] += 1
                else:
                    out_f.write(json.dumps(res, ensure_ascii=False) + "\n")
                    completed.add(res["id"])
                    stats["ok"] += 1
                if done - last_flush >= 50:
                    out_f.flush()
                    last_flush = done
                if done - last_save >= 200:
                    stats["completed"] = len(completed)
                    save_progress(Path(args.progress), completed, stats)
                    last_save = done
                    rate = done / (time.time() - t_start) * 60
                    print(f"  [{done}/{total}] ({done/total*100:.1f}%) ok={stats['ok']} "
                          f"failed={stats['failed']} {rate:.1f}/min", flush=True)
            out_f.flush()

    connector = aiohttp.TCPConnector(ssl=False, limit=0)
    async with aiohttp.ClientSession(connector=connector) as session:
        worker_tasks = []
        for t in teachers:
            for _ in range(t["max_concurrent"]):
                worker_tasks.append(asyncio.create_task(worker(t, session)))
        wtask = asyncio.create_task(writer(len(remaining)))
        print(f"Spawned {sum(t['max_concurrent'] for t in teachers)} workers across "
              f"{len(teachers)} teachers.", flush=True)
        await wtask
        await asyncio.gather(*worker_tasks, return_exceptions=True)

    stats["completed"] = len(completed)
    save_progress(Path(args.progress), completed, stats)
    print(f"\nDone. {json.dumps(stats)}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--assignments", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--progress", required=True)
    asyncio.run(main(ap.parse_args()))
