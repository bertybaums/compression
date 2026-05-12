"""
Generate the form-diverse UGF corpus by extracting (prompt, response) pairs
from parsed public-domain philosophical texts.

This is the production pipeline that implements `docs/followups/corpus-diversification.md`.
It reads JSONL files of source-text pairs (one record per source pair, parsed
by `corpus/poc/parse_*.py`), applies form-specific extraction prompts (from
`corpus/generation/forms.py`), and writes UGF (prompt, response) training
pairs to a single corpus output file.

Pipeline features:
  - Multi-teacher dispatch (ensemble of MR-hosted models with per-teacher
    concurrency caps and weighted sampling)
  - Process-global token-bucket rate limiter (shared with all generation
    pipelines that hit MR; defaults to MR's 200 rpm institutional cap)
  - Per-form retry-on-violations loop with correction prompts
  - Per-form few-shot exemplars injected as in-context turns
  - Progress tracking + resumable runs (per-source JSON progress files keyed
    by source-pair id)
  - JSON output discipline (each (prompt, response) is parsed from a JSON
    object returned by the teacher; non-JSON failures are logged and skipped)

Output schema (one JSONL record per successful extraction):
  {
    "id": "meno_pair_001",
    "source": "plato_meno",          # source-text label
    "form": "dialogue",              # one of forms.FORMS keys
    "prompt": "...",                 # UGF prompt text (the Reasoner's input)
    "response": "...",               # UGF response text (the Reasoner's target)
    "teacher": "openai/gpt-oss-120b",
    "compliant": true,
    "remaining_violations": [],
    "metadata": {...},               # form-specific provenance (speakers,
                                     # article title, descriptor map, etc.)
  }

Usage:
  python corpus/generation/generate_forms.py \\
      --sources sources.yaml          # see docs for the schema
      --output corpus/processed/ugf_forms_corpus.jsonl \\
      --progress-dir corpus/processed/forms_progress \\
      [--limit-per-source N] [--dry-run]
"""

import argparse
import asyncio
import datetime
import json
import os
import random
import sys
import time
import zoneinfo
from collections import Counter
from pathlib import Path

