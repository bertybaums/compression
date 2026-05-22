"""
Extract v2 answer spans into a fresh JSONL file shaped like the original v2
generations, but with `ugf_response` replaced by the parsed answer text.

Used to feed `prepare_v2_milestone_judge_batches.py` with answer-only v2
inputs, for the answer-span-only re-judging comparison (Fork B of the
SFT-v2 milestone diagnosis).

Records where parse_ok=False are dropped (judging an empty / mis-formatted
span would be noise). Parse-fail count is reported so the resulting v1-vs-v2
comparison knows how many v2 records were excluded.

Usage:
    python -m eval.extract_v2_answer_span \\
        --input  eval/results/sft_v2_stress_norep_<ts>.jsonl \\
        --output eval/results/sft_v2_stress_norep_ans_<ts>.jsonl
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from eval.parse_v2_answer import extract_answer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="v2 generation JSONL")
    parser.add_argument("--output", required=True, help="answer-only JSONL")
    args = parser.parse_args()

    n_total = 0
    n_kept = 0
    with open(args.input) as fin, open(args.output, "w") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            n_total += 1
            ugf = r.get("ugf_response", "") or ""
            parsed = extract_answer(ugf)
            if not parsed["parse_ok"] or not parsed["answer"]:
                continue
            # Replace ugf_response with the answer span; keep other fields intact.
            r["ugf_response"] = parsed["answer"]
            r["reasoning_dropped"] = True
            fout.write(json.dumps(r) + "\n")
            n_kept += 1

    print(f"Read {n_total} from {args.input}")
    print(f"Wrote {n_kept} answer-only records to {args.output}")
    print(f"Dropped {n_total - n_kept} (parse_ok=False or empty answer)")


if __name__ == "__main__":
    main()
