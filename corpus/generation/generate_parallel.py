"""
Generate parallel English <-> UGF corpus via MindRouter API.

For each English passage from the extracted sources, generates an Up Goer Five
translation using gpt-oss-120b with a validation loop: the tokenizer checks
the output for vocabulary violations, and the model is re-prompted up to
max_validation_retries times to fix them.

Output: JSONL with {id, english, ugf, metadata, validation_attempts, compliant}

Features:
  - Async with configurable concurrency (semaphore)
  - Streaming writes (append-mode JSONL) for crash recovery
  - Progress tracking with resume support
  - Exponential backoff on API errors

Usage:
  python corpus/generation/generate_parallel.py [--dry-run] [--limit N]
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import aiohttp
import yaml
from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from corpus.generation.validate_ugf import validate_ugf, build_correction_prompt

# --- Load config ---
CONFIG_PATH = Path(__file__).parent / "config.yaml"
with open(CONFIG_PATH) as f:
    CONFIG = yaml.safe_load(f)

# Load API key from .env if present
load_dotenv(Path(__file__).parent.parent.parent / ".env")

MINDROUTER_BASE_URL = CONFIG["mindrouter"]["base_url"]
MINDROUTER_API_KEY = os.environ.get("MINDROUTER_API_KEY", "")
MODEL = CONFIG["mindrouter"]["model"]
MAX_CONCURRENT = CONFIG["mindrouter"]["max_concurrent"]
MAX_RETRIES = CONFIG["mindrouter"]["max_retries"]
RETRY_BACKOFF = CONFIG["mindrouter"]["retry_backoff_base"]

PARALLEL_CONFIG = CONFIG["generation"]["parallel"]
INPUT_PATH = Path(__file__).parent.parent.parent / PARALLEL_CONFIG["input_path"]
OUTPUT_PATH = Path(__file__).parent.parent.parent / PARALLEL_CONFIG["output_path"]
PROGRESS_PATH = Path(__file__).parent.parent.parent / PARALLEL_CONFIG["progress_path"]
MAX_VALIDATION_RETRIES = PARALLEL_CONFIG["max_validation_retries"]
MAX_TOKENS = PARALLEL_CONFIG["max_tokens"]
TEMPERATURE = PARALLEL_CONFIG["temperature"]

# Load the word list for the system prompt (just the words, not the full vocab)
WORDLIST_PATH = Path(__file__).parent.parent.parent / "wordlist" / "vocab_words_only.txt"


def load_wordlist_excerpt() -> str:
    """Load a representative sample of the word list for the system prompt.

    The full 3,600-word list is too long for a system prompt. Instead, we
    provide instructions and a sample, relying on the model's knowledge
    of common English words + our validation loop to catch mistakes.
    """
    words = WORDLIST_PATH.read_text().strip().split("\n")
    # Include first 200 words as a sample (they're sorted alphabetically)
    sample = words[:200]
    return (
        f"The allowed word list contains {len(words)} forms of the 1,000 most "
        f"common English words (all grammatical forms included, e.g., 'walk', "
        f"'walked', 'walking' are all allowed). Here are the first 200 to give "
        f"you the flavor:\n\n"
        + ", ".join(sample)
        + "\n\n"
        f"The full list includes common words like: the, is, was, have, do, "
        f"say, go, get, make, know, think, take, see, come, want, look, use, "
        f"find, give, tell, work, call, try, ask, need, feel, become, leave, "
        f"put, mean, keep, let, begin, show, hear, play, run, move, live, "
        f"believe, hold, bring, happen, write, sit, stand, lose, pay, meet, "
        f"include, continue, set, learn, change, lead, understand, watch, "
        f"follow, stop, create, speak, read, allow, add, spend, grow, open, "
        f"walk, offer, remember, love, consider, appear, buy, wait, die, "
        f"send, build, stay, fall, cut, reach, kill, remain, suggest, raise, "
        f"pass, sell, require, report, pull, turn, wish, drop, develop, "
        f"receive, agree, return, draw, hope, pick, eat, carry, drive, "
        f"wear, drink, hot, cold, hard, fast, small, big, old, young, "
        f"good, bad, right, wrong, true, high, low, long, short, early, late, "
        f"possible, important, different, another, together, enough, however, "
        f"already, actually, probably, especially, sometimes, certainly, "
        f"between, around, though, perhaps, because, before, after, until, "
        f"against, during, without, within.\n\n"
        f"Words NOT allowed include most technical, academic, or specialized "
        f"vocabulary. For example: 'philosophy', 'argument', 'premise', "
        f"'conclusion', 'fallacy', 'probability', 'utility', 'equilibrium', "
        f"'deontological', 'consequentialism', 'inference', 'hypothesis', "
        f"'correlation', 'variable', 'cognitive', 'bias', 'rational', etc.\n\n"
        f"Also NOT allowed (commonly mistaken as simple enough): "
        f"'link', 'linked', 'links', 'type', 'direct', 'data', 'test', "
        f"'result', 'example', 'common', 'rule', 'rules', 'false', 'plain', "
        f"'tool', 'apart', 'plant', 'juice', 'ill', 'fourth', 'fifth', "
        f"'sixth', 'conclusion'. Use allowed-word descriptions instead."
    )


SYSTEM_PROMPT = """You are a translator. Your job is to rewrite English text using ONLY \
the most common words in English -- specifically, the "Up Goer Five" word list \
(the ten hundred most used words and their grammatical forms).