import aiohttp
import yaml
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from corpus.generation.validate_ugf import validate_ugf, normalize_unicode
from corpus.generation.forms import FORMS, build_user_message
from corpus.generation.rate_limiter import (
    AsyncTokenBucket, make_bucket, rate_schedule_ticker,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CONFIG_PATH = Path(__file__).parent / "config.yaml"
with open(CONFIG_PATH) as f:
    CONFIG = yaml.safe_load(f)

load_dotenv(Path(__file__).parent.parent.parent / ".env")

MR_URL = f"{CONFIG['mindrouter']['base_url']}/chat/completions"
MR_KEY = os.environ.get("MINDROUTER_API_KEY", "")
MAX_RETRIES_API = CONFIG["mindrouter"]["max_retries"]
RETRY_BACKOFF = CONFIG["mindrouter"]["retry_backoff_base"]
MAX_REQ_PER_MINUTE = CONFIG["mindrouter"].get("max_req_per_minute", 100)
BURST_CAPACITY = CONFIG["mindrouter"].get("burst_capacity", 10)
RATE_SCHEDULE = CONFIG["mindrouter"].get("rate_schedule")

# Teacher ensemble: same shape as reasoning_teachers in config.yaml; if the
# generation runner is given an override path it loads from there instead.
DEFAULT_TEACHERS = CONFIG["mindrouter"].get("reasoning_teachers", [])
if not DEFAULT_TEACHERS:
    DEFAULT_TEACHERS = [{
        "id": CONFIG["mindrouter"]["model"],
        "weight": 100,
        "max_concurrent": CONFIG["mindrouter"].get("max_concurrent", 5),
        "max_tokens_overhead": 8192,
        "reasoning_effort": "medium",
    }]

# Output budget per call. Form extraction passes the source twice (once in
# the user prompt, once paraphrased in the output); plus gpt-oss reasoning
# tokens. v1 used 2048 + per-teacher overhead; we budget more here because
# the user prompt can be ~600 words (long Hume passages).
MAX_OUTPUT_TOKENS = 4096
TEMPERATURE = 0.7
MAX_VALIDATION_RETRIES = 3  # number of correction-prompt re-attempts

# ---------------------------------------------------------------------------
# Rate limiter (process-global; same pattern as generate_reasoning.py)
# ---------------------------------------------------------------------------

_RATE_LIMITER: AsyncTokenBucket | None = None

# ---------------------------------------------------------------------------
# MR API call
# ---------------------------------------------------------------------------

async def api_call(
    session: aiohttp.ClientSession,
    messages: list[dict],
    teacher: dict,
) -> str | None:
    """Single chat-completion call to a teacher. Returns content string, or
    None if the call exhausted retries / returned null content."""
    payload = {
        "model": teacher["id"],
        "messages": messages,
        "max_tokens": MAX_OUTPUT_TOKENS + teacher.get("max_tokens_overhead", 0),
        "temperature": TEMPERATURE,
    }
    if "reasoning_effort" in teacher:
        payload["reasoning_effort"] = teacher["reasoning_effort"]
    if "enable_thinking" in teacher:
        payload["chat_template_kwargs"] = {"enable_thinking": teacher["enable_thinking"]}

    headers = {
        "Authorization": f"Bearer {MR_KEY}",
        "Content-Type": "application/json",
    }
    tag = teacher["id"].split("/")[-1][:20]
    for attempt in range(MAX_RETRIES_API):
        if _RATE_LIMITER is not None:
            await _RATE_LIMITER.acquire()
        try:
            async with session.post(MR_URL, json=payload, headers=headers,
                                    timeout=aiohttp.ClientTimeout(total=360)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    content = data["choices"][0]["message"].get("content")
                    if content is None:
                        print(f"  [{tag}] content=null (thinking budget exhausted)", flush=True)
                        return None
                    return content.strip()
                elif resp.status == 429:
                    wait = RETRY_BACKOFF * (2 ** attempt) * 4
                    print(f"  [{tag}] 429 rate-limited, waiting {wait:.0f}s (attempt {attempt+1}/{MAX_RETRIES_API})", flush=True)
                    await asyncio.sleep(wait)
                else:
                    body = (await resp.text())[:200]
                    print(f"  [{tag}] HTTP {resp.status}: {body} (attempt {attempt+1}/{MAX_RETRIES_API})", flush=True)
                    await asyncio.sleep(RETRY_BACKOFF * (2 ** attempt))
        except asyncio.TimeoutError:
            print(f"  [{tag}] timeout (attempt {attempt+1}/{MAX_RETRIES_API})", flush=True)
            await asyncio.sleep(RETRY_BACKOFF * (2 ** attempt))
        except aiohttp.ClientError as e:
            print(f"  [{tag}] client error: {type(e).__name__}: {e} (attempt {attempt+1}/{MAX_RETRIES_API})", flush=True)
            await asyncio.sleep(RETRY_BACKOFF * (2 ** attempt))
    return None


# ---------------------------------------------------------------------------
# Per-pair extraction with retry-on-violations
# ---------------------------------------------------------------------------

def parse_extraction_output(content: str) -> tuple[bool, dict]:
    """Parse the teacher's JSON output. Returns (ok, parsed_or_error_dict)."""
    text = content.strip()
    if text.startswith("```"):
        text = "\n".join(text.splitlines()[1:])
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3].rstrip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        return False, {"error": f"JSONDecodeError: {e}", "raw": content[:300]}
    if not isinstance(obj, dict) or "prompt" not in obj or "response" not in obj:
        return False, {"error": "missing keys", "raw": content[:300]}
    p, r = obj["prompt"], obj["response"]
    if not (isinstance(p, str) and isinstance(r, str)):
        return False, {"error": "non-string values", "raw": content[:300]}
    return True, {"prompt": normalize_unicode(p), "response": normalize_unicode(r)}


def validate_pair(prompt: str, response: str) -> tuple[bool, list[str]]:
    """Run UGF validation on both halves; return (overall_ok, combined_violations)."""
    p_ok, p_viol = validate_ugf(prompt)
    r_ok, r_viol = validate_ugf(response)
    return p_ok and r_ok, p_viol + r_viol


async def extract_one(
    session: aiohttp.ClientSession,
    pair: dict,
    form: str,
    teacher: dict,
) -> dict | None:
    """Extract a single (UGF prompt, UGF response) pair from a source pair.

    Returns a result record (compliant or remaining-violations); returns None
    only if every retry path failed at the API level (rare)."""
    spec = FORMS[form]
    user_msg = build_user_message(form, pair)

    messages: list[dict] = [{"role": "system", "content": spec["system_prompt"]}]
    for ex_user, ex_assistant in spec.get("few_shot", []):
        messages.append({"role": "user", "content": ex_user})
        messages.append({"role": "assistant", "content": ex_assistant})
    messages.append({"role": "user", "content": user_msg})

    raw = await api_call(session, messages, teacher)
    if raw is None:
        return None
    parsed_ok, parsed = parse_extraction_output(raw)
    if not parsed_ok:
        # JSON failure: one retry with a clarifying request before giving up.
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content":
            "Your previous reply could not be parsed as JSON. "
            "Output ONLY a single JSON object on one line with exactly two keys: \"prompt\" and \"response\". "
            "No commentary, no markdown fencing, no extra fields."
        })
        raw2 = await api_call(session, messages, teacher)
        if raw2 is None:
            return _failure_record(pair, form, teacher, "api_failed_after_json_retry")
        parsed_ok, parsed = parse_extraction_output(raw2)
        if not parsed_ok:
            return _failure_record(pair, form, teacher, f"json_parse_failed: {parsed.get('error', '?')}")
        raw = raw2

    prompt_text, response_text = parsed["prompt"], parsed["response"]
    ok, violations = validate_pair(prompt_text, response_text)

    # Retry-on-violations: per-form correction prompt
    correction_template = spec["correction_template"]
    for _ in range(MAX_VALIDATION_RETRIES):
        if ok:
            break
        viol_str = ", ".join(f'"{v}"' for v in violations[:20])
        if len(violations) > 20:
            viol_str += f" (and {len(violations) - 20} more)"
        correction = correction_template.format(violations=viol_str)
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": correction})
        raw = await api_call(session, messages, teacher)
        if raw is None:
            break
        parsed_ok, parsed = parse_extraction_output(raw)
        if not parsed_ok:
            # If we lose JSON discipline during correction, abort retry loop
            # and report current best.
            break
        prompt_text, response_text = parsed["prompt"], parsed["response"]
        ok, violations = validate_pair(prompt_text, response_text)

    return {
        "id": pair["id"],
        "form": form,
        "prompt": prompt_text,
        "response": response_text,
        "teacher": teacher["id"],
        "compliant": ok,
        "remaining_violations": violations if not ok else [],
        # Provenance: include every key from the source pair (descriptors,
        # speaker labels, article titles, etc.) so the output is auditable.
        "metadata": {k: v for k, v in pair.items() if k != "id"},
    }


