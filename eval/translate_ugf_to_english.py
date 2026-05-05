"""
Translate the `ugf_response` field of an existing JSONL through the
Translator (UGF -> English), adding an `english_response` field.

Used to add the English-side rendering to comparator output (which only
saves UGF). Idempotent: rewrites the file with the new field added.

Usage:
  python -m eval.translate_ugf_to_english \\
      --input  eval/results/comparator_logic_textbook_<ts>.jsonl \\
      --output eval/results/comparator_logic_textbook_<ts>_with_english.jsonl \\
      --translator checkpoints/translator/best
"""

import argparse
import json
import sys
import time
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).parent.parent))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default=None)
    parser.add_argument("--translator", default="checkpoints/translator/best")
    args = parser.parse_args()

    out_path = args.output or args.input.replace(".jsonl", "_with_english.jsonl")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    print(f"Loading translator from {args.translator}...")
    from translator.model import Translator
    translator = Translator(model_name_or_path=args.translator, device=str(device))

    items = [json.loads(l) for l in open(args.input) if l.strip()]
    print(f"Translating {len(items)} UGF responses...")

    t_start = time.time()
    n_done = 0
    with open(out_path, "w", encoding="utf-8") as f_out:
        for item in items:
            ugf = item.get("ugf_response", "")
            if ugf and not ugf.startswith("<"):
                try:
                    item["english_response"] = translator.to_english(ugf)
                except Exception as e:
                    item["english_response"] = f"<TRANSLATOR_ERROR: {e}>"
            else:
                item["english_response"] = ugf
            f_out.write(json.dumps(item, ensure_ascii=False) + "\n")
            n_done += 1
            if n_done % 10 == 0:
                elapsed = time.time() - t_start
                print(f"  [{n_done}/{len(items)}] {n_done/elapsed*60:.1f}/min", flush=True)

    print(f"\nDone in {time.time()-t_start:.0f}s. Output: {out_path}")


if __name__ == "__main__":
    main()
