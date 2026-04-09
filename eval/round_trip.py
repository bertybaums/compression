"""
Round-trip evaluation pipeline.

Three tests that decompose the full pipeline:

  Test A (Translator only):
    English -> Translator(to_ugf) -> Translator(to_english) -> Reconstructed
    Measures: translation fidelity in isolation

  Test B (Reasoner, mediated by Translator):
    English question -> Translator(to_ugf) -> Reasoner(generate) -> Translator(to_english)
    Measures: reasoning quality through the vocabulary bottleneck

  Test C (Full round-trip fidelity):
    English explanation -> Translator(to_ugf) -> [pass through] -> Translator(to_english)
    Then separately: UGF explanation -> Reasoner(generate more) -> Translator(to_english)
    Measures: semantic preservation across the full pipeline

Usage:
  python eval/round_trip.py --test A --eval-set eval/sets/translation_eval.jsonl
  python eval/round_trip.py --test B --eval-set eval/sets/reasoning_eval.jsonl
  python eval/round_trip.py --test C --eval-set eval/sets/roundtrip_eval.jsonl
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import torch
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from eval.metrics import compute_all_metrics, MetricResult


def load_eval_set(path: str | Path) -> list[dict]:
    """Load evaluation set from JSONL."""
    records = []
    with open(path) as f:
        for line in f:
            records.append(json.loads(line))
    return records


def run_test_a(
    eval_records: list[dict],
    translator,
    device: str = "cuda",
    llm_api_key: str = "",
) -> dict:
    """Test A: Translator round-trip (English -> UGF -> English).

    Measures whether the Translator preserves meaning through the UGF bottleneck.
    """
    originals = []
    reconstructed = []
    ugf_intermediates = []

    print(f"Test A: Translating {len(eval_records)} passages through UGF bottleneck...")

    for i, record in enumerate(eval_records):
        english = record.get("english", record.get("text", ""))
        if not english:
            continue

        # English -> UGF
        ugf = translator.to_ugf(english)
        # UGF -> English
        recon = translator.to_english(ugf)

        originals.append(english)
        reconstructed.append(recon)
        ugf_intermediates.append(ugf)

        if (i + 1) % 50 == 0:
            print(f"  [{i+1}/{len(eval_records)}]")

    print(f"Translated {len(originals)} passages. Computing metrics...")

    metrics = compute_all_metrics(
        originals, reconstructed,
        device=device,
        include_llm_judge=bool(llm_api_key),
        llm_api_key=llm_api_key,
    )

    return {
        "test": "A",
        "description": "Translator round-trip (English -> UGF -> English)",
        "n_samples": len(originals),
        "metrics": {k: v.summary() for k, v in metrics.items()},
        "samples": [
            {
                "original": originals[i],
                "ugf": ugf_intermediates[i],
                "reconstructed": reconstructed[i],
                "scores": {k: round(v.scores[i], 4) for k, v in metrics.items()},
            }
            for i in range(min(20, len(originals)))  # save first 20 for inspection
        ],
    }


def run_test_b(
    eval_records: list[dict],
    translator,
    reasoner_model,
    reasoner_tokenizer,
    device: str = "cuda",
    max_new_tokens: int = 256,
    llm_api_key: str = "",
) -> dict:
    """Test B: Reasoner mediated (English question -> Translator -> Reasoner -> Translator -> English).

    Measures whether the Reasoner can produce meaningful responses
    that survive the round-trip back to English.
    """
    questions = []
    responses = []
    ugf_questions = []
    ugf_responses = []

    print(f"Test B: Processing {len(eval_records)} questions through Reasoner...")

    for i, record in enumerate(eval_records):
        question = record.get("question", record.get("english", record.get("text", "")))
        if not question:
            continue

        # English question -> UGF
        ugf_q = translator.to_ugf(question)

        # UGF question -> Reasoner generates UGF response
        input_ids = reasoner_tokenizer.encode(ugf_q, add_special_tokens=True, return_tensors="pt")
        if isinstance(input_ids, list):
            input_ids = torch.tensor([input_ids])
        input_ids = input_ids.to(device)

        output_ids = reasoner_model.generate(
            input_ids,
            max_new_tokens=max_new_tokens,
            temperature=0.7,
            top_k=50,
            top_p=0.9,
            eos_token_id=reasoner_tokenizer.eos_token_id,
        )
        ugf_r = reasoner_tokenizer.decode(output_ids[0].tolist())

        # UGF response -> English
        english_response = translator.to_english(ugf_r)

        questions.append(question)
        responses.append(english_response)
        ugf_questions.append(ugf_q)
        ugf_responses.append(ugf_r)

        if (i + 1) % 20 == 0:
            print(f"  [{i+1}/{len(eval_records)}]")

    print(f"Generated {len(responses)} responses. Computing metrics...")

    # For Test B, we use the LLM judge as the primary metric
    # (comparing question to response quality, not exact reconstruction)
    metrics = compute_all_metrics(
        questions, responses,
        device=device,
        include_llm_judge=bool(llm_api_key),
        llm_api_key=llm_api_key,
    )

    return {
        "test": "B",
        "description": "Reasoner mediated (question -> Translator -> Reasoner -> Translator -> response)",
        "n_samples": len(questions),
        "metrics": {k: v.summary() for k, v in metrics.items()},
        "samples": [
            {
                "question": questions[i],
                "ugf_question": ugf_questions[i],
                "ugf_response": ugf_responses[i],
                "english_response": responses[i],
                "scores": {k: round(v.scores[i], 4) for k, v in metrics.items()},
            }
            for i in range(min(20, len(questions)))
        ],
    }


def run_test_c(
    eval_records: list[dict],
    translator,
    device: str = "cuda",
    llm_api_key: str = "",
) -> dict:
    """Test C: Full round-trip fidelity on explanations/arguments.

    English explanation -> Translator(to_ugf) -> Translator(to_english) -> compare.
    This is Test A applied specifically to philosophical content that tests the
    limits of the vocabulary bottleneck.

    The eval set should contain high-concept-density passages: categorical
    imperative, Nash equilibrium, Bayesian reasoning, etc.
    """
    # Test C is structurally identical to Test A but uses a different eval set
    # (stress-test passages with high concept density)
    return run_test_a(
        eval_records, translator, device=device, llm_api_key=llm_api_key
    )


def save_results(results: dict, output_path: str | Path):
    """Save evaluation results to JSON."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"Results saved to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Round-trip evaluation pipeline")
    parser.add_argument("--test", choices=["A", "B", "C", "all"], default="A",
                        help="Which test to run")
    parser.add_argument("--eval-set", type=str, required=True,
                        help="Path to evaluation set (JSONL)")
    parser.add_argument("--translator-path", type=str, default="checkpoints/translator/best",
                        help="Path to fine-tuned translator model")
    parser.add_argument("--reasoner-path", type=str, default="checkpoints/reasoner/final.pt",
                        help="Path to trained reasoner checkpoint")
    parser.add_argument("--output", type=str, default=None,
                        help="Path to save results (default: eval/results/<test>_<timestamp>.json)")
    parser.add_argument("--device", type=str, default=None,
                        help="Device (cuda/cpu, default: auto)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit number of eval samples")
    parser.add_argument("--llm-judge", action="store_true",
                        help="Include LLM judge metric (requires MINDROUTER_API_KEY)")
    args = parser.parse_args()

    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    # Load eval set
    eval_records = load_eval_set(args.eval_set)
    if args.limit:
        eval_records = eval_records[:args.limit]
    print(f"Eval set: {len(eval_records)} records from {args.eval_set}")

    # API key for LLM judge
    llm_api_key = ""
    if args.llm_judge:
        from dotenv import load_dotenv
        load_dotenv()
        llm_api_key = os.environ.get("MINDROUTER_API_KEY", "")
        if not llm_api_key:
            print("Warning: --llm-judge specified but MINDROUTER_API_KEY not set")

    # Load models
    tests_to_run = [args.test] if args.test != "all" else ["A", "B", "C"]
    needs_translator = any(t in tests_to_run for t in ["A", "B", "C"])
    needs_reasoner = "B" in tests_to_run

    translator = None
    reasoner_model = None
    reasoner_tokenizer = None

    if needs_translator:
        print(f"Loading translator from {args.translator_path}...")
        from translator.model import Translator
        translator = Translator(model_name_or_path=args.translator_path, device=device)

    if needs_reasoner:
        print(f"Loading reasoner from {args.reasoner_path}...")
        from reasoner.model import Reasoner, ReasonerConfig
        from tokenizer.ugf_tokenizer import UGFTokenizer

        reasoner_tokenizer = UGFTokenizer()
        ckpt = torch.load(args.reasoner_path, map_location="cpu", weights_only=False)
        config = ReasonerConfig(**ckpt["config"]) if isinstance(ckpt["config"], dict) else ckpt["config"]
        reasoner_model = Reasoner(config)
        reasoner_model.load_state_dict(ckpt["model_state_dict"])
        reasoner_model = reasoner_model.to(device)
        reasoner_model.eval()

    # Run tests
    all_results = {}
    timestamp = time.strftime("%Y%m%d_%H%M%S")

    for test in tests_to_run:
        print(f"\n{'='*60}")
        print(f"Running Test {test}")
        print(f"{'='*60}")

        if test == "A":
            results = run_test_a(eval_records, translator, device=device, llm_api_key=llm_api_key)
        elif test == "B":
            results = run_test_b(
                eval_records, translator, reasoner_model, reasoner_tokenizer,
                device=device, llm_api_key=llm_api_key,
            )
        elif test == "C":
            results = run_test_c(eval_records, translator, device=device, llm_api_key=llm_api_key)

        all_results[test] = results

        # Print summary
        print(f"\nTest {test} Results:")
        for metric_name, summary in results["metrics"].items():
            print(f"  {summary['name']:30s}  mean={summary['mean']:.4f}  std={summary['std']:.4f}")

    # Save
    output_path = args.output or f"eval/results/test_{args.test}_{timestamp}.json"
    save_results(all_results, output_path)


if __name__ == "__main__":
    main()
