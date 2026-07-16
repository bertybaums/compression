"""
Stage 1 of ARM C (prompt informativeness) -- the case pool.

Background (docs/form-retrain-clean-design-2026-06-03.md, THIRD AMENDMENT): arms A
and B both carry only 380 unique prompts across ~400K examples (76 topics x 5
content_types, ~1,053 repeats), while responses are ~all distinct. So each prompt
maps to ~1,053 different responses, p(response|prompt) is ~unconditional within a
topic bucket, and attending to prompt detail earns nothing in training loss. Arm C
tests the hypothesis that this -- not response form, capacity, vocabulary or
post-training -- is the binding constraint.

The factorial stays clean because ARM C reuses ARM B's machinery exactly. ARM B's
prompt is POINTED_CONTENT_TYPES[ct].format(topic=<one of 76 GENERIC topics>). ARM C
fills the SAME slot in the SAME template with a distinct SPECIFIC CASE per example.
Same templates, same form instructions, same teachers, same routing: the only thing
that changes is whether the slot carries a recycled general subject or a particular
one. That is exactly the B-vs-C contrast (prompt diversity at fixed form).

This script builds the pool of specific cases. Cases are generated in batches (many
per call, so ~20K calls rather than ~400K), validated against the UGF wordlist
(they end up inside the prompt the model reads, so they must be in-vocabulary), and
deduplicated globally. Then build_specific_assignments.py pairs them to the 400K
ids, and the ARM B runner generates responses with NO code changes:

    python3 -u -m corpus.generation.generate_specific_cases \
        --assignments corpus/processed/matched_prompts_400k.jsonl \
        --output corpus/processed/specific_cases_pool.jsonl \
        --progress corpus/processed/specific_cases_progress.json

    python3 -m corpus.generation.build_specific_assignments \
        --assignments corpus/processed/matched_prompts_400k.jsonl \
        --pool corpus/processed/specific_cases_pool.jsonl \
        --output corpus/processed/specific_assignments_400k.jsonl

    python3 -u -m corpus.generation.generate_form_attentive \
        --assignments corpus/processed/specific_assignments_400k.jsonl \
        --output corpus/processed/ugf_formdiv_n.jsonl \
        --progress corpus/processed/ugf_formdiv_n_progress.json \
        --reference-median 285
"""
import argparse
import asyncio
import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from corpus.generation.generate_reasoning import (
    SYSTEM_PROMPT, CONFIG, MINDROUTER_BASE_URL, MINDROUTER_API_KEY,
    TEMPERATURE, MAX_RETRIES, RETRY_BACKOFF,
)
from corpus.generation.validate_ugf import validate_ugf
from corpus.generation.rate_limiter import make_bucket, rate_schedule_ticker, AsyncTokenBucket

TEACHER_SETTINGS = {
    "openai/gpt-oss-120b": {"max_concurrent": 10, "max_tokens_overhead": 8192, "reasoning_effort": "medium"},
    "google/gemma-4-26b":  {"max_concurrent": 12, "max_tokens_overhead": 4096},
}
DEFAULT_SETTINGS = {"max_concurrent": 8, "max_tokens_overhead": 4096}

# What a "case" must look like per content_type, phrased to slot into the SAME
# POINTED template ARM B uses. Each is the thing that replaces the generic topic.
CASE_KIND = {
    "concept_explanation": "a specific idea someone holds, stated as one concrete claim",
    "chain_of_thought": "a specific thing to work out, stated as one concrete problem with particulars",
    "socratic_dialogue": "a specific exact question two people could argue about",
    "argument_analysis": "a specific case someone makes, stated as one concrete argument",
    "thought_experiment": "a specific situation, stated concretely with particulars",
}

BATCH_PROMPT = (
    "Topic area: {topic}\n\n"
    "Write {n} DIFFERENT examples of {kind}, all within that topic area.\n\n"
    "Rules:\n"
    "- Each one must be PARTICULAR, not general. Name a concrete person, thing, "
    "situation, number, or claim. Someone should be able to answer THAT one and "
    "not just talk about the topic area.\n"
    "- Each must be one or two sentences.\n"
    "- Make them differ from each other: different cases, different angles, "
    "different particulars. Do not restate the topic area {n} times.\n"
    "- Use only simple, common words (the ten hundred most used words).\n"
    "- No markdown. Number them 1. to {n}. and write nothing else."
)

