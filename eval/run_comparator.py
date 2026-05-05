"""
Run a benchmark JSONL through the teacher-in-UGF comparator pipeline.

This is the Layer-3 comparator (per memory/eval_comparator_strategy.md):
gpt-oss-120b with our UGF system prompt + few-shot exemplars — the same
configuration used during corpus generation. It's the natural "ceiling"
the small Reasoner is being compared against.

Pipeline:
  English query
    -> gpt-oss-120b on MindRouter (system prompt enforces UGF + few-shot)
    -> UGF response
    -> Translator -> English response

Output JSONL schema mirrors eval/run_logic_bench.py for easy side-by-side
comparison and downstream judging.

Usage:
  python -m eval.run_comparator \\
      --bench eval/sets/logic_textbook_bench.jsonl \\
      --translator checkpoints/translator/best \\
      --out eval/results/comparator_logic_<timestamp>.jsonl
"""

import argparse
import asyncio
import json
import os
import ssl
import sys
import time
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).parent.parent))


# ============================================================================
# Constants — must match corpus/generation/generate_reasoning.py
# (inlined here, not imported, because generate_reasoning.py reads .env and
# config.yaml at module import time which we don't want here)
# ============================================================================

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


# CONTENT_TYPES (5 standard templates from corpus generation)
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
        "Walk-through:"
    ),
}


FEWSHOT_EXEMPLARS = [
    (
        CONTENT_TYPES["chain_of_thought"].format(topic="how a story about one person does not tell us about everyone"),
        "First, we see that a story tells about the one person in it. Then we notice that each person can have a different life and can think and feel in ways that are not the same as the one in the story. This means that the one story does not give us enough facts to know about all people. Next, we think that to know about many people we would need many stories or many times we see people. This shows that using only one story to say how all people are would be a bad idea. Finally, we understand that a story about one person can still be good to learn about that person, but it does not tell us about everyone.",
    ),
    (
        CONTENT_TYPES["concept_explanation"].format(topic="when one person doing something first changes what others do"),
        "First, when a person does something, the rest of the people can see it. When they see it, they may choose to do the same thing or do some other thing. The first act can make a line of people change what they do. This can happen because the rest of the people think the first act shows a good way, or because they do not want to be left out. Now the rest of the people may change again when another person does something new. All the people can see how one act can make a big change in what many people do. This means that the first thing a person does can shape what the rest of the people will do.",
    ),
]


# Same mapping as eval/run_logic_bench.py for parity
BENCH_TYPE_TO_TEMPLATE = {
    "statement_vs_nonstatement":     "concept_explanation",
    "identify_argument":             "argument_analysis",
    "argument_vs_explanation":       "argument_analysis",
    "validity_judgment":             "argument_analysis",
    "missing_premise":               "argument_analysis",
    "rhetorical_technique":          "argument_analysis",
    "statistical_fallacy":           "argument_analysis",
    "analogical_argument_strength":  "argument_analysis",
    "correlation_causation":         "argument_analysis",
}


# ============================================================================
# MindRouter API
# ============================================================================

MR_BASE_URL = "https://mindrouter.uidaho.edu/v1"
MODEL_ID = "openai/gpt-oss-120b"


def build_messages(item: dict) -> list[dict]:
    """Build the messages list for the comparator: system + few-shot + user.

    The user message wraps the English question in the same CONTENT_TYPES
    template the SFT Reasoner sees (in UGF). Different from the Reasoner side
    in that the topic stays in English here — the teacher reads English natively.
    """
    template_name = BENCH_TYPE_TO_TEMPLATE.get(item["type"], "argument_analysis")
    template = CONTENT_TYPES[template_name]
    english_query = f"{item['instruction']}\n\n{item['question']}"
    user_content = template.format(topic=english_query)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for ex_user, ex_asst in FEWSHOT_EXEMPLARS:
        messages.append({"role": "user", "content": ex_user})
        messages.append({"role": "assistant", "content": ex_asst})
    messages.append({"role": "user", "content": user_content})
    return messages, template_name


