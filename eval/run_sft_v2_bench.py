"""
Run the SFT v2 Reasoner against an eval benchmark.

Loads checkpoints/reasoner_sft_v2/final.pt (or any v2 SFT checkpoint),
feeds each item's English question through the UGF tokenizer (which drops
out-of-vocab words — same treatment the v2 model saw at training time on
the CoT corpus's English prompt_text), generates a UGF continuation, and
writes results to JSONL.

Each output record includes the raw v2 generation, the parsed reasoning
and answer spans (via eval.parse_v2_answer.extract_answer), and a
`parse_ok` flag. Downstream judges and aggregators read this file.

Unlike eval/run_logic_bench.py (the v1 runner), this script:
  - does NOT use the Translator (v2 takes English directly; the UGF
    tokenizer compresses by dropping OOV)
  - does NOT wrap prompts in CONTENT_TYPES templates (v2 was trained on
    natural-English prompts from the CoT corpus, no template scaffolding)
  - does NOT decode back to English (we want to keep the UGF output
    intact for parsing and judging)

Usage:
    python -m eval.run_sft_v2_bench \\
        --bench eval/sets/stress_bench.jsonl \\
        --reasoner checkpoints/reasoner_sft_v2/final.pt \\
        --out eval/results/sft_v2_stress_<timestamp>.jsonl
"""

import argparse
import json
import sys
import time
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).parent.parent))

from reasoner.model import Reasoner, ReasonerConfig
from tokenizer.ugf_tokenizer import UGFTokenizer
from eval.parse_v2_answer import extract_answer


def build_prompt(item: dict) -> str:
    """English prompt for the v2 model.

    Bench items vary by source. Try in order:
      - explicit 'prompt' field
      - instruction + question (logic textbook style)
      - 'question' alone
      - 'topic' alone (corpus holdout style — though v2 may handle these worse)
    """
    if item.get("prompt"):
        return item["prompt"].strip()
    instruction = (item.get("instruction") or "").strip()
    question = (item.get("question") or "").strip()
    if instruction and question:
        return f"{instruction}\n\n{question}"
    if question:
        return question
    topic = (item.get("topic") or "").strip()
    if topic:
        return topic
    raise ValueError(f"item {item.get('id')} has no prompt/question/topic")


@torch.no_grad()
def generate(model, tokenizer, prompt_str: str, max_new_tokens: int,
             temperature: float, top_k: int, top_p: float,
             repetition_penalty: float, no_repeat_ngram_size: int,
             device) -> str:
    bos = tokenizer.bos_token_id
    body = tokenizer.encode(prompt_str, add_special_tokens=False)
    ids = ([bos] if bos is not None else []) + body
    input_ids = torch.tensor([ids], dtype=torch.long, device=device)
    out = model.generate(
        input_ids,
        max_new_tokens=max_new_tokens,
        temperature=temperature,
        top_k=top_k,
        top_p=top_p,
        eos_token_id=tokenizer.eos_token_id,
        repetition_penalty=repetition_penalty,
        no_repeat_ngram_size=no_repeat_ngram_size,
    )
    completion_ids = out[0, input_ids.shape[1]:].tolist()
    return tokenizer.decode(completion_ids, skip_special_tokens=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bench", required=True, help="JSONL benchmark file")
    parser.add_argument("--reasoner", default="checkpoints/reasoner_sft_v2/final.pt",
                        help="SFT v2 checkpoint")
    parser.add_argument("--out", default=None, help="Output JSONL path")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-new-tokens", type=int, default=400,
                        help="Generous budget; v2 emits reasoning + marker + answer.")
    parser.add_argument("--temperature", type=float, default=0.8)
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--top-p", type=float, default=0.9)
    parser.add_argument("--repetition-penalty", type=float, default=1.0,
                        help="HF-style repetition penalty. 1.0=off; 1.2-1.5 typical anti-loop.")
    parser.add_argument("--no-repeat-ngram-size", type=int, default=0,
                        help="Forbid n-grams already in sequence. 0=off; 3-5 typical anti-loop.")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    torch.manual_seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    items = []
    with open(args.bench) as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    if args.limit:
        items = items[: args.limit]
    print(f"Benchmark: {len(items)} items from {args.bench}")

    tokenizer = UGFTokenizer()
    print(f"Loading reasoner v2 from {args.reasoner}...")
    ckpt = torch.load(args.reasoner, map_location="cpu", weights_only=False)
    config = ReasonerConfig(**ckpt["config"]) if isinstance(ckpt["config"], dict) else ckpt["config"]
    reasoner = Reasoner(config)
    reasoner.load_state_dict(ckpt["model_state_dict"])
    reasoner = reasoner.to(device).eval()
    print(f"  step={ckpt.get('step', '?')}")

    if args.out is None:
        ts = time.strftime("%Y%m%d_%H%M%S")
        args.out = f"eval/results/sft_v2_bench_{ts}.jsonl"
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    print(f"Output: {args.out}")

    t_start = time.time()
    n_parse_ok = 0
    with open(args.out, "w", encoding="utf-8") as f_out:
        for i, item in enumerate(items):
            t0 = time.time()
            prompt = build_prompt(item)

            try:
                ugf_response = generate(
                    reasoner, tokenizer, prompt,
                    max_new_tokens=args.max_new_tokens,
                    temperature=args.temperature,
                    top_k=args.top_k, top_p=args.top_p,
                    repetition_penalty=args.repetition_penalty,
                    no_repeat_ngram_size=args.no_repeat_ngram_size,
                    device=device,
                )
            except Exception as e:
                ugf_response = f"<REASONER_ERROR: {e}>"

            parsed = extract_answer(ugf_response)
            if parsed["parse_ok"]:
                n_parse_ok += 1

            record = {
                "id": item.get("id", ""),
                "type": item.get("type", ""),
                "prompt": prompt,
                "ugf_response": ugf_response,
                "reasoning": parsed["reasoning"],
                "answer": parsed["answer"],
                "parse_ok": parsed["parse_ok"],
                "n_markers": parsed["n_markers"],
                "failure_mode": parsed["failure_mode"],
                "latency_s": round(time.time() - t0, 2),
            }
            f_out.write(json.dumps(record, ensure_ascii=False) + "\n")
            f_out.flush()

            if (i + 1) % 10 == 0 or i + 1 == len(items):
                elapsed = time.time() - t_start
                pr = n_parse_ok / (i + 1)
                print(f"  [{i+1}/{len(items)}] parse_ok={pr:.1%}  "
                      f"avg {(i+1)/elapsed*60:.1f}/min", flush=True)

    total = time.time() - t_start
    print(f"\nDone. {len(items)} items in {total:.0f}s")
    print(f"Parse-success: {n_parse_ok}/{len(items)} ({n_parse_ok/len(items):.1%})")
    print(f"Results: {args.out}")


if __name__ == "__main__":
    main()
