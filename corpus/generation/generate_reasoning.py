"""
Generate pure UGF reasoning traces for the Reasoner model.

Two-stage approach:
  Stage A: Generate English reasoning traces (CoT, explanations, dialogues)
  Stage B: Translate them to UGF using the same validation loop

Also generates direct UGF reasoning for diversity.

Content types:
  1. concept_explanation - Explain a concept step by step
  2. chain_of_thought - Work through a problem with explicit reasoning
  3. socratic_dialogue - Two speakers discuss a topic, Q&A style
  4. argument_analysis - Break down an argument's structure
  5. thought_experiment - Walk through a philosophical scenario

Output: JSONL with {id, ugf_text, content_type, topic, metadata, compliant}

Usage:
  python corpus/generation/generate_reasoning.py [--dry-run] [--limit N]
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

from corpus.generation.validate_ugf import validate_ugf, build_correction_prompt

# --- Config ---
CONFIG_PATH = Path(__file__).parent / "config.yaml"
with open(CONFIG_PATH) as f:
    CONFIG = yaml.safe_load(f)

load_dotenv(Path(__file__).parent.parent.parent / ".env")

MINDROUTER_BASE_URL = CONFIG["mindrouter"]["base_url"]
MINDROUTER_API_KEY = os.environ.get("MINDROUTER_API_KEY", "")
MAX_RETRIES = CONFIG["mindrouter"]["max_retries"]
RETRY_BACKOFF = CONFIG["mindrouter"]["retry_backoff_base"]

# Teacher ensemble: list of dicts with id, weight, max_concurrent, max_tokens_overhead.
# Falls back to single-model config for backward compat.
TEACHERS = CONFIG["mindrouter"].get("reasoning_teachers")
if not TEACHERS:
    TEACHERS = [{
        "id": CONFIG["mindrouter"]["model"],
        "weight": 100,
        "max_concurrent": CONFIG["mindrouter"].get("max_concurrent", 8),
        "max_tokens_overhead": 3072,
    }]

REASONING_CONFIG = CONFIG["generation"]["reasoning"]
DEFAULT_OUTPUT_PATH = Path(__file__).parent.parent.parent / REASONING_CONFIG["output_path"]
DEFAULT_PROGRESS_PATH = Path(__file__).parent.parent.parent / REASONING_CONFIG["progress_path"]
MAX_TOKENS = REASONING_CONFIG["max_tokens"]
TEMPERATURE = REASONING_CONFIG["temperature"]

# --- Topic bank ---
# Drawn from good-thinking-bot taxonomy + intro-ethics textbook

TOPICS = {
    "logic_critical_thinking": [
        "what makes a good reason for believing something",
        "how to tell if one thing follows from another",
        "why someone's character does not decide if their point is right",
        "the difference between a strong reason and a weak reason",
        "how two things happening together does not mean one causes the other",
        "why we should not accept something just because many people believe it",
        "how to find the hidden parts of someone's case",
        "why the way a question is asked can change the answer you give",
        "what it means for a case to be put together well",
        "how to tell when someone is changing what was really said",
        "why saying something over and over does not make it true",
        "how a story about one person does not tell us about everyone",
        "the problem with thinking only two choices exist when there are more",
        "why being sure about something does not make it right",
        "how to check if your own thinking has problems",
    ],
    "decision_theory": [
        "how to pick the best choice when you are not sure what will happen",
        "why people sometimes pick the worse thing even when they know better",
        "the problem of spending more just because you already spent a lot",
        "how the way choices are shown can change what you pick",
        "why people fear losing more than they enjoy winning the same amount",
        "when it is good enough to pick something that works instead of the best thing",
        "how to think about what could happen and how likely it is",
        "why what you already believe changes how you see new things",
        "the problem with thinking you know more than you really do",
        "how to decide when the right thing to do is not clear",
    ],
    "game_theory": [
        "the problem where two people could work together but might not",
        "why everyone doing what is best for them can make things worse for all",
        "how people make deals when they will see each other again",
        "when one person doing something first changes what others do",
        "why sharing all you know is not always the best move",
        "how a group can agree on rules that are good for everyone",
        "the problem of everyone using up something that belongs to all",
        "why some deals hold together and others fall apart",
        "how to think about what the other person will do before you act",
        "when helping the group costs you but helps everyone",
    ],
    "ethics_virtue": [
        "what it means to live a good life by being a good person",
        "how doing good things over and over makes you into a good person",
        "the idea that the right thing is usually between two wrong things",
        "why being good at being a person is like being good at anything else",
        "how the kind of person you are matters more than following rules",
        "what makes someone happy in the deepest way, not just for a moment",
        "why different situations need different kinds of good character",
        "how a person can change who they are by changing what they do",
    ],
    "ethics_justice": [
        "how to build fair rules if you did not know your place in the world",
        "why some things you must never do to another person no matter what",
        "the idea that you should only follow rules everyone could agree to",
        "why treating people as things to use is always wrong",
        "how to think about what is fair when people start in different places",
        "why the rules should be the same for everyone",
        "the question of what we owe to people we will never meet",
    ],
    "ethics_consequences": [
        "the idea that the right thing to do is what leads to the most good",
        "why counting up good and bad results is harder than it sounds",
        "the problem of hurting one person to help many",
        "how to decide whose good matters and how much",
        "why what happens after you act matters for whether it was right",
        "the question of whether animals feeling pain matters as much as people",
    ],
    "ethics_care": [
        "why who someone is to you changes what you should do for them",
        "how paying close attention to what someone needs is a kind of good",
        "the idea that we are all connected and need each other",
        "why following rules is not enough if you do not care about people",
        "how taking care of others is a kind of work that matters",
    ],
    "dennett_tools": [
        "why sometimes a good enough answer is better than the best answer",
        "how some ideas stop you from thinking further",
        "the way to help yourself think about hard questions step by step",
        "why we should be careful about thinking everything happens for a reason",
        "how to build your own set of rules for making hard choices",
    ],
}

CONTENT_TYPES = {
    "concept_explanation": (
        "Write a clear explanation of the following idea. Think step by step. "
        "Make sure someone who has never studied this before could understand. "
        "Write in plain running prose -- no asterisks, no bold, no bullet lists, "
        "no numbered headers.\n\n"
        "Topic: {topic}\n\n"
        "Explanation:"
    ),
    "chain_of_thought": (
        "Work through the following problem step by step. Show your thinking "
        "at each step. Write steps as plain sentences joined into a paragraph "
        "(for example: 'First, we notice ... Then we can see ... This means ...'). "
        "Do NOT use numbered lists, bullet points, asterisks, or any markdown.\n\n"
        "Problem: {topic}\n\n"
        "Step-by-step thinking:"
    ),
    "socratic_dialogue": (
        "Write a short conversation between two people about the following topic. "
        "One person asks questions, the other explains. The conversation should "
        "go at least 6 turns. Use plain text only -- no asterisks, no bold.\n\n"
        "Topic: {topic}\n\n"
        "Conversation:\n"
        "Person 1:"
    ),
    "argument_analysis": (
        "Someone makes the following case. Break it down into its parts: what "
        "they are saying is true, what they think follows from that, and whether "
        "the thinking is good. Write this as flowing paragraphs of plain prose. "
        "Do NOT use asterisks, bold, bullet points, or numbered headers. You can "
        "refer to ideas as 'the first idea', 'the second idea', and so on inside "
        "the prose.\n\n"
        "The case: {topic}\n\n"
        "Breaking this down:"
    ),
    "thought_experiment": (
        "Walk through the following situation that makes you think. Describe what "
        "is happening, what the hard question is, and what different answers people "
        "might give and why. Write in flowing paragraphs of plain prose -- no "
        "asterisks, no bold, no bullet points, no numbered headers.\n\n"
        "Situation: {topic}\n\n"
        "Thinking through this:"
    ),
}

SYSTEM_PROMPT = """You write about hard ideas using ONLY the most common words in \
English -- specifically, the "Up Goer Five" word list (the ten hundred most used \
words and their grammatical forms).

