"""
Parse v2 model outputs to extract the answer span.

Reads JSONL with {"id", "ugf_response"} and reports:
  - parse-success rate (fraction of records where the marker is found exactly once)
  - answer-length distribution (word counts of the extracted answer span)
  - reasoning-length distribution
  - failure-mode breakdown (no marker / multiple markers / empty answer)

Also exposes `extract_answer(text)` for use by downstream eval / RL reward
code. The locked marker phrase is "So my answer is:" (case-sensitive on
"So"; capitalization elsewhere matches training data).

Per the SFT v2 design fallback: if parse-success rate < 95% on a
representative eval set, we add `<think>`/`<answer>` special tokens and
re-do SFT v2 with token bracketing. See docs/sft-v2-design-2026-05-18.md.
"""

import argparse
import json
import re
import statistics
from pathlib import Path


# Locked canonical marker. Tolerate variant capitalization on "So" only —
# the model occasionally emits "so my answer is:" mid-sentence. Tolerate
# trailing whitespace / newline between marker and answer.
MARKER_REGEX = re.compile(r"[Ss]o my answer is:\s*", re.MULTILINE)
EXACT_MARKER = "So my answer is:"


def extract_answer(text: str) -> dict:
    """Extract reasoning / answer spans from a v2-format generation.

    Returns:
        {
            "parse_ok": bool,
            "n_markers": int,
            "reasoning": str | None,
            "answer": str | None,
            "failure_mode": "no_marker" | "multiple_markers" | "empty_answer" | None,
        }

    parse_ok == True iff exactly one marker present AND answer span is non-empty.
    """
    matches = list(MARKER_REGEX.finditer(text))
    n_markers = len(matches)

    if n_markers == 0:
        return {
            "parse_ok": False,
            "n_markers": 0,
            "reasoning": None,
            "answer": None,
            "failure_mode": "no_marker",
        }
    if n_markers > 1:
        # We pick the LAST occurrence — the model may emit the phrase
        # incidentally in reasoning before committing to it as a structural
        # marker. Reporting it as a failure mode anyway, since the format
        # contract was a single marker.
        m = matches[-1]
        reasoning = text[: m.start()].rstrip()
        answer = text[m.end():].strip()
        return {
            "parse_ok": False,
            "n_markers": n_markers,
            "reasoning": reasoning,
            "answer": answer if answer else None,
            "failure_mode": "multiple_markers",
        }

    m = matches[0]
    reasoning = text[: m.start()].rstrip()
    answer = text[m.end():].strip()
    if not answer:
        return {
            "parse_ok": False,
            "n_markers": 1,
            "reasoning": reasoning,
            "answer": None,
            "failure_mode": "empty_answer",
        }
    return {
        "parse_ok": True,
        "n_markers": 1,
        "reasoning": reasoning,
        "answer": answer,
        "failure_mode": None,
    }


def summarize(records: list[dict]) -> dict:
    """Compute parse-success statistics over a list of records."""
    n = len(records)
    n_ok = sum(1 for r in records if r["parse_ok"])
    failures = {
        "no_marker": 0,
        "multiple_markers": 0,
        "empty_answer": 0,
    }
    for r in records:
        if not r["parse_ok"]:
            failures[r["failure_mode"]] += 1
    ans_lens = [len((r["answer"] or "").split()) for r in records if r["parse_ok"]]
    reas_lens = [len((r["reasoning"] or "").split()) for r in records if r["parse_ok"]]

    def _stats(xs: list[int]) -> dict:
        if not xs:
            return {"n": 0}
        return {
            "n": len(xs),
            "mean": round(statistics.mean(xs), 1),
            "median": int(statistics.median(xs)),
            "min": min(xs),
            "max": max(xs),
            "p10": int(statistics.quantiles(xs, n=10)[0]) if len(xs) >= 10 else min(xs),
            "p90": int(statistics.quantiles(xs, n=10)[-1]) if len(xs) >= 10 else max(xs),
        }

    return {
        "n_total": n,
        "n_parse_ok": n_ok,
        "parse_success_rate": round(n_ok / n, 4) if n else 0.0,
        "parse_failure_rate": round(1 - n_ok / n, 4) if n else 0.0,
        "failures": failures,
        "answer_length_words": _stats(ans_lens),
        "reasoning_length_words": _stats(reas_lens),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+",
                        help="One or more JSONL files. Each record must have "
                             "{id, ugf_response}.")
    parser.add_argument("--text-field", default="ugf_response",
                        help="Field name holding the generation text "
                             "(default: ugf_response).")
    parser.add_argument("--out", default=None,
                        help="Optional path to write summary JSON. If unset, "
                             "prints to stdout.")
    parser.add_argument("--print-failures", action="store_true",
                        help="Print id + first 200 chars of each parse failure.")
    args = parser.parse_args()

    parsed: list[dict] = []
    failed_examples: list[tuple[str, str, str]] = []  # (id, failure_mode, sample)
    for path in args.inputs:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                text = rec.get(args.text_field, "") or ""
                result = extract_answer(text)
                result["id"] = rec.get("id", "")
                parsed.append(result)
                if not result["parse_ok"]:
                    failed_examples.append(
                        (result["id"], result["failure_mode"], text[:200])
                    )

    summary = summarize(parsed)
    fallback_threshold = 0.05
    summary["fallback_triggered"] = summary["parse_failure_rate"] > fallback_threshold
    summary["fallback_threshold"] = fallback_threshold

    if args.print_failures:
        print(f"--- {len(failed_examples)} parse failures ---")
        for rid, mode, sample in failed_examples[:50]:
            print(f"  [{mode}] {rid}: {sample!r}")
        if len(failed_examples) > 50:
            print(f"  ... and {len(failed_examples) - 50} more")
        print()

    out_str = json.dumps(summary, indent=2)
    if args.out:
        with open(args.out, "w") as f:
            f.write(out_str)
        print(f"Wrote {args.out}")
    print(out_str)


if __name__ == "__main__":
    main()
