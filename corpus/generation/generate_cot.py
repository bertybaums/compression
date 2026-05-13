"""
Generate UGF chain-of-thought corpus for SFT-with-verifier and downstream RL.

Two tracks:
  LOGIC      — synthetic puzzles (logic_puzzles.generate) with verifiable
               verdicts. Teacher CoT is rejection-sampled: only traces whose
               extracted verdict matches the puzzle's ground truth are kept.
  PHILOSOPHY — open-ended prompts sampled from english_passages.jsonl (or a
               supplied JSONL). No crisp verifier; UGF compliance and
               retry-on-violations same as the v1 reasoning generator.

Each track is run with a 50/50 short/extended CoT-depth mix.

Reuses:
  - corpus.generation.api_call (via generate_reasoning) for MR dispatch
  - corpus.generation.validate_ugf for compliance check
  - corpus.generation.rate_limiter for the shared 200-rpm cap
  - corpus.generation.config.yaml for teacher ensemble

Output schema (JSONL):
  {id, track, depth, reasoning, conclusion, verdict?, expected?, correct?,
   compliant, source_model, scenario?, prompt_text}

Usage:
  python corpus/generation/generate_cot.py \
      --logic-n 50000 \
      --philosophy-n 50000 \
      --philosophy-topics corpus/processed/english_passages.jsonl \
      --output corpus/processed/ugf_cot.jsonl \
      --progress corpus/processed/cot_progress.json
"""

import argparse
import asyncio
import json
import os
import random
import sys
import time
from pathlib import Path

import aiohttp
import yaml
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from corpus.generation.validate_ugf import validate_ugf
from corpus.generation.rate_limiter import make_bucket, rate_schedule_ticker
from corpus.generation.cot_prompts import build_messages, TRACKS
from corpus.generation.logic_puzzles import generate as gen_puzzles, verify

CONFIG_PATH = Path(__file__).parent / "config.yaml"
with open(CONFIG_PATH) as f:
    CONFIG = yaml.safe_load(f)

load_dotenv(Path(__file__).parent.parent.parent / ".env")

MINDROUTER_BASE_URL = CONFIG["mindrouter"]["base_url"]
MINDROUTER_API_KEY = os.environ.get("MINDROUTER_API_KEY", "")
MAX_RETRIES = CONFIG["mindrouter"]["max_retries"]
RETRY_BACKOFF = CONFIG["mindrouter"]["retry_backoff_base"]

TEACHERS = CONFIG["mindrouter"].get("reasoning_teachers") or [{
    "id": CONFIG["mindrouter"]["model"],
    "weight": 100,
    "max_concurrent": CONFIG["mindrouter"].get("max_concurrent", 8),
    "max_tokens_overhead": 3072,
}]

REASONING_CONFIG = CONFIG["generation"]["reasoning"]
MAX_TOKENS = REASONING_CONFIG["max_tokens"]
TEMPERATURE = REASONING_CONFIG["temperature"]

_RATE_LIMITER = None  # populated in main()


# ---------------------------------------------------------------------------
# Assignment generation
# ---------------------------------------------------------------------------

DEPTHS = ["short", "extended"]


def make_logic_assignments(n: int, seed: int = 42) -> list[dict]:
    """Generate n logic-track assignments by drawing synthetic puzzles."""
    puzzles = gen_puzzles(n, seed=seed)
    rng = random.Random(seed + 1)
    out: list[dict] = []
    for i, p in enumerate(puzzles):
        depth = DEPTHS[i % len(DEPTHS)]
        out.append({
            "id": f"cot-logic-{i:07d}",
            "track": "logic",
            "depth": depth,
            "puzzle": {
                "rule": p.rule,
                "is_valid": p.is_valid,
                "premises": p.premises,
                "conclusion": p.conclusion,
                "scenario": p.scenario,
            },
            "prompt_text": p.natural_prompt,
        })
    rng.shuffle(out)
    return out


def load_philosophy_topics(path: Path, n: int, seed: int = 42,
                           exclude_track: str | None = None) -> list[str]:
    """Sample n topic strings from a JSONL with a `text` field.

    If `exclude_track` is supplied (e.g. "logic_critical_thinking"), records
    whose metadata.track matches are skipped — so the philosophy track is
    actually philosophy.
    """
    rng = random.Random(seed)
    pool: list[str] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if exclude_track and r.get("metadata", {}).get("track") == exclude_track:
                continue
            txt = r.get("text", "").strip()
            if 40 <= len(txt) <= 2000:
                pool.append(txt)
    rng.shuffle(pool)
    if n > len(pool):
        print(f"  WARN: requested {n} philosophy topics, pool has {len(pool)}. "
              f"Sampling with replacement.")
        return [rng.choice(pool) for _ in range(n)]
    return pool[:n]


