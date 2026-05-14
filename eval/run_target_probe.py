"""
Run the P4-vs-P5-vs-Reasoner target-probe experiment.

For each prompt in eval/sets/cot_target_probe_50.jsonl, generate three R_UGF
responses, one per condition:

  Reasoner  — Q_EN → TL → Q_UGF → trained v1 200M SFT Reasoner → R_UGF
  P4        — Q_EN → gpt-oss-120b (full EN reasoning) → TL → R_UGF
  P5        — Q_EN → gpt-oss-120b (with UGF system prompt) → R_UGF

Output: three JSONL files for downstream judging, plus one combined file
that has all three responses per prompt for inspection.

Usage:
    python -m eval.run_target_probe \\
        --fixture eval/sets/cot_target_probe_50.jsonl \\
        --reasoner-ckpt checkpoints/reasoner_sft_v1/final.pt \\
        --out-dir eval/results/_jsonl/
"""

import argparse
import json
import os
import ssl
import sys
import time
import urllib.request
from pathlib import Path

import torch
import yaml
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

from corpus.generation.generate_reasoning import (
    CONTENT_TYPES, SYSTEM_PROMPT, FEWSHOT_EXEMPLARS,
)
from corpus.generation.validate_ugf import validate_ugf
from translator.mr_structured_translator import translate as mr_translate
from reasoner.model import Reasoner, ReasonerConfig
from tokenizer.ugf_tokenizer import UGFTokenizer

CONFIG_PATH = Path(__file__).parent.parent / "corpus" / "generation" / "config.yaml"
with open(CONFIG_PATH) as f:
    CONFIG = yaml.safe_load(f)
load_dotenv(Path(__file__).parent.parent / ".env")

MR_URL = f"{CONFIG['mindrouter']['base_url']}/chat/completions"
MR_KEY = os.environ.get("MINDROUTER_API_KEY", "")