def _failure_record(pair: dict, form: str, teacher: dict, reason: str) -> dict:
    return {
        "id": pair["id"],
        "form": form,
        "teacher": teacher["id"],
        "compliant": False,
        "failed": True,
        "failure_reason": reason,
        "metadata": {k: v for k, v in pair.items() if k != "id"},
    }


# ---------------------------------------------------------------------------
# Source loading + teacher assignment
# ---------------------------------------------------------------------------

def load_sources(sources_config: list[dict], limit_per_source: int | None) -> list[dict]:
    """Each source entry: {label: str, path: Path, form: str}.
    Returns flat list of pairs, each tagged with `source` and `form`."""
    pairs = []
    for s in sources_config:
        path = Path(s["path"])
        label = s["label"]
        form = s["form"]
        if not path.exists():
            print(f"WARNING: source path not found: {path} (skipping)", flush=True)
            continue
        with open(path) as f:
            n = 0
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                rec["source"] = label
                rec["form"] = form
                pairs.append(rec)
                n += 1
                if limit_per_source and n >= limit_per_source:
                    break
        print(f"  loaded {n} pairs from {label} ({form}) at {path}", flush=True)
    return pairs


def assign_teachers(pairs: list[dict], teachers: list[dict], seed: int = 42) -> None:
    """In-place assignment of teacher_id to each pair via weighted sampling."""
    rng = random.Random(seed)
    weights = [t["weight"] for t in teachers]
    ids = [t["id"] for t in teachers]
    for p in pairs:
        p["teacher_id"] = rng.choices(ids, weights=weights, k=1)[0]


