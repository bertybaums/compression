"""
Generate gold-standard English (P3) teacher answers for a benchmark JSONL.

P3 = pipeline 3 of the comparator framework: English query -> teacher reasons
in UNRESTRICTED English -> English response. Concretely this is
eval/run_comparator.py MINUS the UGF system prompt + few-shot exemplars — the
single-variable flip that isolates the vocabulary restriction. Same model
(gpt-oss-120b), same content-type template wrapping the same English question,
same reasoning_effort; only the Up-Goer-Five output constraint is removed.

Used by the English-baseline precursor (docs/english-baseline-design-2026-05-24.md):
the per-dimension gap between this P3 and the cached teacher-in-UGF comparator
(same prompts, same template) = the vocabulary tax at teacher (120B) scale.

Run on the fortyfive LOGIN node (needs MR + .env; compute nodes have no internet):
  python -m eval.run_p3_gold_english \
      --bench eval/sets/stress_bench.jsonl \
      --out eval/results/_jsonl/p3_gold_english_stress_$(date +%Y%m%d_%H%M%S).jsonl
"""
import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).parent.parent))

# Reusable, side-effect-free pieces from the comparator pipeline.
from eval.run_comparator import (
    CONTENT_TYPES, BENCH_TYPE_TO_TEMPLATE, AsyncTokenBucket, MR_BASE_URL, MODEL_ID,
)

_RATE: AsyncTokenBucket | None = None


def build_p3_messages(item: dict) -> tuple[list[dict], str, str]:
    """Same template wrap as the comparator, but NO UGF system prompt / few-shot."""
    template_name = BENCH_TYPE_TO_TEMPLATE.get(item["type"], "argument_analysis")
    template = CONTENT_TYPES[template_name]
    instruction = (item.get("instruction") or "").strip()
    question = item["question"].strip()
    english_query = f"{instruction}\n\n{question}" if instruction else question
    user_content = template.format(topic=english_query)
    return [{"role": "user", "content": user_content}], template_name, english_query


async def call_mr(session, sem, key, messages, max_tokens, timeout_s=360):
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {"model": MODEL_ID, "messages": messages, "max_tokens": max_tokens,
               "temperature": 0.7, "reasoning_effort": "medium"}
    async with sem:
        if _RATE is not None:
            await _RATE.acquire()
        t0 = time.time()
        try:
            async with session.post(f"{MR_BASE_URL}/chat/completions", json=payload,
                                    headers=headers,
                                    timeout=aiohttp.ClientTimeout(total=timeout_s),
                                    ssl=False) as resp:
                dt = time.time() - t0
                if resp.status != 200:
                    return None, dt, f"HTTP {resp.status}: {(await resp.text())[:200]}"
                data = await resp.json()
                return (data["choices"][0]["message"].get("content", "") or "").strip(), dt, None
        except Exception as e:
            return None, time.time() - t0, str(e)


async def process_one(session, sem, key, item, max_tokens):
    messages, template_name, english_query = build_p3_messages(item)
    resp, lat, err = await call_mr(session, sem, key, messages, max_tokens)
    if err:
        resp = f"<P3_ERROR: {err}>"
    return {"id": item["id"], "type": item["type"], "question": item["question"],
            "english_query": english_query, "template": template_name,
            "p3_model": MODEL_ID, "english_response": resp, "latency_s": round(lat, 2)}


async def main_async(args):
    global _RATE
    _RATE = AsyncTokenBucket(rate_per_sec=args.max_req_per_minute / 60.0, burst=args.burst)
    print(f"Rate: {args.max_req_per_minute} rpm, burst {args.burst}", flush=True)

    key = os.environ.get("MINDROUTER_API_KEY", "")
    if not key:
        envp = Path(__file__).parent.parent / ".env"
        if envp.exists():
            for line in envp.read_text().splitlines():
                if line.startswith("MINDROUTER_API_KEY="):
                    key = line.split("=", 1)[1].strip()
    if not key:
        raise SystemExit("MINDROUTER_API_KEY not set (env or .env)")

    items = [json.loads(l) for l in open(args.bench) if l.strip()]
    if args.limit:
        items = items[: args.limit]
    print(f"{len(items)} items from {args.bench}", flush=True)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)

    sem = asyncio.Semaphore(args.concurrency)
    conn = aiohttp.TCPConnector(limit=args.concurrency, ssl=False)
    async with aiohttp.ClientSession(connector=conn,
                                     timeout=aiohttp.ClientTimeout(total=None)) as session:
        t0 = time.time()
        n = 0
        tasks = [process_one(session, sem, key, it, args.max_tokens) for it in items]
        with open(args.out, "w", encoding="utf-8") as f:
            for fut in asyncio.as_completed(tasks):
                rec = await fut
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
                n += 1
                if n % 5 == 0 or n == len(items):
                    el = time.time() - t0
                    print(f"  [{n}/{len(items)}] {n / el * 60:.1f}/min", flush=True)
    errs = sum(1 for l in open(args.out) if '"<P3_ERROR' in l)
    print(f"Done. {n} P3 runs, {errs} errors -> {args.out}", flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--bench", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--max-tokens", type=int, default=6000)
    p.add_argument("--concurrency", type=int, default=5)
    p.add_argument("--max-req-per-minute", type=int, default=100)
    p.add_argument("--burst", type=int, default=10)
    asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    main()
