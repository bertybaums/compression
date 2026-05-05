"""
Run the logic textbook benchmark through the full Layer-2 pipeline:

  English question -> Translator -> UGF prompt (wrapped in CONTENT_TYPES template)
                   -> Reasoner SFT -> UGF response -> Translator -> English answer

Writes per-item results to a JSONL with all intermediate outputs (UGF prompt,
UGF response, English response) so you can inspect failure modes by stage.

Usage:
  python -m eval.run_logic_bench \\
    --bench eval/sets/logic_textbook_bench.jsonl \\
    --reasoner checkpoints/reasoner_sft_v1/final.pt \\
    --translator checkpoints/translator/best \\
    --out eval/results/logic_bench_<timestamp>.jsonl
"""

import argparse
import json
import sys
import time
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).parent.parent))

from reasoner.model import Reasoner, ReasonerConfig
from reasoner.data_sft import CONTENT_TYPES
from tokenizer.ugf_tokenizer import UGFTokenizer


# Map benchmark item `type` to a CONTENT_TYPES template. Most items are
# argument-analytic in form; sentence-classification (statement_vs_nonstatement)
# fits concept_explanation better.
BENCH_TYPE_TO_TEMPLATE = {
    # textbook types -> CONTENT_TYPES keys
    "statement_vs_nonstatement":     "concept_explanation",
    "identify_argument":             "argument_analysis",
    "argument_vs_explanation":       "argument_analysis",
    "validity_judgment":             "argument_analysis",
    "missing_premise":               "argument_analysis",
    "rhetorical_technique":          "argument_analysis",
    "statistical_fallacy":           "argument_analysis",
    "analogical_argument_strength":  "argument_analysis",
    "correlation_causation":         "argument_analysis",
    # corpus content_type -> identity (for holdout benchmark)
    "concept_explanation":           "concept_explanation",
    "chain_of_thought":              "chain_of_thought",
    "socratic_dialogue":             "socratic_dialogue",
    "argument_analysis":             "argument_analysis",
    "thought_experiment":            "thought_experiment",
    # cxbot/misccorpora content_types fall back to argument_analysis
    "counterexample_analysis":       "argument_analysis",
    "analogical_analysis":           "argument_analysis",
    "conditional_analysis":          "argument_analysis",
}


def build_user_query_english(item: dict) -> str:
    """Construct the English query a 'student' would ask, combining
    instruction + specific question. If instruction is empty (holdout
    benchmark format), just returns the question."""
    instruction = (item.get("instruction") or "").strip()
    question = item["question"].strip()
    if instruction:
        return f"{instruction}\n\n{question}"
    return question


def wrap_in_template(ugf_query: str, content_type: str) -> str:
    """Wrap a UGF query in the CONTENT_TYPES template the SFT model expects.
    The CONTENT_TYPES templates all have a {topic} placeholder."""
    template = CONTENT_TYPES[content_type]
    return template.format(topic=ugf_query)


@torch.no_grad()
def reasoner_generate(model, tokenizer, prompt_str: str, max_new_tokens: int,
                      temperature: float, top_k: int, top_p: float, device) -> str:
    """Generate a UGF response from a prompt string (no trailing EOS)."""
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
    )
    completion_ids = out[0, input_ids.shape[1]:].tolist()
    return tokenizer.decode(completion_ids, skip_special_tokens=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bench", required=True, help="JSONL benchmark file")
    parser.add_argument("--reasoner", default="checkpoints/reasoner_sft_v1/final.pt",
                        help="Reasoner SFT checkpoint")
    parser.add_argument("--translator", default="checkpoints/translator/best",
                        help="Translator model directory")
    parser.add_argument("--out", default=None, help="Output JSONL path")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of items")
    parser.add_argument("--max-new-tokens", type=int, default=300)
    parser.add_argument("--temperature", type=float, default=0.8)
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--top-p", type=float, default=0.9)
    parser.add_argument("--skip-translate-en2ugf", action="store_true",
                        help="Skip Translator(English->UGF) — feed query directly "
                             "as UGF (use when bench questions are already UGF-formatted, "
                             "e.g., the holdout corpus).")
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

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

    # Load Translator
    print(f"Loading translator from {args.translator}...")
    from translator.model import Translator
    translator = Translator(model_name_or_path=args.translator, device=str(device))

    # Load Reasoner
    print(f"Loading reasoner from {args.reasoner}...")
    tokenizer = UGFTokenizer()
    ckpt = torch.load(args.reasoner, map_location="cpu", weights_only=False)
    config = ReasonerConfig(**ckpt["config"]) if isinstance(ckpt["config"], dict) else ckpt["config"]
    reasoner = Reasoner(config)
    reasoner.load_state_dict(ckpt["model_state_dict"])
    reasoner = reasoner.to(device)
    reasoner.eval()
    print(f"  ckpt step={ckpt.get('step', '?')}")

    # Output path
    if args.out is None:
        ts = time.strftime("%Y%m%d_%H%M%S")
        args.out = f"eval/results/logic_bench_{ts}.jsonl"
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    print(f"Output: {args.out}")

    # Run
    t_start = time.time()
    n_done = 0
    with open(args.out, "w", encoding="utf-8") as f_out:
        for i, item in enumerate(items):
            t0 = time.time()
            english_query = build_user_query_english(item)

            # English -> UGF (Translator) — unless caller asked to skip it
            if args.skip_translate_en2ugf:
                ugf_query = english_query  # already UGF/simple-English
            else:
                try:
                    ugf_query = translator.to_ugf(english_query)
                except Exception as e:
                    ugf_query = f"<TRANSLATOR_ERROR: {e}>"

            # Wrap in CONTENT_TYPES template
            template_name = BENCH_TYPE_TO_TEMPLATE.get(item["type"], "argument_analysis")
            wrapped_prompt = wrap_in_template(ugf_query, template_name)

            # Reasoner generation
            try:
                ugf_response = reasoner_generate(
                    reasoner, tokenizer, wrapped_prompt,
                    max_new_tokens=args.max_new_tokens,
                    temperature=args.temperature,
                    top_k=args.top_k, top_p=args.top_p,
                    device=device,
                )
            except Exception as e:
                ugf_response = f"<REASONER_ERROR: {e}>"

            # UGF -> English (Translator)
            try:
                english_response = translator.to_english(ugf_response) if ugf_response and not ugf_response.startswith("<") else ugf_response
            except Exception as e:
                english_response = f"<TRANSLATOR_ERROR: {e}>"

            dt = time.time() - t0

            record = {
                "id": item["id"],
                "type": item["type"],
                "instruction": item["instruction"],
                "question": item["question"],
                "expected_answer": item["expected_answer"],
                "english_query": english_query,
                "ugf_query": ugf_query,
                "template": template_name,
                "wrapped_prompt": wrapped_prompt,
                "ugf_response": ugf_response,
                "english_response": english_response,
                "latency_s": round(dt, 2),
            }
            f_out.write(json.dumps(record, ensure_ascii=False) + "\n")
            f_out.flush()
            n_done += 1

            if (i + 1) % 5 == 0 or i + 1 == len(items):
                elapsed = time.time() - t_start
                rate = n_done / elapsed if elapsed else 0
                print(f"  [{i+1}/{len(items)}] {dt:.1f}s/item, avg {rate*60:.1f}/min", flush=True)

    total = time.time() - t_start
    print(f"\nDone. {n_done} items in {total:.0f}s ({n_done/total*60:.1f}/min)")
    print(f"Results: {args.out}")


if __name__ == "__main__":
    main()
