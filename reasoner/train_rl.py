"""
GRPO trainer for the v2 Reasoner.

Self-play RL with:
  - Reward = weighted 4-dim judge score (Nemotron-3-Super-120b jury), gated
    on UGF compliance + parse_ok + no doom-loop + answer length floor.
  - Group-relative advantage normalization (the GR in GRPO).
  - PPO-style importance-ratio clipping.
  - KL penalty against the frozen v2-SFT reference policy.
  - SFT-mix anchor: every gradient step also includes a CE loss term on
    a batch of CoT-corpus examples to prevent distributional drift.

See docs/rl-design-2026-05-18.md for the locked design + rationale.

Usage:
    python -m reasoner.train_rl --config configs/reasoner_rl_v1.yaml \\
        --resume checkpoints/reasoner_sft_v2/final.pt
"""

import argparse
import asyncio
import copy
import json
import math
import os
import sys
import time
from pathlib import Path

import aiohttp
import torch
import torch.nn.functional as F
import yaml
from dotenv import load_dotenv
from torch.utils.data import DataLoader

sys.path.insert(0, str(Path(__file__).parent.parent))

from reasoner.model import Reasoner, ReasonerConfig
from reasoner.data_sft_v2 import UGFSFTv2Dataset, sft_v2_collate_fn
from reasoner.rl_judge import MRJudge
from reasoner.rl_reward import compute_reward, reward_diagnostics
from reasoner.rl_rollout import collect_rollouts, compute_group_advantages
from reasoner.train import load_checkpoint, save_checkpoint
from tokenizer.ugf_tokenizer import UGFTokenizer
from corpus.generation.rate_limiter import AsyncTokenBucket


def load_prompts(path: str) -> list[str]:
    """One prompt per line, or JSONL with {english_query} / {prompt} / {question} / {topic}."""
    prompts: list[str] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("{"):
                r = json.loads(line)
                p = (r.get("english_query")
                     or r.get("prompt")
                     or r.get("question")
                     or r.get("topic")
                     or "")
                if p:
                    prompts.append(p.strip())
            else:
                prompts.append(line)
    return prompts


async def judge_batch(judge, session, items: list[tuple[str, str]]) -> list[dict | None]:
    """Score (prompt, answer) pairs in parallel. Returns list aligned to items."""
    coros = [judge.score(session, p, a) for p, a in items]
    return await asyncio.gather(*coros)


def grpo_loss(
    rollouts: list,
    new_logprobs: list[torch.Tensor],
    clip_ratio: float,
    kl_coef: float,
) -> tuple[torch.Tensor, dict]:
    """Compute GRPO loss for a batch of rollouts.

    Each rollout in `rollouts` has .advantage, .old_logprobs, .ref_logprobs.
    `new_logprobs[i]` is the per-token logprob under the current (training) policy
    for rollout i's completion (computed via a fresh forward pass on the trainer side).

    Returns:
        loss (scalar tensor) and a diagnostics dict.
    """
    policy_terms = []
    kl_terms = []
    n_kept = 0
    for r, new_lp in zip(rollouts, new_logprobs):
        if r.advantage is None:
            continue
        old_lp = r.old_logprobs.to(new_lp.device)
        ref_lp = r.ref_logprobs.to(new_lp.device)
        # Truncate to the shorter of the three (in case of edge cases).
        T = min(new_lp.shape[0], old_lp.shape[0], ref_lp.shape[0])
        if T == 0:
            continue
        new_lp = new_lp[:T]
        old_lp = old_lp[:T]
        ref_lp = ref_lp[:T]
        # Importance ratio.
        ratio = (new_lp - old_lp).exp()
        adv = r.advantage
        unclipped = ratio * adv
        clipped = torch.clamp(ratio, 1 - clip_ratio, 1 + clip_ratio) * adv
        # Negative because we maximize the objective; sum across the sequence.
        policy_terms.append(-torch.min(unclipped, clipped).mean())
        # KL approximation: E[new_lp - ref_lp] (per-token, mean).
        kl_terms.append((new_lp - ref_lp).mean())
        n_kept += 1
    if n_kept == 0:
        loss = torch.tensor(0.0, requires_grad=True)
        return loss, {"n_used": 0, "policy_loss": 0.0, "kl": 0.0}
    policy_loss = torch.stack(policy_terms).mean()
    kl = torch.stack(kl_terms).mean()
    total = policy_loss + kl_coef * kl
    return total, {
        "n_used": n_kept,
        "policy_loss": float(policy_loss.item()),
        "kl": float(kl.item()),
        "total_loss": float(total.item()),
    }