_RATE_LIMITER: AsyncTokenBucket | None = None
_NUMBERED = re.compile(r"^\s*\d+[.)]\s*(.+)$")


def parse_cases(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        m = _NUMBERED.match(line)
        if not m:
            continue
        c = m.group(1).strip().strip('"').strip()
        # Guard against the model echoing the instructions or emitting stubs.
        if 4 <= len(c.split()) <= 60:
            out.append(c)
    return out


def norm(case: str) -> str:
    """Dedup key: casefold, strip punctuation/whitespace variation."""
    return re.sub(r"[^a-z0-9 ]", "", case.casefold()).strip()


async def api_call(session, messages, teacher) -> str | None:
    url = f"{MINDROUTER_BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {MINDROUTER_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": teacher["id"], "messages": messages,
        "max_tokens": 2048 + teacher.get("max_tokens_overhead", 3072),
        "temperature": 1.0,   # high: we want spread across cases, not the modal one
    }
    if "reasoning_effort" in teacher:
        payload["reasoning_effort"] = teacher["reasoning_effort"]
    tag = teacher["id"].split("/")[-1][:20]
    for attempt in range(MAX_RETRIES):
        if _RATE_LIMITER is not None:
            await _RATE_LIMITER.acquire()
        try:
            async with session.post(url, json=payload, headers=headers,
                                    timeout=aiohttp.ClientTimeout(total=360)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    msg = data["choices"][0]["message"]
                    content = msg.get("content") or msg.get("reasoning_content")
                    return content.strip() if content else None
                if resp.status == 429:
                    await asyncio.sleep(RETRY_BACKOFF * (2 ** attempt))
                else:
                    body = (await resp.text())[:120]
                    print(f"  [{tag}] HTTP {resp.status}: {body}", flush=True)
                    await asyncio.sleep(RETRY_BACKOFF * (2 ** attempt))
        except (asyncio.TimeoutError, aiohttp.ClientError) as e:
            print(f"  [{tag}] {type(e).__name__}", flush=True)
            await asyncio.sleep(RETRY_BACKOFF * (2 ** attempt))
    return None


async def main(args):
    global _RATE_LIMITER
    _RATE_LIMITER, sched = make_bucket(CONFIG)
    if sched is not None:
        asyncio.create_task(rate_schedule_ticker(_RATE_LIMITER, sched))
    if not MINDROUTER_API_KEY:
        sys.exit("MINDROUTER_API_KEY not set")

    # Bucket sizes come from the real assignment file, so the pool matches demand
    # exactly: the same (topic, content_type) mix the essay/form arms were built on.
    demand: Counter = Counter()
    teacher_of: dict[tuple, Counter] = defaultdict(Counter)
    with open(args.assignments) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            a = json.loads(line)
            k = (a["topic"], a["content_type"])
            demand[k] += 1
            teacher_of[k][a["source_model"]] += 1

    need = {k: max(1, round(v * args.coverage)) for k, v in demand.items()}
    print(f"buckets: {len(demand)} | examples: {sum(demand.values()):,} | "
          f"unique cases wanted: {sum(need.values()):,} (coverage={args.coverage})", flush=True)

    pool: dict[tuple, list[str]] = defaultdict(list)
    seen: dict[tuple, set] = defaultdict(set)
    if Path(args.output).exists():   # resume
        with open(args.output) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                k = (d["topic"], d["content_type"])
                if norm(d["case"]) not in seen[k]:
                    seen[k].add(norm(d["case"]))
                    pool[k].append(d["case"])
        print(f"resumed: {sum(len(v) for v in pool.values()):,} cases already pooled", flush=True)

    todo = [k for k in demand if len(pool[k]) < need[k]]
    if not todo:
        print("pool already complete")
        return

    out_f = open(args.output, "a", encoding="utf-8")
    lock = asyncio.Lock()
    stats = {"calls": 0, "parsed": 0, "kept": 0, "dup": 0, "non_ugf": 0}
    t0 = time.time()

    queue: asyncio.Queue = asyncio.Queue()
    for k in todo:
        queue.put_nowait(k)

    async def worker(teacher, session):
        while True:
            try:
                k = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            topic, ct = k
            stall = 0
            while len(pool[k]) < need[k] and stall < args.max_stalls:
                msg = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": BATCH_PROMPT.format(
                        topic=topic, n=args.batch, kind=CASE_KIND[ct])},
                ]
                text = await api_call(session, msg, teacher)
                stats["calls"] += 1
                if not text:
                    stall += 1
                    continue
                cases = parse_cases(text)
                stats["parsed"] += len(cases)
                added = 0
                async with lock:
                    for c in cases:
                        if len(pool[k]) >= need[k]:
                            break
                        nk = norm(c)
                        if not nk or nk in seen[k]:
                            stats["dup"] += 1
                            continue
                        ok, _ = validate_ugf(c)
                        if not ok:
                            stats["non_ugf"] += 1
                            continue
                        seen[k].add(nk)
                        pool[k].append(c)
                        out_f.write(json.dumps(
                            {"topic": topic, "content_type": ct, "case": c},
                            ensure_ascii=False) + "\n")
                        stats["kept"] += 1
                        added += 1
                    out_f.flush()
                # A bucket that stops yielding NEW cases is saturated: the teacher has
                # run out of distinct particulars for it. Give up rather than burn the
                # rate cap regenerating duplicates -- build_specific_assignments.py
                # reports the achieved ratio and it is fine for it to be < 1.0.
                stall = 0 if added else stall + 1
            if len(pool[k]) < need[k]:
                print(f"  saturated: {ct} / {topic[:45]!r} -> {len(pool[k])}/{need[k]}", flush=True)

    connector = aiohttp.TCPConnector(limit=0)
    async with aiohttp.ClientSession(connector=connector) as session:
        present = sorted({m for c in teacher_of.values() for m in c})
        teachers = [{"id": m, **TEACHER_SETTINGS.get(m, DEFAULT_SETTINGS)} for m in present]
        tasks = []
        for t in teachers:
            for _ in range(t["max_concurrent"]):
                tasks.append(asyncio.create_task(worker(t, session)))
        print(f"spawned {len(tasks)} workers across {len(teachers)} teachers", flush=True)

        async def reporter():
            while any(not t.done() for t in tasks):
                await asyncio.sleep(60)
                have = sum(len(v) for v in pool.values())
                want = sum(need.values())
                rate = stats["kept"] / max(1e-9, (time.time() - t0)) * 60
                print(f"  [{have:,}/{want:,}] ({have/want*100:.1f}%) calls={stats['calls']:,} "
                      f"kept={stats['kept']:,} dup={stats['dup']:,} non_ugf={stats['non_ugf']:,} "
                      f"{rate:.0f} cases/min", flush=True)
                Path(args.progress).write_text(json.dumps(
                    {"have": have, "want": want, **stats}, indent=2))

        rep = asyncio.create_task(reporter())
        await asyncio.gather(*tasks, return_exceptions=True)
        rep.cancel()

    out_f.close()
    have = sum(len(v) for v in pool.values())
    print(f"\nDone. pooled {have:,} unique cases across {len(pool)} buckets. {json.dumps(stats)}",
          flush=True)
    Path(args.progress).write_text(json.dumps({"have": have, "want": sum(need.values()), **stats}, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--assignments", required=True, help="matched_prompts_400k.jsonl (defines demand)")
    ap.add_argument("--output", required=True, help="case pool jsonl (append/resume)")
    ap.add_argument("--progress", required=True)
    ap.add_argument("--batch", type=int, default=25, help="cases requested per call")
    ap.add_argument("--coverage", type=float, default=1.0,
                    help="unique cases per example (1.0 = a distinct case for every "
                         "example, i.e. prompt:example ~ 1.0 like ugf_forms_corpus)")
    ap.add_argument("--max-stalls", type=int, default=6,
                    help="give up on a bucket after this many calls yielding no new cases")
    args = ap.parse_args()
    asyncio.run(main(args))