def make_philosophy_assignments(topics: list[str]) -> list[dict]:
    out: list[dict] = []
    for i, topic in enumerate(topics):
        out.append({
            "id": f"cot-phil-{i:07d}",
            "track": "philosophy",
            "depth": DEPTHS[i % len(DEPTHS)],
            "topic": topic,
            "prompt_text": topic,
        })
    return out


def assign_teachers(assignments: list[dict], teachers: list[dict], seed: int = 43) -> None:
    rng = random.Random(seed)
    weights = [t["weight"] for t in teachers]
    for a in assignments:
        a["teacher_id"] = rng.choices(teachers, weights=weights, k=1)[0]["id"]


# ---------------------------------------------------------------------------
# Single-trace generation
# ---------------------------------------------------------------------------

async def api_call(session: aiohttp.ClientSession, messages: list[dict],
                   teacher: dict, semaphore: asyncio.Semaphore) -> str | None:
    """One MR call with retries + global rate limiter."""
    url = f"{MINDROUTER_BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {MINDROUTER_API_KEY}",
               "Content-Type": "application/json"}
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
        async with semaphore:
            if _RATE_LIMITER is not None:
                await _RATE_LIMITER.acquire()
            try:
                async with session.post(
                    url, json=payload, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=360),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        content = data["choices"][0]["message"].get("content")
                        if content is None:
                            return None
                        return content.strip()
                    elif resp.status == 429:
                        await asyncio.sleep(RETRY_BACKOFF * (2 ** attempt))
                    else:
                        body = (await resp.text())[:120]
                        print(f"  [{tag}] HTTP {resp.status}: {body}")
                        await asyncio.sleep(RETRY_BACKOFF * (2 ** attempt))
            except asyncio.TimeoutError:
                await asyncio.sleep(RETRY_BACKOFF * (2 ** attempt))
            except aiohttp.ClientError as e:
                print(f"  [{tag}] client error: {type(e).__name__}: {e}")
                await asyncio.sleep(RETRY_BACKOFF * (2 ** attempt))
    return None


def _try_parse_json(text: str) -> dict | None:
    """Pull a JSON object out of `text`, tolerating markdown fences."""
    candidate = text.strip()
    if candidate.startswith("```"):
        # strip code fence
        lines = candidate.split("\n")
        candidate = "\n".join(l for l in lines if not l.strip().startswith("```"))
    # Try whole-string parse first
    try:
        obj = json.loads(candidate)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    # Fall back: locate the first {...} block
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(candidate[start:end + 1])
        except json.JSONDecodeError:
            return None
    return None


def _verify_logic(parsed: dict, puzzle_truth: bool) -> dict:
    """Compare parsed verdict to ground truth. Verdict tokens come from the
    LOGIC track's prompt: 'follows' or 'does not follow'."""
    verdict = parsed.get("verdict", "").strip().lower()
    if "does not follow" in verdict or "not follow" in verdict:
        extracted = "does_not_follow"
    elif "follows" in verdict or verdict in {"yes", "valid"}:
        extracted = "follows"
    else:
        extracted = None
    expected = "follows" if puzzle_truth else "does_not_follow"
    return {
        "expected": expected,
        "extracted": extracted,
        "correct": extracted == expected if extracted else None,
    }