RULES:
1. Use ONLY words from the allowed list. All grammatical forms of allowed words \
are permitted (e.g., if "think" is allowed, so are "thinks", "thinking", "thought").
2. When a concept has no direct simple word, DESCRIBE it using allowed words. \
For example: "equilibrium" -> "the point where things stop changing" or \
"hypothesis" -> "a guess about what is true".
3. Preserve meaning and logical structure as faithfully as you can.
4. Longer is fine -- it is expected that explanations in simple words are \
longer than ones using technical words.
5. Do NOT use any word not on the list, even if it seems common.
6. Numbers (0-9) and basic punctuation (. , ! ? ; : - ' " ( )) are allowed.
7. Do NOT use markdown formatting. No asterisks (*), no bold, no italic, no \
headers, no bullet points, no dashes used as list markers. Write plain running \
prose. If you need to enumerate, write the numbers as words inside sentences \
("First, we see ... Second, we note ...") rather than as lists.
8. Single letters used as variable names (A, B, C, etc.) must be replaced with \
numbered descriptions like "the first thing", "the second thing", "the third \
thing", "thing number four", "thing number five", "thing number six", etc. \
Ordinals like "fourth", "fifth", "sixth" are NOT allowed -- use "thing number \
four" or "the one after the third" instead.

Words NOT allowed include most technical, academic, or specialized vocabulary. \
For example: 'philosophy', 'argument', 'premise', 'conclusion', 'fallacy', \
'probability', 'utility', 'equilibrium', 'deontological', 'consequentialism', \
'inference', 'hypothesis', 'correlation', 'variable', 'cognitive', 'bias', \
'rational', 'ethics', 'moral', 'virtue', 'principle', 'obligation', 'autonomy', \
'justice', 'welfare', 'theory', 'logic', 'evidence'.

Also NOT allowed (commonly mistaken as simple enough): 'link', 'linked', \
'links', 'type', 'direct', 'data', 'test', 'result', 'example', 'common', \
'rule', 'rules', 'false', 'plain', 'tool', 'apart', 'plant', 'juice', 'ill', \
'fourth', 'fifth', 'sixth', 'conclusion', 'harm', 'dealt', 'deal', 'based', \
'exact', 'handle', 'handled', 'describe', 'described'. Use allowed-word \
descriptions instead (e.g. 'harm' -> 'hurt', 'based on' -> 'resting on', \
'exact' -> 'the very same', 'handle' -> 'take care of', 'describe' -> \
'tell about').

Your writing should be clear, thoughtful, and detailed."""


def generate_topic_assignments(n: int) -> list[dict]:
    """Generate N topic+content_type assignments."""
    assignments = []
    all_topics = []
    for domain, topics in TOPICS.items():
        for topic in topics:
            all_topics.append({"domain": domain, "topic": topic})

    content_type_names = list(CONTENT_TYPES.keys())

    for i in range(n):
        topic_entry = all_topics[i % len(all_topics)]
        content_type = content_type_names[i % len(content_type_names)]
        assignments.append({
            "id": f"reasoning-{i:07d}",
            "domain": topic_entry["domain"],
            "topic": topic_entry["topic"],
            "content_type": content_type,
        })

    # Shuffle for diverse batches
    random.seed(42)
    random.shuffle(assignments)
    return assignments


def assign_teachers(assignments: list[dict], teachers: list[dict],
                    seed: int = 42, equal: bool = False) -> None:
    """Attach a teacher_id to each assignment via weighted sampling.

    When equal=True, each teacher receives approximately the same number of
    assignments (for controlled pilots). Otherwise, the teacher's `weight`
    field determines its share.
    """
    rng = random.Random(seed)
    if equal:
        # Deterministic round-robin so each teacher gets a near-equal share.
        for i, a in enumerate(assignments):
            a["teacher_id"] = teachers[i % len(teachers)]["id"]
        rng.shuffle(assignments)  # re-shuffle so batches are mixed
    else:
        weights = [t["weight"] for t in teachers]
        for a in assignments:
            a["teacher_id"] = rng.choices(teachers, weights=weights, k=1)[0]["id"]


async def api_call(
    session: aiohttp.ClientSession,
    messages: list[dict],
    teacher: dict,
    semaphore: asyncio.Semaphore,
) -> str | None:
    """Make a single API call to the given teacher's model."""
    url = f"{MINDROUTER_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {MINDROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": teacher["id"],
        "messages": messages,
        "max_tokens": MAX_TOKENS + teacher.get("max_tokens_overhead", 3072),
        "temperature": TEMPERATURE,
    }

    tag = teacher["id"].split("/")[-1][:20]
    for attempt in range(MAX_RETRIES):
        async with semaphore:
            try:
                async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=360)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        content = data["choices"][0]["message"].get("content")
                        if content is None:
                            print(f"  [{tag}] content=null (thinking budget exhausted)")
                            return None
                        return content.strip()
                    elif resp.status == 429:
                        wait = RETRY_BACKOFF * (2 ** attempt)
                        print(f"  [{tag}] 429 rate-limited, waiting {wait:.0f}s (attempt {attempt+1}/{MAX_RETRIES})")
                        await asyncio.sleep(wait)
                    else:
                        body = (await resp.text())[:120]
                        print(f"  [{tag}] HTTP {resp.status}: {body} (attempt {attempt+1}/{MAX_RETRIES})")
                        await asyncio.sleep(RETRY_BACKOFF * (2 ** attempt))
            except asyncio.TimeoutError:
                print(f"  [{tag}] timeout (attempt {attempt+1}/{MAX_RETRIES})")
                await asyncio.sleep(RETRY_BACKOFF * (2 ** attempt))
            except aiohttp.ClientError as e:
                print(f"  [{tag}] client error: {type(e).__name__}: {e} (attempt {attempt+1}/{MAX_RETRIES})")
                await asyncio.sleep(RETRY_BACKOFF * (2 ** attempt))

    return None


