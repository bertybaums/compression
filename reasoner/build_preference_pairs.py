"""
Mine preference pairs for Stage-1 DPO/APO (docs/dpo-stage1-design-2026-05-22.md).

For each RL prompt:
  - Sample N rollouts from the SFT-v2 policy (anti-rep decode, temp ~0.9).
  - Score each: structural gates (rl_reward) → for gate-passers, the Nemotron
    jury weighted reward on the answer span (rl_judge). Gate failures (off-topic
    doom-loops, vocab/parse fails) keep reward 0 and are prime "rejected" picks.
  - Form pairs:
      Pattern 2 (primary): chosen = P4 reference (reliably on-topic), rejected =
        the worst on-policy rollout (the off-topic boilerplate v3 collapsed onto).
      Pattern 3: chosen = best on-policy rollout, rejected = worst — only when the
        reward gap clears --margin and the best passed all gates.

Output JSONL: {prompt, chosen, rejected, track, chosen_src, rejected_src,
chosen_score, rejected_score}. Reused by reasoner/train_dpo.py.

Reuses rl_rollout decode settings, rl_reward gates + doom-loop rule, and the
rl_judge Nemotron jury behind the shared AsyncTokenBucket. Don't run other MR
generation concurrently.

Usage (on fortyfive):
    python -m reasoner.build_preference_pairs \\
        --reasoner checkpoints/reasoner_sft_v2/final.pt \\
        --prompts corpus/processed/rl_train_prompts.jsonl \\
        --p4-refs corpus/processed/p4_refs.jsonl \\
        --out corpus/processed/dpo_pairs.jsonl \\
        --n-rollouts 6
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import aiohttp
import torch
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

from reasoner.model import Reasoner, ReasonerConfig
from reasoner.rl_judge import MRJudge
from reasoner.rl_reward import compute_reward
from tokenizer.ugf_tokenizer import UGFTokenizer
from corpus.generation.rate_limiter import AsyncTokenBucket


@torch.no_grad()
def rollout(model, tok, prompt, max_new_tokens, temperature, top_k, top_p,
            repetition_penalty, no_repeat_ngram_size, device) -> str:
    bos = tok.bos_token_id
    ids = ([bos] if bos is not None else []) + tok.encode(prompt, add_special_tokens=False)
    inp = torch.tensor([ids], dtype=torch.long, device=device)
    out = model.generate(inp, max_new_tokens=max_new_tokens, temperature=temperature,
                         top_k=top_k, top_p=top_p, eos_token_id=tok.eos_token_id,
                         repetition_penalty=repetition_penalty,
                         no_repeat_ngram_size=no_repeat_ngram_size)
    return tok.decode(out[0, inp.shape[1]:].tolist(), skip_special_tokens=True).strip()


def load_jsonl(path):
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def get_mr_key():
    k = os.environ.get("MINDROUTER_API_KEY", "")
    if k:
        return k
    for cand in (Path.home() / "compression" / ".env", Path(__file__).parent.parent / ".env"):
        if cand.exists():
            for ln in open(cand):
                if ln.startswith("MINDROUTER_API_KEY="):
                    return ln.split("=", 1)[1].strip()
    return ""


async def score_rollouts(judge, session, prompt, rollouts):
    """Return a list of dicts {text, reward, reason} aligned to rollouts."""
    gated = [compute_reward(t) for t in rollouts]            # gates only
    # Judge the gate-passers (reason == 'judge_pending') on their answer span.
    pending = [(i, g.answer_text) for i, g in enumerate(gated) if g.reason == "judge_pending"]
    results = {}
    if pending:
        scores = await asyncio.gather(*[judge.score(session, prompt, a) for _, a in pending])
        for (i, _), s in zip(pending, scores):
            results[i] = s
    out = []
    for i, (t, g) in enumerate(zip(rollouts, gated)):
        if g.reason == "judge_pending":
            s = results.get(i)
            if s is None:
                out.append({"text": t, "reward": 0.0, "reason": "judge_fail"})
            else:
                fo = compute_reward(t, judge_scores=s, judge_n_valid=int(s.get("_n_valid", 0)))
                out.append({"text": t, "reward": fo.reward, "reason": fo.reason})
        else:
            out.append({"text": t, "reward": g.reward, "reason": g.reason})
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reasoner", default="checkpoints/reasoner_sft_v2/final.pt")
    parser.add_argument("--prompts", default="corpus/processed/rl_train_prompts.jsonl")
    parser.add_argument("--p4-refs", default="corpus/processed/p4_refs.jsonl")
    parser.add_argument("--out", default="corpus/processed/dpo_pairs.jsonl")
    parser.add_argument("--n-rollouts", type=int, default=6)
    parser.add_argument("--max-new-tokens", type=int, default=400)
    parser.add_argument("--temperature", type=float, default=0.9)
    parser.add_argument("--margin", type=float, default=0.15,
                        help="Min reward gap for a Pattern-3 (best vs worst on-policy) pair.")
    parser.add_argument("--max-pairs-per-prompt", type=int, default=2)
    parser.add_argument("--judge-rate-per-sec", type=float, default=1.0)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    load_dotenv(Path(__file__).parent.parent / ".env")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    tok = UGFTokenizer()
    ckpt = torch.load(args.reasoner, map_location="cpu", weights_only=False)
    config = ReasonerConfig(**ckpt["config"]) if isinstance(ckpt["config"], dict) else ckpt["config"]
    model = Reasoner(config); model.load_state_dict(ckpt["model_state_dict"])
    model = model.to(device).eval()
    print(f"Loaded SFT-v2 (step {ckpt.get('step','?')})")

    prompts = load_jsonl(args.prompts)
    if args.limit:
        prompts = prompts[: args.limit]
    # P4 refs keyed by id; only compliant + parse_ok are usable as 'chosen'.
    p4 = {}
    if Path(args.p4_refs).exists():
        for r in load_jsonl(args.p4_refs):
            if r.get("compliant") and r.get("parse_ok") and r.get("chosen"):
                p4[r["id"]] = r["chosen"]
    print(f"{len(prompts)} prompts; {len(p4)} usable P4 refs")

    judge = MRJudge(
        f"{os.environ.get('MR_URL', 'https://mindrouter.uidaho.edu/v1')}/chat/completions",
        get_mr_key(),
        AsyncTokenBucket(rate_per_sec=args.judge_rate_per_sec, burst=10),
        model="Nemotron-3-Super-120b", jury_size=3,
    )

    loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
    session = loop.run_until_complete(_session())

    n_pairs = n_p2 = n_p3 = 0
    t0 = time.time()
    with open(args.out, "w", encoding="utf-8") as fout:
        for i, p in enumerate(prompts):
            pid, q, track = p.get("id", str(i)), p["english_query"], p.get("track", "")
            rolls = [rollout(model, tok, q, args.max_new_tokens, args.temperature,
                             50, 0.9, 1.2, 4, device) for _ in range(args.n_rollouts)]
            scored = loop.run_until_complete(score_rollouts(judge, session, q, rolls))
            scored.sort(key=lambda r: r["reward"])
            worst, best = scored[0], scored[-1]

            pairs = []
            # Pattern 2: P4 ref (chosen) vs worst on-policy rollout (rejected).
            if pid in p4 and worst["text"] and p4[pid].strip() != worst["text"].strip():
                pairs.append((p4[pid], worst["text"], "p4", "onpolicy_worst",
                              1.0, worst["reward"]))
                n_p2 += 1
            # Pattern 3: best vs worst on-policy, if best is clean and gap is real.
            if (best["reason"] == "ok" and (best["reward"] - worst["reward"]) >= args.margin
                    and best["text"].strip() != worst["text"].strip()):
                pairs.append((best["text"], worst["text"], "onpolicy_best", "onpolicy_worst",
                              best["reward"], worst["reward"]))
                n_p3 += 1

            for chosen, rejected, csrc, rsrc, cs, rs in pairs[: args.max_pairs_per_prompt]:
                fout.write(json.dumps({
                    "id": pid, "prompt": q, "track": track,
                    "chosen": chosen, "rejected": rejected,
                    "chosen_src": csrc, "rejected_src": rsrc,
                    "chosen_score": round(cs, 4), "rejected_score": round(rs, 4),
                }, ensure_ascii=False) + "\n")
                n_pairs += 1
            fout.flush()
            if (i + 1) % 10 == 0 or i + 1 == len(prompts):
                print(f"[{i+1}/{len(prompts)}] pairs={n_pairs} (P2={n_p2} P3={n_p3}) "
                      f"{(i+1)/(time.time()-t0)*60:.1f} prompts/min", flush=True)

    loop.run_until_complete(session.close()); loop.close()
    print(f"Done. {n_pairs} pairs (P2={n_p2} P3={n_p3}) -> {args.out}")


async def _session():
    return aiohttp.ClientSession()


if __name__ == "__main__":
    main()