def mr_chat(messages: list[dict], model: str = "openai/gpt-oss-120b",
            max_tokens: int = 2000, reasoning_effort: str = "low",
            temperature: float = 0.7, timeout: int = 120) -> dict:
    """Generic MindRouter chat-completion call. No structured-output constraint."""
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "reasoning_effort": reasoning_effort,
        "temperature": temperature,
    }
    headers = {
        "Authorization": f"Bearer {MR_KEY}",
        "Content-Type": "application/json",
    }
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(
        MR_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    t0 = time.time()
    with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
        body = json.loads(resp.read())
    content = (body.get("choices") or [{}])[0].get("message", {}).get("content", "")
    return {
        "content": (content or "").strip(),
        "latency_s": round(time.time() - t0, 2),
    }


def generate_p4(english_query: str,
                en_max_tokens: int = 4000,
                en_reasoning_effort: str = "medium",
                translator_max_retries: int = 5) -> dict:
    """Q_EN → gpt-oss-120b (EN reasoning, medium effort) → TL → R_UGF.

    Uses medium reasoning_effort for the English reasoning step (matching the
    v1 corpus generator's setting for gpt-oss-120b). The translator step uses
    a higher retry budget than the bench default because long English
    reasoning traces have more chances for OOV words to slip through.
    """
    t0 = time.time()
    en = mr_chat(
        [{"role": "user", "content": english_query}],
        max_tokens=en_max_tokens,
        reasoning_effort=en_reasoning_effort,
    )
    en_response = en["content"]
    if not en_response:
        return {"ugf": "", "en_intermediate": "", "compliant": False,
                "violations": [], "translator_attempts": 0,
                "latency_s": round(time.time() - t0, 2)}
    # Translator uses more retries + medium reasoning for long inputs.
    tl = mr_translate(
        en_response,
        max_retries=translator_max_retries,
        reasoning_effort="medium",
        max_tokens=6000,
    )
    return {
        "ugf": tl["translation"],
        "en_intermediate": en_response,
        "compliant": tl["compliant"],
        "violations": tl["violations"],
        "translator_attempts": tl["attempts"],
        "latency_s": round(time.time() - t0, 2),
    }


def generate_p5(english_query: str, content_type: str,
                topic: str,
                max_tokens: int = 10240,
                reasoning_effort: str = "medium",
                max_retries: int = 3) -> dict:
    """Q_EN → gpt-oss-120b with UGF system prompt → R_UGF.

    Faithful reproduction of corpus/generation/generate_reasoning.generate_one()
    in synchronous form: same SYSTEM_PROMPT, same FEWSHOT_EXEMPLARS injection
    between system and user, same reasoning_effort=medium, same generous
    max_tokens (2048 + 8192 overhead) used in the v1 campaign that hit
    95–99% compliance.
    """
    t0 = time.time()
    # The system prompt + few-shot anchors the model on UGF register; the
    # template re-wraps the user prompt the way the v1 corpus generator did.
    user_prompt = CONTENT_TYPES[content_type].format(topic=topic)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for ex_user, ex_assistant in FEWSHOT_EXEMPLARS:
        messages.append({"role": "user", "content": ex_user})
        messages.append({"role": "assistant", "content": ex_assistant})
    messages.append({"role": "user", "content": user_prompt})

    response_text = ""
    compliant = False
    violations: list[str] = []
    attempts = 0
    for attempt in range(max_retries):
        attempts += 1
        r = mr_chat(
            messages,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
        )
        response_text = r["content"]
        if not response_text:
            break
        compliant, violations = validate_ugf(response_text)
        if compliant:
            break
        messages.append({"role": "assistant", "content": response_text})
        messages.append({
            "role": "user",
            "content": (
                f"Your response contains words or symbols not in the allowed list: "
                f"{', '.join(repr(v) for v in violations[:15])}. "
                f"Rewrite the entire response. Replace each disallowed word with "
                f"a description using only allowed words. Remove any markdown "
                f"formatting."
            ),
        })
    return {
        "ugf": response_text,
        "compliant": compliant,
        "violations": violations,
        "attempts": attempts,
        "latency_s": round(time.time() - t0, 2),
    }


@torch.no_grad()
def generate_reasoner(reasoner, tokenizer, topic: str, content_type: str,
                      device, max_new_tokens: int = 300,
                      temperature: float = 0.8, top_k: int = 50,
                      top_p: float = 0.9) -> dict:
    """Q_EN topic → TL → Q_UGF → wrap in content_type template → Reasoner → R_UGF."""
    t0 = time.time()
    # Translate topic to UGF
    tl = mr_translate(topic)
    ugf_topic = tl["translation"]
    wrapped = CONTENT_TYPES[content_type].format(topic=ugf_topic)
    # Tokenize and run Reasoner
    bos = tokenizer.bos_token_id
    body = tokenizer.encode(wrapped, add_special_tokens=False)
    ids = ([bos] if bos is not None else []) + body
    input_ids = torch.tensor([ids], dtype=torch.long, device=device)
    out = reasoner.generate(
        input_ids,
        max_new_tokens=max_new_tokens,
        temperature=temperature,
        top_k=top_k,
        top_p=top_p,
        eos_token_id=tokenizer.eos_token_id,
    )
    completion_ids = out[0, input_ids.shape[1]:].tolist()
    ugf_response = tokenizer.decode(completion_ids, skip_special_tokens=False)
    return {
        "ugf": ugf_response,
        "ugf_topic": ugf_topic,
        "wrapped_prompt": wrapped,
        "topic_translator_compliant": tl["compliant"],
        "latency_s": round(time.time() - t0, 2),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", default="eval/sets/cot_target_probe_50.jsonl")
    parser.add_argument(
        "--reasoner-ckpt",
        default="checkpoints/reasoner_sft_v1/final.pt",
    )
    parser.add_argument(
        "--out-dir",
        default="eval/results/_jsonl/",
    )
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit number of prompts (debug).")
    parser.add_argument("--skip-reasoner", action="store_true",
                        help="Skip Reasoner condition (debug).")
    args = parser.parse_args()

    fixture = []
    with open(args.fixture) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            fixture.append(json.loads(line))
    if args.limit:
        fixture = fixture[: args.limit]
    print(f"Fixture: {len(fixture)} prompts")

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    p4_path = out_dir / f"cot_target_probe_p4_{ts}.jsonl"
    p5_path = out_dir / f"cot_target_probe_p5_{ts}.jsonl"
    reasoner_path = out_dir / f"cot_target_probe_reasoner_{ts}.jsonl"
    combined_path = out_dir / f"cot_target_probe_combined_{ts}.jsonl"
    print(f"Outputs:\n  {p4_path}\n  {p5_path}\n  {reasoner_path}\n  {combined_path}")

    # Load Reasoner (unless skipping)
    reasoner = tokenizer = device = None
    if not args.skip_reasoner:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(f"Loading Reasoner from {args.reasoner_ckpt} on {device}...")
        ckpt = torch.load(args.reasoner_ckpt, map_location="cpu", weights_only=False)
        cfg = ReasonerConfig(**ckpt["config"]) if isinstance(ckpt["config"], dict) else ckpt["config"]
        reasoner = Reasoner(cfg)
        reasoner.load_state_dict(ckpt["model_state_dict"])
        reasoner = reasoner.to(device)
        reasoner.eval()
        tokenizer = UGFTokenizer()
        print(f"  ckpt step={ckpt.get('step', '?')}")

    if not MR_KEY:
        raise SystemExit("MINDROUTER_API_KEY not set")

    t_start = time.time()
    p4_f = open(p4_path, "w", encoding="utf-8")
    p5_f = open(p5_path, "w", encoding="utf-8")
    reasoner_f = open(reasoner_path, "w", encoding="utf-8") if not args.skip_reasoner else None
    combined_f = open(combined_path, "w", encoding="utf-8")

    try:
        for i, prompt in enumerate(fixture):
            pid = prompt["id"]
            print(f"\n[{i+1}/{len(fixture)}] {pid}")

            # P4
            try:
                p4 = generate_p4(prompt["english_query"])
                p4_f.write(json.dumps({
                    "id": pid,
                    "english_query": prompt["english_query"],
                    "ugf_response": p4["ugf"],
                    "en_intermediate": p4["en_intermediate"],
                    "compliant": p4["compliant"],
                    "translator_attempts": p4["translator_attempts"],
                    "latency_s": p4["latency_s"],
                }, ensure_ascii=False) + "\n")
                p4_f.flush()
                print(f"  P4: {p4['latency_s']}s, compliant={p4['compliant']}")
            except Exception as e:
                p4 = {"ugf": f"<P4_ERROR: {e}>", "compliant": False}
                print(f"  P4 ERROR: {e}")

            # P5 — uses the v1 corpus-generator recipe: SYSTEM_PROMPT +
            # FEWSHOT_EXEMPLARS + content-type wrapping + medium effort.
            try:
                p5 = generate_p5(
                    prompt["english_query"],
                    content_type=prompt["content_type"],
                    topic=prompt["topic"],
                )
                p5_f.write(json.dumps({
                    "id": pid,
                    "english_query": prompt["english_query"],
                    "ugf_response": p5["ugf"],
                    "compliant": p5["compliant"],
                    "attempts": p5["attempts"],
                    "latency_s": p5["latency_s"],
                }, ensure_ascii=False) + "\n")
                p5_f.flush()
                print(f"  P5: {p5['latency_s']}s, compliant={p5['compliant']}, attempts={p5['attempts']}")
            except Exception as e:
                p5 = {"ugf": f"<P5_ERROR: {e}>", "compliant": False}
                print(f"  P5 ERROR: {e}")

            # Reasoner
            if not args.skip_reasoner:
                try:
                    r = generate_reasoner(
                        reasoner, tokenizer,
                        prompt["topic"], prompt["content_type"],
                        device,
                    )
                    reasoner_f.write(json.dumps({
                        "id": pid,
                        "english_query": prompt["english_query"],
                        "ugf_response": r["ugf"],
                        "ugf_topic": r["ugf_topic"],
                        "wrapped_prompt": r["wrapped_prompt"],
                        "content_type": prompt["content_type"],
                        "latency_s": r["latency_s"],
                    }, ensure_ascii=False) + "\n")
                    reasoner_f.flush()
                    print(f"  Reasoner: {r['latency_s']}s")
                except Exception as e:
                    r = {"ugf": f"<REASONER_ERROR: {e}>"}
                    print(f"  Reasoner ERROR: {e}")
            else:
                r = {"ugf": "<SKIPPED>"}

            # Combined row
            combined_f.write(json.dumps({
                "id": pid,
                "english_query": prompt["english_query"],
                "topic": prompt["topic"],
                "content_type": prompt["content_type"],
                "track": prompt.get("track", "unknown"),
                "responses": {
                    "p4": p4.get("ugf", ""),
                    "p5": p5.get("ugf", ""),
                    "reasoner": r.get("ugf", ""),
                },
            }, ensure_ascii=False) + "\n")
            combined_f.flush()
    finally:
        p4_f.close()
        p5_f.close()
        if reasoner_f:
            reasoner_f.close()
        combined_f.close()

    total = time.time() - t_start
    print(f"\nDone in {total:.0f}s ({total/60:.1f} min)")
    print(f"P4:       {p4_path}")
    print(f"P5:       {p5_path}")
    print(f"Reasoner: {reasoner_path}")
    print(f"Combined: {combined_path}")


if __name__ == "__main__":
    main()