async def generate_one(
    session: aiohttp.ClientSession,
    assignment: dict,
    teacher: dict,
    semaphore: asyncio.Semaphore,
) -> dict | None:
    """Generate a single UGF reasoning trace with validation via one teacher."""
    prompt_template = CONTENT_TYPES[assignment["content_type"]]
    user_prompt = prompt_template.format(topic=assignment["topic"])

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    ugf_text = await api_call(session, messages, teacher, semaphore)
    if ugf_text is None:
        return None

    # Validation with retries
    max_retries = 3
    for retry in range(max_retries):
        is_valid, violations = validate_ugf(ugf_text)
        if is_valid:
            break

        correction = (
            f"Your response contains words or symbols not in the allowed list: "
            f"{', '.join(repr(v) for v in violations[:15])}. "
            f"Rewrite the entire response. Two things to fix:\n"
            f"  (a) Replace each disallowed word with a description using only allowed words.\n"
            f"  (b) Remove all markdown formatting. No asterisks, no bold, no bullet lists, "
            f"no numbered headers. Write plain running prose only -- if you need to enumerate, "
            f"write 'First, ... Second, ... Third, ...' as sentences, not as a list."
        )
        messages.append({"role": "assistant", "content": ugf_text})
        messages.append({"role": "user", "content": correction})

        ugf_text = await api_call(session, messages, teacher, semaphore)
        if ugf_text is None:
            return None

    is_valid, violations = validate_ugf(ugf_text)

    return {
        "id": assignment["id"],
        "ugf_text": ugf_text,
        "content_type": assignment["content_type"],
        "topic": assignment["topic"],
        "source_model": teacher["id"],
        "metadata": {"domain": assignment["domain"]},
        "compliant": is_valid,
        "remaining_violations": violations if not is_valid else [],
    }