async def generate_one(session, assignment: dict, teacher: dict,
                       semaphore: asyncio.Semaphore) -> dict | None:
    """Generate one CoT trace via one teacher. Returns a result record (which
    may be marked non-compliant or verifier-failed) or None on hard failure.

    Rejection-sampling: a logic-track trace whose verdict is wrong is still
    kept in the output (marked correct=False) so the downstream training
    code can decide whether to use it (positive-only SFT vs contrastive
    training). The writer logs them with correct=True/False so we can audit.
    """
    track = assignment["track"]
    depth = assignment["depth"]
    if track == "logic":
        puzzle = assignment["puzzle"]
        messages = build_messages(
            "logic", depth,
            premises_block="\n".join(puzzle["premises"]),
            conclusion=puzzle["conclusion"],
        )
    else:
        messages = build_messages("philosophy", depth, topic=assignment["topic"])

    raw = await api_call(session, messages, teacher, semaphore)
    if raw is None:
        return None

    parsed = _try_parse_json(raw)
    reasoning = (parsed or {}).get("reasoning", "")
    other_key = "verdict" if track == "logic" else "conclusion"
    other_value = (parsed or {}).get(other_key, "")

    # Validate the natural-language part (the reasoning + the conclusion/verdict)
    # against UGF. Both should be compliant; we concatenate for the check.
    combined_text = f"{reasoning} {other_value}".strip()
    is_compliant, violations = validate_ugf(combined_text) if combined_text else (False, ["empty_response"])

    # On compliance failure, run up to 2 retries with the violations called out.
    for retry in range(2):
        if is_compliant:
            break
        if not violations:
            break
        correction = (
            f"Your response contains words not in the allowed list: "
            f"{', '.join(repr(v) for v in violations[:15])}. "
            f"Rewrite the entire JSON object. Replace each disallowed word with a "
            f"description using only allowed words. Output only one JSON object on a single line."
        )
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": correction})
        raw = await api_call(session, messages, teacher, semaphore)
        if raw is None:
            break
        parsed = _try_parse_json(raw)
        reasoning = (parsed or {}).get("reasoning", "")
        other_value = (parsed or {}).get(other_key, "")
        combined_text = f"{reasoning} {other_value}".strip()
        is_compliant, violations = validate_ugf(combined_text) if combined_text else (False, ["empty_response"])

    record = {
        "id": assignment["id"],
        "track": track,
        "depth": depth,
        "reasoning": reasoning,
        other_key: other_value,
        "compliant": is_compliant,
        "remaining_violations": violations if not is_compliant else [],
        "source_model": teacher["id"],
        "prompt_text": assignment["prompt_text"],
    }

    if track == "logic":
        truth = assignment["puzzle"]["is_valid"]
        verdict_check = _verify_logic(parsed or {}, truth)
        record["expected"] = verdict_check["expected"]
        record["extracted"] = verdict_check["extracted"]
        record["correct"] = verdict_check["correct"]
        record["puzzle_rule"] = assignment["puzzle"]["rule"]
        record["scenario"] = assignment["puzzle"]["scenario"]

    return record


# ---------------------------------------------------------------------------
# Progress / writer / runner
# ---------------------------------------------------------------------------

def load_completed_ids(progress_path: Path) -> set[str]:
    if progress_path.exists():
        with open(progress_path) as f:
            return set(json.load(f).get("completed_ids", []))
    return set()


