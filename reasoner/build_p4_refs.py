"""
Generate P4 references in v2 think-answer format, for Stage-1 DPO "chosen" examples.

P4 = gold-standard English reasoning (gpt-oss-120b, medium effort) translated to
UGF. For DPO the reference must be a valid v2 completion — reasoning, the
phrasal marker, then the answer — so the contrast against the model's own
rollouts is about *content/on-topic-ness*, not format. We therefore:

  1. Ask gpt-oss-120b (English) to reason and end with an explicit
     "Final answer: <one sentence>" line.
  2. Split the English on that cue → (reasoning_en, answer_en).
  3. Translate each part to UGF via mr_structured_translator (the split is the
     noisy step the design doc flagged; the explicit cue keeps the answer span
     clean — see docs/dpo-stage1-design-2026-05-22.md).
  4. Compose "{reasoning_ugf} So my answer is: {answer_ugf}" and validate
     (UGF-compliant + parse_ok via the same checks the reward uses).

Output: corpus/processed/p4_refs.jsonl. Records carry `compliant` and
`parse_ok`; the pair miner uses only refs that pass both.

Sequential (one prompt at a time) — naturally well under MR's 200 rpm cap, so
no token bucket needed. Do NOT run concurrent MR generation alongside it.

Usage (on fortyfive):
    python -m reasoner.build_p4_refs \\
        --prompts corpus/processed/rl_train_prompts.jsonl \\
        --out corpus/processed/p4_refs.jsonl
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from eval.run_target_probe import mr_chat            # reuses the 422-retry MR client
from translator.mr_structured_translator import translate as mr_translate
from corpus.generation.validate_ugf import validate_ugf
from eval.parse_v2_answer import extract_answer

ANSWER_MARKER = "So my answer is:"

ENGLISH_INSTRUCTION = (
    "Reason carefully and concisely about the following, then on a new final "
    "line write exactly 'Final answer: ' followed by a single clear sentence "
    "stating your answer.\n\n{q}"
)
_FINAL_RE = re.compile(r"final answer\s*:\s*", re.IGNORECASE)


def split_reasoning_answer(english: str) -> tuple[str, str]:
    """Split on the last 'Final answer:' cue. Fallback: last sentence as answer."""
    m = None
    for m in _FINAL_RE.finditer(english):
        pass  # keep the last match
    if m is not None:
        reasoning = english[: m.start()].strip()
        answer = english[m.end():].strip()
        if reasoning and answer:
            return reasoning, answer
    # Fallback: split off the last sentence.
    parts = re.split(r"(?<=[.!?])\s+", english.strip())
    if len(parts) >= 2:
        return " ".join(parts[:-1]).strip(), parts[-1].strip()
    return english.strip(), english.strip()


def build_one(english_query: str, en_max_tokens: int, retries: int) -> dict:
    t0 = time.time()
    en = mr_chat(
        [{"role": "user", "content": ENGLISH_INSTRUCTION.format(q=english_query)}],
        max_tokens=en_max_tokens,
        reasoning_effort="medium",
    )
    en_text = en["content"]
    if not en_text:
        return {"completion": "", "compliant": False, "parse_ok": False,
                "reason": "empty_english", "latency_s": round(time.time() - t0, 2)}

    reasoning_en, answer_en = split_reasoning_answer(en_text)
    r_tl = mr_translate(reasoning_en, max_retries=retries, reasoning_effort="medium", max_tokens=6000)
    a_tl = mr_translate(answer_en, max_retries=retries, reasoning_effort="medium", max_tokens=2000)

    reasoning_ugf = r_tl["translation"].strip()
    answer_ugf = a_tl["translation"].strip()
    # Guard: the marker phrase must not already appear in either span (else two markers).
    reasoning_ugf = _FINAL_RE.sub("", reasoning_ugf)
    if ANSWER_MARKER.lower() in reasoning_ugf.lower() or ANSWER_MARKER.lower() in answer_ugf.lower():
        return {"completion": "", "compliant": False, "parse_ok": False,
                "reason": "marker_in_span", "en_intermediate": en_text,
                "latency_s": round(time.time() - t0, 2)}

    completion = f"{reasoning_ugf} {ANSWER_MARKER} {answer_ugf}"
    compliant, violations = validate_ugf(completion)
    parsed = extract_answer(completion)
    return {
        "completion": completion,
        "reasoning": reasoning_ugf,
        "answer": answer_ugf,
        "compliant": compliant,
        "parse_ok": parsed["parse_ok"],
        "violations": violations[:15],
        "en_intermediate": en_text,
        "reason": "ok",
        "latency_s": round(time.time() - t0, 2),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompts", default="corpus/processed/rl_train_prompts.jsonl")
    parser.add_argument("--out", default="corpus/processed/p4_refs.jsonl")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--en-max-tokens", type=int, default=4000)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--resume", action="store_true",
                        help="Skip prompt ids already present in --out.")
    args = parser.parse_args()

    prompts = []
    with open(args.prompts) as f:
        for line in f:
            line = line.strip()
            if line:
                prompts.append(json.loads(line))
    if args.limit:
        prompts = prompts[: args.limit]

    done_ids = set()
    if args.resume and Path(args.out).exists():
        with open(args.out) as f:
            for line in f:
                try:
                    done_ids.add(json.loads(line)["id"])
                except Exception:
                    pass
        print(f"Resume: {len(done_ids)} ids already done")

    n_ok = n_compliant = 0
    mode = "a" if (args.resume and Path(args.out).exists()) else "w"
    with open(args.out, mode, encoding="utf-8") as fout:
        for i, p in enumerate(prompts):
            pid = p.get("id", str(i))
            if pid in done_ids:
                continue
            try:
                res = build_one(p["english_query"], args.en_max_tokens, args.retries)
            except Exception as e:
                res = {"completion": "", "compliant": False, "parse_ok": False, "reason": f"error: {e}"}
            ok = bool(res.get("compliant") and res.get("parse_ok"))
            n_ok += 1
            n_compliant += int(ok)
            fout.write(json.dumps({
                "id": pid,
                "prompt": p["english_query"],
                "track": p.get("track", ""),
                "chosen": res.get("completion", ""),
                "reasoning": res.get("reasoning", ""),
                "answer": res.get("answer", ""),
                "compliant": res.get("compliant", False),
                "parse_ok": res.get("parse_ok", False),
                "reason": res.get("reason", ""),
                "en_intermediate": res.get("en_intermediate", ""),
            }, ensure_ascii=False) + "\n")
            fout.flush()
            if (i + 1) % 10 == 0 or i + 1 == len(prompts):
                print(f"[{i+1}/{len(prompts)}] usable={n_compliant}/{n_ok} "
                      f"({n_compliant/max(n_ok,1):.0%})", flush=True)

    print(f"Done. {n_compliant}/{n_ok} usable P4 refs -> {args.out}")


if __name__ == "__main__":
    main()
