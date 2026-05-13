"""
Run the EN→UGF direction of the logic-textbook benchmark through the
MR-based structured Translator (gpt-oss-120b + short prompt + json_object
response_format + post-hoc UGF validation + retry-on-violations).

Output schema matches eval/results/_jsonl/logic_bench_20260505_143235.jsonl
so the new outputs go head-to-head against the trained-T5 baseline.

Usage:
    python -m eval.run_mr_structured_translator_bench \\
        --bench eval/sets/logic_textbook_bench.jsonl \\
        --out eval/results/logic_bench_mr_structured_<ts>.jsonl
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from translator.mr_structured_translator import translate


def build_user_query(item: dict) -> str:
    instruction = (item.get("instruction") or "").strip()
    question = item["question"].strip()
    return f"{instruction}\n\n{question}" if instruction else question


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bench", default="eval/sets/logic_textbook_bench.jsonl")
    parser.add_argument("--model", default="openai/gpt-oss-120b")
    parser.add_argument("--out", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--reasoning-effort", default="low")
    parser.add_argument("--max-tokens", type=int, default=2500)
    args = parser.parse_args()

    items: list[dict] = []
    with open(args.bench) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
    if args.limit:
        items = items[: args.limit]
    print(f"Benchmark: {len(items)} items from {args.bench}")

    if args.out is None:
        ts = time.strftime("%Y%m%d_%H%M%S")
        args.out = f"eval/results/logic_bench_mr_structured_{ts}.jsonl"
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    print(f"Output: {args.out}")

    t_start = time.time()
    n_done = 0
    n_compliant = 0
    with open(args.out, "w", encoding="utf-8") as f_out:
        for i, item in enumerate(items):
            english_query = build_user_query(item)
            try:
                r = translate(
                    english_query,
                    model=args.model,
                    max_retries=args.max_retries,
                    reasoning_effort=args.reasoning_effort,
                    max_tokens=args.max_tokens,
                )
                ugf_query = r["translation"]
                compliant = r["compliant"]
                attempts = r["attempts"]
                latency = r["latency_s"]
                violations = r["violations"]
            except Exception as e:
                ugf_query = f"<TRANSLATOR_ERROR: {type(e).__name__}: {e}>"
                compliant = False
                attempts = 0
                latency = 0.0
                violations = []

            record = {
                "id": item["id"],
                "type": item["type"],
                "instruction": item.get("instruction", ""),
                "question": item["question"],
                "expected_answer": item.get("expected_answer", ""),
                "english_query": english_query,
                "ugf_query": ugf_query,
                "translator": "mr-structured-prompt-retry",
                "translator_model": args.model,
                "compliant": compliant,
                "attempts": attempts,
                "remaining_violations": violations,
                "latency_s": latency,
            }
            f_out.write(json.dumps(record, ensure_ascii=False) + "\n")
            f_out.flush()
            n_done += 1
            if compliant:
                n_compliant += 1

            if (i + 1) % 5 == 0 or i + 1 == len(items):
                elapsed = time.time() - t_start
                rate = n_done / elapsed if elapsed else 0
                print(
                    f"  [{i+1}/{len(items)}] "
                    f"compliant {n_compliant}/{n_done} ({n_compliant/n_done:.0%}) "
                    f"avg {rate*60:.0f}/min",
                    flush=True,
                )

    total = time.time() - t_start
    print(f"\nDone. {n_done} items in {total:.0f}s")
    print(f"Compliance: {n_compliant}/{n_done} ({n_compliant/n_done:.0%})")
    print(f"Results: {args.out}")


if __name__ == "__main__":
    main()