def load_progress(progress_path: Path) -> set[str]:
    if progress_path.exists():
        with open(progress_path) as f:
            return set(json.load(f).get("completed_ids", []))
    return set()


def save_progress(progress_path: Path, completed_ids: set[str], stats: dict):
    with open(progress_path, "w") as f:
        json.dump({
            "completed_ids": sorted(completed_ids),
            "stats": stats,
            "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        }, f, indent=2)


# ---------------------------------------------------------------------------
# Main loop: teacher workers + writer coroutine
# ---------------------------------------------------------------------------

async def main(
    sources_path: Path,
    output_path: Path,
    progress_path: Path,
    teachers: list[dict],
    limit_per_source: int | None,
    dry_run: bool,
):
    global _RATE_LIMITER
    if not MR_KEY:
        print("ERROR: MINDROUTER_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    # Rate limiter — shared module handles fixed or time-scheduled caps.
    _RATE_LIMITER, sched = make_bucket(CONFIG)
    schedule_task: asyncio.Task | None = None
    if sched is not None:
        schedule_task = asyncio.create_task(rate_schedule_ticker(_RATE_LIMITER, sched))

    # Load sources config
    with open(sources_path) as f:
        sources_config = yaml.safe_load(f)["sources"]

    print(f"Sources ({len(sources_config)}):", flush=True)
    pairs = load_sources(sources_config, limit_per_source)
    print(f"Total pairs to consider: {len(pairs)}", flush=True)

    # Tag with teacher_id (weighted sample)
    assign_teachers(pairs, teachers, seed=42)
    share = Counter(p["teacher_id"] for p in pairs)
    for t in teachers:
        n = share.get(t["id"], 0)
        pct = 100 * n / max(1, len(pairs))
        print(f"  {t['id']:35} concurrency={t['max_concurrent']:<3} share={n} ({pct:.1f}%)", flush=True)

    # Resume from progress
    completed = load_progress(progress_path)
    remaining = [p for p in pairs if p["id"] not in completed]
    print(f"Already completed: {len(completed)}", flush=True)
    print(f"Remaining: {len(remaining)}", flush=True)

    if dry_run:
        print("\n[DRY RUN] First 5 pairs:")
        for p in remaining[:5]:
            print(f"  [{p['teacher_id']}] [{p['form']}] [{p['source']}] {p['id']}")
        return

    # Build per-teacher work queues
    by_teacher: dict[str, list[dict]] = {t["id"]: [] for t in teachers}
    for p in remaining:
        by_teacher[p["teacher_id"]].append(p)

    # Per-teacher semaphores cap concurrent in-flight calls. The global rate
    # limiter still applies, so total throughput stays below MAX_REQ_PER_MINUTE
    # regardless of how aggressive per-teacher concurrency is.
    semaphores: dict[str, asyncio.Semaphore] = {
        t["id"]: asyncio.Semaphore(t["max_concurrent"]) for t in teachers
    }
    teachers_by_id = {t["id"]: t for t in teachers}

    output_path.parent.mkdir(parents=True, exist_ok=True)
    progress_path.parent.mkdir(parents=True, exist_ok=True)

    output_f = output_path.open("a", encoding="utf-8")
    stats = {"compliant": 0, "non_compliant": 0, "failed": 0, "by_form": Counter(),
             "by_teacher": Counter()}
    completed_ids = set(completed)
    results_q: asyncio.Queue = asyncio.Queue(maxsize=200)

    async def teacher_worker(teacher: dict, session: aiohttp.ClientSession):
        sem = semaphores[teacher["id"]]
        my_pairs = by_teacher[teacher["id"]]
        async def run_one(pair):
            async with sem:
                result = await extract_one(session, pair, pair["form"], teacher)
            # Every pair must produce SOMETHING on the queue — otherwise the
            # writer (which counts to len(remaining)) hangs forever waiting on
            # hard-API-failure pairs that silently returned None.
            if result is None:
                result = _failure_record(pair, pair["form"], teacher, "api_failed_after_max_retries")
            result["source"] = pair["source"]
            await results_q.put(result)
        await asyncio.gather(*(run_one(p) for p in my_pairs))

    async def writer(total_expected: int):
        n_written = 0
        progress_save_every = 50
        while n_written < total_expected:
            rec = await results_q.get()
            output_f.write(json.dumps(rec) + "\n")
            output_f.flush()
            completed_ids.add(rec["id"])
            if rec.get("failed"):
                stats["failed"] += 1
            elif rec["compliant"]:
                stats["compliant"] += 1
            else:
                stats["non_compliant"] += 1
            stats["by_form"][rec["form"]] += 1
            stats["by_teacher"][rec["teacher"]] += 1
            n_written += 1
            if n_written % 25 == 0:
                pct = 100 * n_written / total_expected
                comp_pct = 100 * stats["compliant"] / max(1, n_written - stats["failed"])
                print(f"  [{time.strftime('%H:%M:%S')}] {n_written}/{total_expected} ({pct:.1f}%) | compliant {stats['compliant']} ({comp_pct:.0f}%) | non-compliant {stats['non_compliant']} | failed {stats['failed']}", flush=True)
            if n_written % progress_save_every == 0:
                save_progress(progress_path, completed_ids, stats)
        save_progress(progress_path, completed_ids, stats)

    connector = aiohttp.TCPConnector(ssl=False, limit=0)
    async with aiohttp.ClientSession(connector=connector) as session:
        worker_tasks = [asyncio.create_task(teacher_worker(t, session)) for t in teachers]
        writer_task = asyncio.create_task(writer(len(remaining)))
        await asyncio.gather(*worker_tasks)
        await writer_task

    if schedule_task is not None:
        schedule_task.cancel()
        try:
            await schedule_task
        except asyncio.CancelledError:
            pass

    output_f.close()
    print()
    print(f"=== Done ===")
    print(f"Compliant: {stats['compliant']} ({100 * stats['compliant'] / max(1, len(remaining)):.1f}%)")
    print(f"Non-compliant: {stats['non_compliant']}")
    print(f"Failed: {stats['failed']}")
    print(f"By form: {dict(stats['by_form'])}")
    print(f"By teacher: {dict(stats['by_teacher'])}")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", type=Path, required=True,
                    help="YAML file listing source pair JSONLs and their forms")
    ap.add_argument("--output", type=Path,
                    default=Path("corpus/processed/ugf_forms_corpus.jsonl"))
    ap.add_argument("--progress", type=Path,
                    default=Path("corpus/processed/forms_progress.json"))
    ap.add_argument("--teachers", type=Path, default=None,
                    help="Optional JSON file overriding the teacher ensemble")
    ap.add_argument("--limit-per-source", type=int, default=None,
                    help="Cap on pairs per source (for testing)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.teachers and args.teachers.exists():
        with open(args.teachers) as f:
            teachers = json.load(f)
        print(f"Teachers overridden from {args.teachers}")
    else:
        teachers = DEFAULT_TEACHERS
    print(f"Using {len(teachers)} teacher(s).")

    asyncio.run(main(
        sources_path=args.sources,
        output_path=args.output,
        progress_path=args.progress,
        teachers=teachers,
        limit_per_source=args.limit_per_source,
        dry_run=args.dry_run,
    ))