def load_progress(progress_path: Path) -> set[str]:
    if progress_path.exists():
        with open(progress_path) as f:
            return set(json.load(f).get("completed_ids", []))
    return set()


def save_progress(progress_path: Path, completed_ids: set[str], stats: dict):
    with open(progress_path, "w") as f:
        json.dump({
            "completed_ids": list(completed_ids),
            "stats": stats,
            "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        }, f)


def _empty_model_stats(teachers: list[dict]) -> dict:
    return {t["id"]: {"compliant": 0, "non_compliant": 0, "failed": 0} for t in teachers}


async def main(
    dry_run: bool = False,
    limit: int | None = None,
    output_path: Path | None = None,
    progress_path: Path | None = None,
    equal_teacher_weights: bool = False,
    teachers_override_json: Path | None = None,
):
    global TEACHERS
    if teachers_override_json is not None:
        with open(teachers_override_json) as f:
            TEACHERS = json.load(f)
        print(f"Teacher list overridden from {teachers_override_json} ({len(TEACHERS)} teachers)")
    # 86 topics × 5 content_types = 430 unique combos. For the full corpus we
    # aim for ~2M traces; the default below is a short iteration batch.
    n_total = limit or 2000

    output_path = output_path or DEFAULT_OUTPUT_PATH
    progress_path = progress_path or DEFAULT_PROGRESS_PATH

    assignments = generate_topic_assignments(n_total)
    assign_teachers(assignments, TEACHERS, equal=equal_teacher_weights)

    completed_ids = load_progress(progress_path)
    remaining = [a for a in assignments if a["id"] not in completed_ids]

    print(f"Total assignments: {len(assignments)}")
    print(f"Already completed: {len(completed_ids)}")
    print(f"Remaining: {len(remaining)}")
    print(f"Topics: {sum(len(t) for t in TOPICS.values())} across {len(TOPICS)} domains")
    print(f"Content types: {len(CONTENT_TYPES)}")
    print(f"Teachers ({len(TEACHERS)}):")
    from collections import Counter
    share = Counter(a["teacher_id"] for a in remaining)
    for t in TEACHERS:
        n = share.get(t["id"], 0)
        pct = (n / len(remaining) * 100) if remaining else 0
        print(f"  {t['id']:35} concurrency={t['max_concurrent']:<3} share={n} ({pct:.1f}%)")

    if dry_run:
        print("\n[DRY RUN] First 5 assignments:")
        for a in remaining[:5]:
            print(f"  [{a['teacher_id']}] [{a['content_type']}] {a['topic'][:60]}")
        return

    if not MINDROUTER_API_KEY:
        print("ERROR: MINDROUTER_API_KEY not set.")
        sys.exit(1)

    # Per-teacher semaphore and quick lookup by id
    semaphores = {t["id"]: asyncio.Semaphore(t["max_concurrent"]) for t in TEACHERS}
    teachers_by_id = {t["id"]: t for t in TEACHERS}

    stats = {
        "completed": len(completed_ids),
        "compliant": 0,
        "non_compliant": 0,
        "failed": 0,
        "per_model": _empty_model_stats(TEACHERS),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # MindRouter uses a self-signed certificate (campus-internal service)
    connector = aiohttp.TCPConnector(ssl=False, limit=0)
    async with aiohttp.ClientSession(connector=connector) as session:
        batch_size = 100
        for batch_start in range(0, len(remaining), batch_size):
            batch = remaining[batch_start:batch_start + batch_size]

            tasks = []
            for a in batch:
                teacher = teachers_by_id[a["teacher_id"]]
                sem = semaphores[a["teacher_id"]]
                tasks.append(generate_one(session, a, teacher, sem))
            results = await asyncio.gather(*tasks)

            with open(output_path, "a", encoding="utf-8") as f:
                for a, result in zip(batch, results):
                    model_id = a["teacher_id"]
                    if result is None:
                        stats["failed"] += 1
                        stats["per_model"][model_id]["failed"] += 1
                        continue
                    f.write(json.dumps(result, ensure_ascii=False) + "\n")
                    completed_ids.add(result["id"])
                    if result["compliant"]:
                        stats["compliant"] += 1
                        stats["per_model"][model_id]["compliant"] += 1
                    else:
                        stats["non_compliant"] += 1
                        stats["per_model"][model_id]["non_compliant"] += 1

            stats["completed"] = len(completed_ids)
            save_progress(progress_path, completed_ids, stats)

            total_done = batch_start + len(batch)
            pct = total_done / len(remaining) * 100
            per_model_str = " | ".join(
                f"{mid.split('/')[-1][:16]}: {s['compliant']}/{s['compliant']+s['non_compliant']+s['failed']}"
                for mid, s in stats["per_model"].items()
            )
            print(
                f"  [{total_done}/{len(remaining)}] ({pct:.1f}%) "
                f"compliant={stats['compliant']} non_compliant={stats['non_compliant']} "
                f"failed={stats['failed']}  ||  {per_model_str}"
            )

    print(f"\nDone. Overall stats: {json.dumps(stats, indent=2)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate UGF reasoning traces")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, help="Number of traces to generate")
    parser.add_argument("--output-path", type=Path,
                        help="Override output jsonl path (for pilots)")
    parser.add_argument("--progress-path", type=Path,
                        help="Override progress json path (for pilots)")
    parser.add_argument("--equal-teacher-weights", action="store_true",
                        help="Give each teacher an equal share (for controlled pilots)")
    parser.add_argument("--teachers-override-json", type=Path,
                        help="JSON file with an alternate teacher list (for pilots)")
    args = parser.parse_args()

    asyncio.run(main(
        dry_run=args.dry_run,
        limit=args.limit,
        output_path=args.output_path,
        progress_path=args.progress_path,
        equal_teacher_weights=args.equal_teacher_weights,
        teachers_override_json=args.teachers_override_json,
    ))
