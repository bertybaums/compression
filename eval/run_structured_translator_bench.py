"""
Run the EN->UGF direction of the logic-textbook benchmark through the
StructuredTranslator (base model + hard UGF mask).

Output schema matches eval/results/_jsonl/logic_bench_20260505_143235.jsonl
so the new outputs are directly comparable to the trained-T5 Translator's
outputs from May 5.

Usage:
    python -m eval.run_structured_translator_bench \\
        --bench eval/sets/logic_textbook_bench.jsonl \\
        --model openai/gpt-oss-20b \\
        --out  eval/results/logic_bench_structured_<ts>.jsonl
"""

import argparse
import json
import sys
import time
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).parent.parent))

from translator.structured_translator import StructuredTranslator


def build_user_query_english(item: dict) -> str:
    instruction = (item.get("instruction") or "").strip()
    question = item["question"].strip()
    if instruction:
        return f"{instruction}\n\n{question}"
    return question


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bench", default="eval/sets/logic_textbook_bench.jsonl")
    parser.add_argument("--model", default="openai/gpt-oss-20b")
    parser.add_argument("--out", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-new-tokens", type=int, default=300)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument(
        "--prompt-template",
        default=None,
        help="Override default prompt template. Must contain '{text}'.",
    )
    args = parser.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Device: {device}")

    items: list[dict] = []
    with open(args.bench) as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    if args.limit:
        items = items[: args.limit]
    print(f"Benchmark: {len(items)} items from {args.bench}")

    print(f"Loading structured translator from {args.model}...")
    translator = StructuredTranslator(model_name_or_path=args.model)
    print(
        f"  Vocab size: {translator.tokenizer.vocab_size}; "
        f"UGF-allowed token count: {len(translator.ugf_processor.allowed_token_ids)}"
    )

    if args.out is None:
        ts = time.strftime("%Y%m%d_%H%M%S")
        args.out = f"eval/results/logic_bench_structured_{ts}.jsonl"
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    print(f"Output: {args.out}")

    to_ugf_kwargs = {
        "max_new_tokens": args.max_new_tokens,
        "temperature": args.temperature,
    }
    if args.prompt_template:
        to_ugf_kwargs["prompt_template"] = args.prompt_template

    t_start = time.time()
    n_done = 0
    with open(args.out, "w", encoding="utf-8") as f_out:
        for i, item in enumerate(items):
            t0 = time.time()
            english_query = build_user_query_english(item)

            try:
                ugf_query = translator.to_ugf(english_query, **to_ugf_kwargs)
            except Exception as e:
                ugf_query = f"<TRANSLATOR_ERROR: {e}>"

            dt = time.time() - t0
            record = {
                "id": item["id"],
                "type": item["type"],
                "instruction": item.get("instruction", ""),
                "question": item["question"],
                "expected_answer": item.get("expected_answer", ""),
                "english_query": english_query,
                "ugf_query": ugf_query,
                "translator": "structured-output",
                "translator_model": args.model,
                "latency_s": round(dt, 2),
            }
            f_out.write(json.dumps(record, ensure_ascii=False) + "\n")
            f_out.flush()
            n_done += 1

            if (i + 1) % 5 == 0 or i + 1 == len(items):
                elapsed = time.time() - t_start
                rate = n_done / elapsed if elapsed else 0
                print(
                    f"  [{i+1}/{len(items)}] {dt:.1f}s/item, avg {rate*60:.1f}/min",
                    flush=True,
                )

    total = time.time() - t_start
    print(f"\nDone. {n_done} items in {total:.0f}s ({n_done/total*60:.1f}/min)")
    print(f"Results: {args.out}")


if __name__ == "__main__":
    main()
