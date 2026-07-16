"""
Form arm of the form-controlled retrain (docs/form-retrain-clean-design-2026-06-03.md).

Option B: POINTED prompts + prompt-attentive responses. For each matched prompt we
generate a UGF response that must engage the SPECIFIC question (restate it, work it
on a concrete case, raise and meet the specific objection), not a generic essay.
Same prompts/teachers as the essay arm (matched_prompts_400k.jsonl), routed to the
same teacher per prompt; length-matched to the essay arm's ~317-word median.

Reuses generate_reasoning's UGF system prompt + few-shot + validate/retry, and
generate_english_parallel's matched routing + producer-consumer + shared rate
limiter. The single experimental change vs the essay arm: the user prompt is a
POINTED template (below) instead of the generic CONTENT_TYPES template, and that
pointed prompt is stored as the training prompt.

Output schema (sft_plain-ready): {id, prompt, response, content_type, topic,
source_model, compliant}.

Usage (fortyfive, in tmux, unbuffered + tee):
  python3 -u -m corpus.generation.generate_form_attentive \
      --assignments corpus/processed/matched_prompts_400k.jsonl \
      --output corpus/processed/ugf_form_n.jsonl \
      --progress corpus/processed/ugf_form_n_progress.json
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
    SYSTEM_PROMPT, FEWSHOT_EXEMPLARS, CONFIG, MINDROUTER_BASE_URL, MINDROUTER_API_KEY,
    MAX_TOKENS, TEMPERATURE, MAX_RETRIES, RETRY_BACKOFF, load_progress, save_progress,
)
from corpus.generation.validate_ugf import validate_ugf
from corpus.generation.rate_limiter import make_bucket, rate_schedule_ticker, AsyncTokenBucket

# Same two teachers + settings as the matched English arm (built from the
# source_models present, NOT config.yaml's drifted reasoning_teachers list).
TEACHER_SETTINGS = {
    "openai/gpt-oss-120b": {"max_concurrent": 10, "max_tokens_overhead": 8192, "reasoning_effort": "medium"},
    "google/gemma-4-26b":  {"max_concurrent": 12, "max_tokens_overhead": 4096},
}
DEFAULT_SETTINGS = {"max_concurrent": 8, "max_tokens_overhead": 4096}

# POINTED templates: the response must engage THIS specific question, work it on a
# concrete case, and meet the specific objection it invites -- not a general talk
# about the subject. Topics come from the corpus (never the stress-bench forms),
# so the stress bench stays out-of-distribution for both arms.
POINTED_CONTENT_TYPES = {
    "concept_explanation": (
        "Here is an idea: {topic}.\n\n"
        "Do not give a general talk about the subject. Say exactly what this idea comes to, "
        "in your own plain words. Then test it against one hard case where it is not clear "
        "what to say, and show how the idea does or does not hold up in that case. Write a "
        "full, developed answer in plain running prose."
    ),
    "chain_of_thought": (
        "Here is a specific thing to work out: {topic}.\n\n"
        "Work it out step by step, in plain sentences joined into a paragraph. Make each step "
        "turn on the specific case in front of you, not a general point. Then name one case "
        "where the usual answer would be wrong, and say why. Write a full, developed answer."
    ),
    "socratic_dialogue": (
        "Two people talk about this exact question: {topic}.\n\n"
        "One person keeps pushing for a clear answer to the specific question; the other must "
        "meet each specific point that is raised and not change the subject. Go at least six "
        "turns. Plain text only."
    ),
    "argument_analysis": (
        "Someone makes this exact case: {topic}.\n\n"
        "Take their specific case, not the general subject. Say what they are claiming, what "
        "they think follows from it, and where the thinking holds and where it breaks. Then "
        "give one case that tests it, and say what that case shows. Write flowing plain prose."
    ),
    "thought_experiment": (
        "Here is a situation that makes you think: {topic}.\n\n"
        "Say exactly what the hard question is in this specific situation, what two different "
        "answers people would give to it, and which answer holds up when you push on it, and "
        "why. Stay on this specific situation, do not drift to the general subject. Plain prose."
    ),
}

_RATE_LIMITER: AsyncTokenBucket | None = None


async def api_call(session: aiohttp.ClientSession, messages: list[dict], teacher: dict) -> str | None:
    """Single MR call, rate-limited before every attempt (incl. retries)."""
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
                    return content.strip() if content else None
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


async def generate_one_form(session: aiohttp.ClientSession, a: dict, teacher: dict) -> dict | None:
    """Pointed-prompt, prompt-attentive UGF response with validate-and-retry."""
    pointed = POINTED_CONTENT_TYPES[a["content_type"]].format(topic=a["topic"])
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for ex_user, ex_assistant in FEWSHOT_EXEMPLARS:   # UGF-compliance anchors
        messages.append({"role": "user", "content": ex_user})
        messages.append({"role": "assistant", "content": ex_assistant})
    messages.append({"role": "user", "content": pointed})

    text = await api_call(session, messages, teacher)
    if text is None:
        return None

    for _ in range(3):
        ok, violations = validate_ugf(text)
        if ok:
            break
        correction = (
            f"Your response contains words or symbols not in the allowed list: "
            f"{', '.join(repr(v) for v in violations[:15])}. "
            f"Rewrite the entire response, keeping it about the same specific question. Two "
            f"fixes: (a) replace each disallowed word with a description using only allowed "
            f"words; (b) remove all markdown -- plain running prose only."
        )
        messages.append({"role": "assistant", "content": text})
        messages.append({"role": "user", "content": correction})
        text = await api_call(session, messages, teacher)
        if text is None:
            return None

    ok, violations = validate_ugf(text)
    return {
        "id": a["id"], "prompt": pointed, "response": text,
        "content_type": a["content_type"], "topic": a["topic"],
        "source_model": teacher["id"], "compliant": ok,
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
    if args.limit:
        assignments = assignments[: args.limit]
    present = sorted({a["source_model"] for a in assignments})
    teachers = [{"id": sm, **TEACHER_SETTINGS.get(sm, DEFAULT_SETTINGS)} for sm in present]
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
    stats = {"completed": len(completed), "compliant": 0, "non_compliant": 0, "failed": 0}
    t_start = time.time()

    async def worker(teacher, session):
        q = per_teacher_queues[teacher["id"]]
        while True:
            try:
                a = q.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                res = await generate_one_form(session, a, teacher)
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
                    stats["compliant" if res["compliant"] else "non_compliant"] += 1
                if done - last_flush >= 50:
                    out_f.flush(); last_flush = done
                if done - last_save >= 200:
                    stats["completed"] = len(completed)
                    save_progress(Path(args.progress), completed, stats)
                    last_save = done
                    rate = done / (time.time() - t_start) * 60
                    print(f"  [{done}/{total}] ({done/total*100:.1f}%) compliant={stats['compliant']} "
                          f"non_compliant={stats['non_compliant']} failed={stats['failed']} "
                          f"{rate:.1f}/min", flush=True)
            out_f.flush()

    connector = aiohttp.TCPConnector(limit=0)
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
    ap.add_argument("--limit", type=int, default=None)
    asyncio.run(main(ap.parse_args()))