RULES:
1. Use ONLY words from the allowed list. All grammatical forms of allowed words \
are permitted (e.g., if "think" is allowed, so are "thinks", "thinking", "thought").
2. When a concept has no direct simple word, DESCRIBE it using allowed words. \
For example: "equilibrium" -> "the point where things stop changing" or \
"hypothesis" -> "a guess about what is true".
3. Preserve the meaning and logical structure as faithfully as possible.
4. It is OK if the translation is longer than the original -- that is expected.
5. Do NOT use any word not on the list, even if it seems common.
6. Numbers (0-9) and basic punctuation (. , ! ? ; : - ' " ( )) are allowed.
7. Do NOT use markdown formatting. No asterisks (*), no bold, no italic, no \
headers. Use plain text only.
8. Single letters used as variable names (A, B, C, etc.) must be replaced with \
numbered descriptions like "the first thing", "the second thing", "the third \
thing", "thing number four", "thing number five", "thing number six", etc. \
Ordinals like "fourth", "fifth", "sixth" are NOT allowed -- use "thing number \
four" or "the one after the third" instead.

{wordlist_info}"""


def build_translation_prompt(english_text: str) -> str:
    return (
        f"Translate this text into Up Goer Five language (using only the "
        f"ten hundred most common words):\n\n"
        f"{english_text}\n\n"
        f"Up Goer Five translation:"
    )


def load_progress() -> set[str]:
    """Load IDs of already-processed passages."""
    if PROGRESS_PATH.exists():
        with open(PROGRESS_PATH) as f:
            data = json.load(f)
        return set(data.get("completed_ids", []))
    return set()


def save_progress(completed_ids: set[str], stats: dict):
    """Save progress to disk."""
    with open(PROGRESS_PATH, "w") as f:
        json.dump({
            "completed_ids": list(completed_ids),
            "stats": stats,
            "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        }, f)


async def api_call(
    session: aiohttp.ClientSession,
    messages: list[dict],
    semaphore: asyncio.Semaphore,
) -> str | None:
    """Make a single API call with retries and backoff."""
    url = f"{MINDROUTER_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {MINDROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    # gpt-oss-120b has thinking mode — it uses tokens for reasoning_content
    # before producing content. The thinking is valuable: the model reasons
    # about how to express complex concepts in simple words, which is exactly
    # what we need for high-quality training data. Budget generously.
    payload = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": MAX_TOKENS + 12288,  # generous budget: thinking IS the work
        "temperature": TEMPERATURE,
    }

    for attempt in range(MAX_RETRIES):
        async with semaphore:
            try:
                async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=360)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        content = data["choices"][0]["message"].get("content")
                        if content is None:
                            # Model spent all tokens on reasoning, no content produced
                            print("  Warning: content was null (thinking used all tokens)")
                            return None
                        return content.strip()
                    elif resp.status == 429:
                        wait = RETRY_BACKOFF * (2 ** attempt)
                        print(f"  Rate limited, waiting {wait:.1f}s...")
                        await asyncio.sleep(wait)
                    else:
                        text = await resp.text()
                        print(f"  API error {resp.status}: {text[:200]}")
                        await asyncio.sleep(RETRY_BACKOFF * (2 ** attempt))
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                print(f"  Request error: {e}")
                await asyncio.sleep(RETRY_BACKOFF * (2 ** attempt))

    return None


async def translate_passage(
    session: aiohttp.ClientSession,
    passage: dict,
    system_prompt: str,
    semaphore: asyncio.Semaphore,
) -> dict | None:
    """Translate a single passage with validation loop."""
    english_text = passage["text"]

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": build_translation_prompt(english_text)},
    ]

    ugf_text = await api_call(session, messages, semaphore)
    if ugf_text is None:
        return None

    # Validation loop
    for retry in range(MAX_VALIDATION_RETRIES):
        is_valid, violations = validate_ugf(ugf_text)
        if is_valid:
            return {
                "id": passage["id"],
                "english": english_text,
                "ugf": ugf_text,
                "metadata": passage.get("metadata", {}),
                "validation_attempts": retry + 1,
                "compliant": True,
            }

        # Build correction prompt and retry
        correction = build_correction_prompt(english_text, ugf_text, violations)
        messages.append({"role": "assistant", "content": ugf_text})
        messages.append({"role": "user", "content": correction})

        ugf_text = await api_call(session, messages, semaphore)
        if ugf_text is None:
            return None

    # Final check after all retries
    is_valid, violations = validate_ugf(ugf_text)
    return {
        "id": passage["id"],
        "english": english_text,
        "ugf": ugf_text,
        "metadata": passage.get("metadata", {}),
        "validation_attempts": MAX_VALIDATION_RETRIES + 1,
        "compliant": is_valid,
        "remaining_violations": violations if not is_valid else [],
    }


async def main(
    dry_run: bool = False,
    limit: int | None = None,
    input_path: Path | None = None,
    output_path: Path | None = None,
    progress_path: Path | None = None,
):
    global INPUT_PATH, OUTPUT_PATH, PROGRESS_PATH
    if input_path is not None:
        INPUT_PATH = input_path
    if output_path is not None:
        OUTPUT_PATH = output_path
    if progress_path is not None:
        PROGRESS_PATH = progress_path

    print(f"Input:    {INPUT_PATH}")
    print(f"Output:   {OUTPUT_PATH}")
    print(f"Progress: {PROGRESS_PATH}")

    # Load passages
    passages = []
    with open(INPUT_PATH) as f:
        for line in f:
            passages.append(json.loads(line))

    if limit:
        passages = passages[:limit]

    # Resume support
    completed_ids = load_progress()
    remaining = [p for p in passages if p["id"] not in completed_ids]

    print(f"Total passages: {len(passages)}")
    print(f"Already completed: {len(completed_ids)}")
    print(f"Remaining: {len(remaining)}")

    if dry_run:
        print("\n[DRY RUN] Would translate first 3 passages:")
        for p in remaining[:3]:
            print(f"  {p['id']}: {p['text'][:80]}...")
        return

    if not MINDROUTER_API_KEY:
        print("ERROR: MINDROUTER_API_KEY not set. Set it in .env or environment.")
        sys.exit(1)

    wordlist_info = load_wordlist_excerpt()
    system_prompt = SYSTEM_PROMPT.format(wordlist_info=wordlist_info)

    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    stats = {"completed": len(completed_ids), "compliant": 0, "non_compliant": 0, "failed": 0}

    # Open output file in append mode
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    # MindRouter uses a self-signed certificate (campus-internal service)
    ssl_ctx = False  # disable SSL verification for aiohttp
    connector = aiohttp.TCPConnector(ssl=ssl_ctx)
    async with aiohttp.ClientSession(connector=connector) as session:
        # Process in batches to manage memory and save progress
        batch_size = 100
        for batch_start in range(0, len(remaining), batch_size):
            batch = remaining[batch_start:batch_start + batch_size]

            tasks = [
                translate_passage(session, p, system_prompt, semaphore)
                for p in batch
            ]
            results = await asyncio.gather(*tasks)

            # Write results and update progress
            with open(OUTPUT_PATH, "a", encoding="utf-8") as f:
                for result in results:
                    if result is None:
                        stats["failed"] += 1
                        continue
                    f.write(json.dumps(result, ensure_ascii=False) + "\n")
                    completed_ids.add(result["id"])
                    if result["compliant"]:
                        stats["compliant"] += 1
                    else:
                        stats["non_compliant"] += 1

            stats["completed"] = len(completed_ids)
            save_progress(completed_ids, stats)

            total_done = batch_start + len(batch)
            pct = total_done / len(remaining) * 100
            print(
                f"  [{total_done}/{len(remaining)}] ({pct:.1f}%) "
                f"compliant={stats['compliant']} "
                f"non_compliant={stats['non_compliant']} "
                f"failed={stats['failed']}"
            )

    print(f"\nDone. Final stats: {json.dumps(stats, indent=2)}")
    print(f"Output: {OUTPUT_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate parallel English-UGF corpus")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be translated")
    parser.add_argument("--limit", type=int, help="Limit number of passages to translate")
    parser.add_argument("--input-path", type=Path,
                        help="Override input english_passages.jsonl path")
    parser.add_argument("--output-path", type=Path,
                        help="Override output parallel_corpus.jsonl path")
    parser.add_argument("--progress-path", type=Path,
                        help="Override progress json path")
    args = parser.parse_args()

    asyncio.run(main(
        dry_run=args.dry_run,
        limit=args.limit,
        input_path=args.input_path,
        output_path=args.output_path,
        progress_path=args.progress_path,
    ))