def policy_logprobs_for_rollout(model, full_ids: torch.Tensor, prompt_len: int, device) -> torch.Tensor:
    """Re-forward a sequence through the (training) policy; return completion logprobs WITH gradient."""
    ids = full_ids.unsqueeze(0).to(device)
    if ids.shape[1] > model.config.max_seq_len:
        ids = ids[:, -model.config.max_seq_len:]
        prompt_len = max(0, prompt_len - (full_ids.shape[0] - ids.shape[1]))
    out = model(ids)
    logits = out["logits"][0]
    log_probs = F.log_softmax(logits, dim=-1)
    targets = ids[0, 1:]
    target_logps = log_probs[:-1].gather(-1, targets.unsqueeze(-1)).squeeze(-1)
    return target_logps[prompt_len - 1 :]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, required=True)
    parser.add_argument("--resume", type=str, required=True,
                        help="SFT v2 checkpoint to init policy + ref from.")
    args = parser.parse_args()

    with open(args.config) as f:
        cfg = yaml.safe_load(f)
    load_dotenv(Path(__file__).parent.parent / ".env")

    model_cfg = cfg["model"]
    train_cfg = cfg["training"]
    rl_cfg = cfg["rl"]
    data_cfg = cfg["data"]

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    tokenizer = UGFTokenizer()
    config = ReasonerConfig(
        vocab_size=tokenizer.vocab_size,
        d_model=model_cfg["d_model"],
        n_layers=model_cfg["n_layers"],
        n_heads=model_cfg["n_heads"],
        n_kv_heads=model_cfg["n_kv_heads"],
        d_ff=model_cfg["d_ff"],
        max_seq_len=model_cfg["max_seq_len"],
        dropout=model_cfg.get("dropout", 0.0),
        tie_embeddings=model_cfg.get("tie_embeddings", True),
    )
    print(f"Loading SFT v2 checkpoint: {args.resume}")
    policy = Reasoner(config).to(device)
    load_checkpoint(args.resume, policy)

    print("Cloning frozen reference policy.")
    ref_policy = Reasoner(config).to(device)
    ref_policy.load_state_dict(policy.state_dict())
    ref_policy.eval()
    for p in ref_policy.parameters():
        p.requires_grad_(False)

    optimizer = torch.optim.AdamW(
        policy.parameters(),
        lr=train_cfg["lr"],
        betas=(0.9, 0.95),
        weight_decay=train_cfg.get("weight_decay", 0.0),
    )

    # Optionally restore AdamW momentum/variance from the resume checkpoint
    # (used when continuing a prior RL run from its final/step checkpoint).
    if rl_cfg.get("resume_optimizer", False):
        ckpt = torch.load(args.resume, map_location="cpu", weights_only=False)
        if "optimizer_state_dict" in ckpt:
            optimizer.load_state_dict(ckpt["optimizer_state_dict"])
            print(f"Restored optimizer state from {args.resume} (step {ckpt.get('step', '?')})")
        else:
            print(f"WARNING: resume_optimizer set but no optimizer_state_dict in {args.resume}")
        del ckpt

    # Prompts.
    train_prompts = load_prompts(data_cfg["train_prompts"])
    print(f"Loaded {len(train_prompts)} train prompts from {data_cfg['train_prompts']}")

    # SFT-mix anchor.
    sft_anchor_path = data_cfg["sft_anchor"]
    sft_ds = UGFSFTv2Dataset(
        sft_anchor_path, tokenizer,
        max_seq_len=model_cfg["max_seq_len"],
    )
    sft_loader = DataLoader(
        sft_ds, batch_size=train_cfg.get("sft_batch_size", 4),
        shuffle=True, num_workers=0,
        collate_fn=lambda b: sft_v2_collate_fn(b, pad_id=tokenizer.pad_token_id),
        drop_last=True,
    )
    sft_iter = iter(sft_loader)
    print(f"SFT-anchor dataset: {len(sft_ds)} pairs")

    # Judge.
    mr_url = os.environ["MR_URL"] if os.environ.get("MR_URL") else \
             f"{cfg.get('mindrouter', {}).get('base_url', 'https://mindrouter.uidaho.edu/v1')}/chat/completions"
    mr_key = os.environ.get("MINDROUTER_API_KEY", "")
    if not mr_key:
        for ln in open(Path.home() / "compression" / ".env"):
            if ln.startswith("MINDROUTER_API_KEY="):
                mr_key = ln.split("=", 1)[1].strip()
                break
    rate_bucket = AsyncTokenBucket(
        rate_per_sec=rl_cfg.get("judge_rate_per_sec", 100/60),
        burst=rl_cfg.get("judge_burst", 10),
    )
    judge = MRJudge(
        mr_url, mr_key, rate_bucket,
        model=rl_cfg.get("judge_model", "Nemotron-3-Super-120b"),
        jury_size=rl_cfg.get("judge_jury", 3),
    )

    # Logging dirs.
    log_dir = Path(train_cfg["log_dir"])
    log_dir.mkdir(parents=True, exist_ok=True)
    ckpt_dir = Path(train_cfg["checkpoint_dir"])
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = log_dir / "rl_metrics.jsonl"
    samples_path = log_dir / "rl_samples.jsonl"

    # Halt-rule state.
    parse_fail_window = []  # last N parse-failure rates

    # Async event loop for judge dispatch.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    session = loop.run_until_complete(_make_session())

    prompt_cursor = 0
    n_steps = rl_cfg["max_steps"]
    batch_size_prompts = rl_cfg["batch_prompts"]
    n_per_prompt = rl_cfg["n_rollouts"]
    max_new_tokens = rl_cfg.get("max_new_tokens", 400)

    print(f"Starting RL: {n_steps} steps × {batch_size_prompts} prompts × {n_per_prompt} rollouts")
    print(f"            ~{batch_size_prompts * n_per_prompt * rl_cfg.get('judge_jury', 3)} judge calls per step")
    t0 = time.time()

    for step in range(1, n_steps + 1):
        step_t0 = time.time()
        # Sample prompts.
        prompts = []
        for _ in range(batch_size_prompts):
            prompts.append(train_prompts[prompt_cursor % len(train_prompts)])
            prompt_cursor += 1

        # 1. Collect rollouts (frozen policy snapshot under torch.no_grad).
        rollout_groups = collect_rollouts(
            policy, ref_policy, tokenizer, prompts,
            n_per_prompt=n_per_prompt,
            max_new_tokens=max_new_tokens,
            temperature=rl_cfg.get("temperature", 0.8),
            top_k=rl_cfg.get("top_k", 50),
            top_p=rl_cfg.get("top_p", 0.9),
            repetition_penalty=rl_cfg.get("repetition_penalty", 1.2),
            no_repeat_ngram_size=rl_cfg.get("no_repeat_ngram_size", 4),
            device=device,
        )

        # 2. Apply structural gates → identify items that need judging.
        flat_rollouts = [r for group in rollout_groups for r in group]
        outcomes = [compute_reward(r.completion_text) for r in flat_rollouts]  # gates only
        judge_inputs = []  # (rollout, prompt, answer)
        for r, o in zip(flat_rollouts, outcomes):
            if o.reason == "judge_pending":
                judge_inputs.append((r, r.prompt_text, o.answer_text))

        # 3. Dispatch judges.
        if judge_inputs:
            items = [(p, a) for _, p, a in judge_inputs]
            judge_results = loop.run_until_complete(judge_batch(judge, session, items))
        else:
            judge_results = []

        # 4. Finalize rewards.
        final_outcomes = []
        ji = 0
        for r, o in zip(flat_rollouts, outcomes):
            if o.reason == "judge_pending":
                scores = judge_results[ji]; ji += 1
                if scores is None:
                    # Judge fail — treat as zero reward but not a structural fail.
                    final_outcomes.append(o.__class__(0.0, "judge_fail", True, True, True, True, o.answer_text, None, None))
                else:
                    fo = compute_reward(r.completion_text, judge_scores=scores,
                                         judge_n_valid=int(scores.get("_n_valid", 0)))
                    final_outcomes.append(fo)
            else:
                final_outcomes.append(o)
            r.reward = final_outcomes[-1].reward
            r.reason = final_outcomes[-1].reason

        # 5. Group-relative advantages.
        for group in rollout_groups:
            advs = compute_group_advantages([r.reward for r in group])
            for r, a in zip(group, advs):
                r.advantage = a

        # 6-7. PPO inner loop: K epochs over this rollout batch. Each epoch
        # recomputes new-policy logprobs (the policy changed last epoch), so
        # the importance ratio diverges from 1 and the clipping engages. This
        # extracts more learning from each expensive rollout batch.
        ppo_epochs = rl_cfg.get("ppo_epochs", 4)
        sft_anchor_coef = rl_cfg.get("sft_anchor_coef", 0.1)
        last_rl_diag = {}
        last_sft_loss = 0.0
        for _epoch in range(ppo_epochs):
            new_logprobs = []
            for r in flat_rollouts:
                full_ids = torch.cat([r.prompt_ids, r.completion_ids])
                prompt_len = r.prompt_ids.shape[0]
                new_lp = policy_logprobs_for_rollout(policy, full_ids, prompt_len, device)
                new_logprobs.append(new_lp)

            rl_loss, rl_diag = grpo_loss(
                flat_rollouts, new_logprobs,
                clip_ratio=rl_cfg.get("clip_ratio", 0.2),
                kl_coef=rl_cfg.get("kl_coef", 0.05),
            )

            try:
                sft_batch = next(sft_iter)
            except StopIteration:
                sft_iter = iter(sft_loader)
                sft_batch = next(sft_iter)
            sft_input = sft_batch["input_ids"].to(device)
            sft_labels = sft_batch["labels"].to(device)
            sft_out = policy(sft_input, labels=sft_labels)
            sft_loss = sft_out["loss"]

            total_loss = rl_loss + sft_anchor_coef * sft_loss

            optimizer.zero_grad()
            total_loss.backward()
            torch.nn.utils.clip_grad_norm_(policy.parameters(), max_norm=1.0)
            optimizer.step()
            last_rl_diag = rl_diag
            last_sft_loss = float(sft_loss.item())
        rl_diag = last_rl_diag
        sft_loss = torch.tensor(last_sft_loss)

        # 8. Diagnostics.
        diag = reward_diagnostics(final_outcomes)
        diag.update({
            "step": step,
            "wall_s": round(time.time() - step_t0, 2),
            "rl_loss": rl_diag.get("total_loss", 0.0),
            "policy_loss": rl_diag.get("policy_loss", 0.0),
            "kl": rl_diag.get("kl", 0.0),
            "sft_loss": float(sft_loss.item()),
            "total_loss": float(total_loss.item()),
            "prompt_cursor": prompt_cursor,
        })
        with open(metrics_path, "a") as f:
            f.write(json.dumps(diag) + "\n")
        print(f"step {step:4d} | rew {diag['reward_mean']:.3f} | "
              f"ok {diag['rate_ok']:.1%} | parse_fail {diag['rate_parse_fail']:.1%} | "
              f"doom {diag['rate_doom_loop']:.1%} | "
              f"policy {rl_diag.get('policy_loss', 0):.3f} | "
              f"kl {rl_diag.get('kl', 0):.3f} | "
              f"sft {sft_loss.item():.3f} | "
              f"{diag['wall_s']:.0f}s", flush=True)

        # 9. Save a couple of sample rollouts.
        if step % rl_cfg.get("sample_log_every", 10) == 0:
            with open(samples_path, "a") as f:
                for r in flat_rollouts[:3]:
                    f.write(json.dumps({
                        "step": step,
                        "prompt": r.prompt_text,
                        "completion": r.completion_text,
                        "reward": r.reward,
                        "reason": r.reason,
                    }) + "\n")

        # 10. Halt rule.
        parse_fail_window.append(diag["rate_parse_fail"])
        if len(parse_fail_window) > 50:
            parse_fail_window.pop(0)
        if (len(parse_fail_window) >= 50 and
                sum(parse_fail_window) / 50 > 0.15):
            print("HALT: parse_failure_rate exceeded 15% over last 50 steps")
            break

        # 11. Save checkpoint.
        if step % rl_cfg.get("save_interval", 50) == 0:
            save_path = ckpt_dir / f"step-{step:06d}.pt"
            torch.save({
                "step": step,
                "model_state_dict": policy.state_dict(),
                "config": config.__dict__,
                "optimizer_state_dict": optimizer.state_dict(),
            }, save_path)
            print(f"  saved {save_path}", flush=True)

    # Final checkpoint.
    final_path = ckpt_dir / "final.pt"
    torch.save({
        "step": step,
        "model_state_dict": policy.state_dict(),
        "config": config.__dict__,
        "optimizer_state_dict": optimizer.state_dict(),
    }, final_path)
    print(f"Done. final ckpt: {final_path}")
    print(f"Total wall: {time.time() - t0:.0f}s")

    loop.run_until_complete(session.close())
    loop.close()


async def _make_session():
    return aiohttp.ClientSession()


if __name__ == "__main__":
    main()
