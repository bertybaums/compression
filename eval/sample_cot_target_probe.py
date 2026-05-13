"""
Sample a 50-prompt fixture for the P4-vs-P5-vs-Reasoner target-probe
experiment. Reads corpus/processed/english_passages.jsonl, excludes the
logic_critical_thinking track (the philosophical comparison wants
philosophy, not logic puzzles, on this slice), strats by remaining track,
wraps each sampled topic in one of the five CONTENT_TYPES templates
(cycled so we cover the space the Reasoner was trained on), writes the
cached fixture to eval/sets/cot_target_probe_50.jsonl.

Output schema (one JSONL record per prompt):
    {
      "id": "probe-NNN",
      "topic": "<raw text from english_passages>",
      "content_type": "argument_analysis",
      "english_query": "<wrapped prompt the Reasoner / P4 / P5 will see>",
      "source_id": "<original passage id>",
      "track": "<metadata.track or unknown>"
    }

Usage:
    python -m eval.sample_cot_target_probe \\
        --english-passages corpus/processed/english_passages.jsonl \\
        --n 50 \\
        --out eval/sets/cot_target_probe_50.jsonl
"""

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from corpus.generation.generate_reasoning import CONTENT_TYPES

CONTENT_TYPE_ORDER = list(CONTENT_TYPES.keys())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--english-passages",
        default="corpus/processed/english_passages.jsonl",
    )
    parser.add_argument("--n", type=int, default=50)
    parser.add_argument(
        "--out",
        default="eval/sets/cot_target_probe_50.jsonl",
    )
    parser.add_argument(
        "--exclude-track",
        default="logic_critical_thinking",
        help="metadata.track to exclude. Default keeps non-logic-puzzle records only.",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--min-len", type=int, default=80,
        help="Minimum text length in characters (filters trivial passages).",
    )
    parser.add_argument(
        "--max-len", type=int, default=1200,
        help="Maximum text length in characters (filters runaway passages).",
    )
    args = parser.parse_args()

    src = Path(args.english_passages)
    print(f"Reading {src}...")
    by_track: dict[str, list[dict]] = defaultdict(list)
    skipped = 0
    with open(src) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            text = (r.get("text") or "").strip()
            track = (r.get("metadata") or {}).get("track", "unknown")
            if track == args.exclude_track:
                continue
            if not (args.min_len <= len(text) <= args.max_len):
                continue
            by_track[track].append({"id": r["id"], "text": text, "track": track})
    print(f"  tracks: {dict((k, len(v)) for k, v in by_track.items())}; "
          f"skipped {skipped} unparseable")

    # Proportional sampling across remaining tracks.
    rng = random.Random(args.seed)
    total_available = sum(len(v) for v in by_track.values())
    sample: list[dict] = []
    for track, records in by_track.items():
        share = max(1, round(args.n * len(records) / total_available))
        rng.shuffle(records)
        sample.extend(records[: min(share, len(records))])
    rng.shuffle(sample)
    sample = sample[: args.n]
    print(f"  sampled {len(sample)} prompts")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for i, rec in enumerate(sample):
            content_type = CONTENT_TYPE_ORDER[i % len(CONTENT_TYPE_ORDER)]
            wrapped = CONTENT_TYPES[content_type].format(topic=rec["text"])
            f.write(json.dumps({
                "id": f"probe-{i:03d}",
                "topic": rec["text"],
                "content_type": content_type,
                "english_query": wrapped,
                "source_id": rec["id"],
                "track": rec["track"],
            }, ensure_ascii=False) + "\n")
    print(f"  wrote {out_path}")


if __name__ == "__main__":
    main()