async def call_mr(
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    api_key: str,
    messages: list[dict],
    max_tokens: int = 8192,
    reasoning_effort: str = "medium",
    timeout_s: int = 360,
) -> tuple[str | None, float, str | None]:
    """Single call to MR. Returns (content, latency_s, error_msg)."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": MODEL_ID,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "reasoning_effort": reasoning_effort,
    }
    async with semaphore:
        t0 = time.time()
        try:
            async with session.post(
                f"{MR_BASE_URL}/chat/completions",
                json=payload, headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout_s),
                ssl=False,
            ) as resp:
                dt = time.time() - t0
                if resp.status != 200:
                    text = await resp.text()
                    return None, dt, f"HTTP {resp.status}: {text[:200]}"
                data = await resp.json()
                content = data["choices"][0]["message"].get("content", "") or ""
                return content.strip(), dt, None
        except Exception as e:
            return None, time.time() - t0, str(e)


async def process_one(
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    api_key: str,
    item: dict,
    max_tokens: int,
) -> dict:
    """Process a single benchmark item: call MR, return record."""
    messages, template_name = build_messages(item)
    english_query = f"{item['instruction']}\n\n{item['question']}"

    ugf_response, latency, err = await call_mr(
        session, semaphore, api_key, messages, max_tokens=max_tokens
    )
    if err:
        ugf_response = f"<COMPARATOR_ERROR: {err}>"

    return {
        "id": item["id"],
        "type": item["type"],
        "instruction": item["instruction"],
        "question": item["question"],
        "expected_answer": item["expected_answer"],
        "english_query": english_query,
        "template": template_name,
        "comparator_model": MODEL_ID,
        "ugf_response": ugf_response,
        "comparator_latency_s": round(latency, 2),
    }


async def main_async(args):
    # Load API key
    api_key = os.environ.get("MINDROUTER_API_KEY", "")
    if not api_key:
        env_path = Path(__file__).parent.parent / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("MINDROUTER_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
    if not api_key:
        raise SystemExit("MINDROUTER_API_KEY not set (env or .env file)")

    # Load benchmark
    items = []
    with open(args.bench) as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    if args.limit:
        items = items[: args.limit]
    print(f"Benchmark: {len(items)} items from {args.bench}")

    # Output path
    if args.out is None:
        ts = time.strftime("%Y%m%d_%H%M%S")
        bench_stem = Path(args.bench).stem
        args.out = f"eval/results/comparator_{bench_stem}_{ts}.jsonl"
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    print(f"Output: {args.out}")

    # Run with concurrency
    semaphore = asyncio.Semaphore(args.concurrency)
    connector = aiohttp.TCPConnector(limit=args.concurrency, ssl=False)
    timeout = aiohttp.ClientTimeout(total=None)
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        t_start = time.time()
        tasks = [process_one(session, semaphore, api_key, item, args.max_tokens) for item in items]
        n_done = 0
        with open(args.out, "w", encoding="utf-8") as f_out:
            for fut in asyncio.as_completed(tasks):
                rec = await fut
                f_out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f_out.flush()
                n_done += 1
                if n_done % 5 == 0 or n_done == len(items):
                    elapsed = time.time() - t_start
                    rate = n_done / elapsed * 60 if elapsed else 0
                    print(f"  [{n_done}/{len(items)}] {rate:.1f}/min", flush=True)

    total = time.time() - t_start
    print(f"\nDone. {n_done} comparator runs in {total:.0f}s")
    print(f"Results: {args.out}")
    print(f"\nNext step: pipe UGF responses through Translator (UGF -> English) "
          f"for downstream judging.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bench", required=True, help="JSONL benchmark file")
    parser.add_argument("--out", default=None, help="Output JSONL path")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of items")
    parser.add_argument("--max-tokens", type=int, default=8192,
                        help="max_tokens overhead for gpt-oss-120b (with thinking)")
    parser.add_argument("--concurrency", type=int, default=5,
                        help="Concurrent MR calls (kept low for politeness)")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