def save_progress(progress_path: Path, completed_ids: set[str], stats: dict):
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    with open(progress_path, "w") as f:
        json.dump({
            "completed_ids": list(completed_ids),
            "stats": stats,
            "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        }, f)


async def run(output_path: Path, progress_path: Path,
              logic_n: int, philosophy_n: int,
              philosophy_topics_path: Path | None,
              dry_run: bool = False) -> None:
    global _RATE_LIMITER
    _RATE_LIMITER, _sched = make_bucket(CONFIG)
    if _sched is not None:
        asyncio.create_task(rate_schedule_ticker(_RATE_LIMITER, _sched))

    assignments: list[dict] = []
    if logic_n > 0:
        print(f"Building {logic_n} logic-track assignments...")
        assignments.extend(make_logic_assignments(logic_n))
    if philosophy_n > 0:
        if philosophy_topics_path is None:
            raise SystemExit("--philosophy-topics PATH is required when --philosophy-n > 0")
        print(f"Loading philosophy topics from {philosophy_topics_path}...")
        topics = load_philosophy_topics(
            philosophy_topics_path, philosophy_n,
            exclude_track="logic_critical_thinking",
        )
        print(f"  sampled {len(topics)} topics")
        assignments.extend(make_philosophy_assignments(topics))

    assign_teachers(assignments, TEACHERS)
    completed = load_completed_ids(progress_path)
    remaining = [a for a in assignments if a["id"] not in completed]
    print(f"Total assignments: {len(assignments)}; remaining after resume: {len(remaining)}")
    if dry_run:
        for a in remaining[:5]:
            print(f"  [{a['track']}/{a['depth']}] [{a['teacher_id']}] {a['prompt_text'][:80]}")
        return

    if not MINDROUTER_API_KEY:
        raise SystemExit("MINDROUTER_API_KEY not set")

    from collections import Counter
    share = Counter(a["teacher_id"] for a in remaining)
    track_share = Counter(a["track"] for a in remaining)
    print(f"By track: {dict(track_share)}")
    for t in TEACHERS:
        n = share.get(t["id"], 0)
        pct = (n / len(remaining) * 100) if remaining else 0
        print(f"  {t['id']:35} concurrency={t['max_concurrent']:<3} share={n} ({pct:.1f}%)")

    # Producer-consumer (per-teacher queues + single writer)
    per_teacher_queues: dict[str, asyncio.Queue] = {
        t["id"]: asyncio.Queue() for t in TEACHERS
    }
    for a in remaining:
        per_teacher_queues[a["teacher_id"]].put_nowait(a)
    results_queue: asyncio.Queue = asyncio.Queue(maxsize=1024)

    stats: dict = {
        "completed": len(completed),
        "compliant": 0,
        "non_compliant": 0,
        "failed": 0,
        "logic_correct": 0,
        "logic_incorrect": 0,
        "logic_unparseable": 0,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    connector = aiohttp.TCPConnector(ssl=False, limit=0)

    async def teacher_worker(teacher, session):
        q = per_teacher_queues[teacher["id"]]
        sem = asyncio.Semaphore(1)
        while True:
            try:
                a = q.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                r = await generate_one(session, a, teacher, sem)
            except Exception as e:
                print(f"  worker err ({teacher['id']}): {type(e).__name__}: {e}")
                r = None
            await results_queue.put((a, r))

    async def writer(total: int):
        done = 0
        last_save = 0
        with open(output_path, "a", encoding="utf-8") as out_f:
            while done < total:
                a, r = await results_queue.get()
                done += 1
                if r is None:
                    stats["failed"] += 1
                else:
                    if r["compliant"]:
                        stats["compliant"] += 1
                    else:
                        stats["non_compliant"] += 1
                    if a["track"] == "logic":
                        if r.get("correct") is True:
                            stats["logic_correct"] += 1
                        elif r.get("correct") is False:
                            stats["logic_incorrect"] += 1
                        else:
                            stats["logic_unparseable"] += 1
                    out_f.write(json.dumps(r, ensure_ascii=False) + "\n")
                    out_f.flush()
                    completed.add(a["id"])

                if done - last_save >= 100 or done == total:
                    save_progress(progress_path, completed, stats)
                    last_save = done
                    rate = done / max(1, (time.time() - t0)) * 60
                    pct = done / total * 100
                    summary = (
                        f"[{time.strftime('%H:%M:%S')}] {done}/{total} ({pct:.1f}%) "
                        f"compl {stats['compliant']} | non-compl {stats['non_compliant']} | "
                        f"fail {stats['failed']}"
                    )
                    if stats["logic_correct"] or stats["logic_incorrect"]:
                        ok = stats["logic_correct"]
                        bad = stats["logic_incorrect"]
                        total_judged = ok + bad
                        acc = ok / total_judged if total_judged else 0
                        summary += f" | logic-acc {acc:.0%} ({ok}/{total_judged})"
                    summary += f" | {rate:.0f}/min"
                    print(summary, flush=True)

    t0 = time.time()
    async with aiohttp.ClientSession(connector=connector) as session:
        worker_tasks = []
        for t in TEACHERS:
            n_workers = t["max_concurrent"]
            for _ in range(n_workers):
                worker_tasks.append(asyncio.create_task(teacher_worker(t, session)))
        writer_task = asyncio.create_task(writer(len(remaining)))
        await writer_task
        for w in worker_tasks:
            w.cancel()

    save_progress(progress_path, completed, stats)
    print(f"Done. Stats: {stats}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--logic-n", type=int, default=50000)
    parser.add_argument("--philosophy-n", type=int, default=50000)
    parser.add_argument(
        "--philosophy-topics",
        default="corpus/processed/english_passages.jsonl",
        help="JSONL with `text` field; records with metadata.track=logic_critical_thinking are excluded.",
    )
    parser.add_argument(
        "--output",
        default="corpus/processed/ugf_cot.jsonl",
    )
    parser.add_argument(
        "--progress",
        default="corpus/processed/cot_progress.json",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    asyncio.run(run(
        output_path=Path(args.output),
        progress_path=Path(args.progress),
        logic_n=args.logic_n,
        philosophy_n=args.philosophy_n,
        philosophy_topics_path=Path(args.philosophy_topics) if args.philosophy_n > 0 else None,
        dry_run=args.dry_run,
    ))


if __name__ == "__main__":
    main()
