"""
Rollout buffer for GRPO training of the v2 Reasoner.

Generates N rollouts per prompt, capturing per-token log-probabilities under
the current policy (for the importance ratio in GRPO loss). Also computes
reference-policy log-probabilities (frozen SFT v2 checkpoint) for the KL
penalty.

Sampling matches the bench-generation defaults: temperature 0.8, top-p 0.9,
top-k 50, plus the anti-repetition decode controls (repetition_penalty 1.2,
no_repeat_ngram_size 4) we found necessary to suppress Labonne-style
doom-loops in v2 outputs.
"""

from dataclasses import dataclass

import torch
import torch.nn.functional as F


@dataclass
class Rollout:
    """One generated rollout, with everything the GRPO loss needs."""
    prompt_text: str                # original english prompt
    prompt_ids: torch.Tensor        # [Tp] long
    completion_ids: torch.Tensor    # [Tc] long
    completion_text: str            # decoded completion (used for reward + logging)
    old_logprobs: torch.Tensor      # [Tc] float — logprob under generation policy
    ref_logprobs: torch.Tensor      # [Tc] float — logprob under frozen ref policy
    # Reward and advantage fill in after the judge returns; left None initially.
    reward: float | None = None
    advantage: float | None = None
    reason: str | None = None


@torch.no_grad()
def _generate_with_logprobs(
    model,
    tokenizer,
    prompt_str: str,
    max_new_tokens: int,
    temperature: float,
    top_k: int,
    top_p: float,
    repetition_penalty: float,
    no_repeat_ngram_size: int,
    device: torch.device,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Manual autoregressive sampling that captures per-token logprobs.

    Mirrors Reasoner.generate() (with the same anti-repetition controls) but
    additionally accumulates the log-probability of the sampled token at each
    step. Returns (full_sequence_ids, completion_logprobs) where logprobs has
    shape [Tc].
    """
    model.eval()
    bos = tokenizer.bos_token_id
    eos = tokenizer.eos_token_id
    body = tokenizer.encode(prompt_str, add_special_tokens=False)
    ids_list = ([bos] if bos is not None else []) + body
    prompt_len = len(ids_list)
    input_ids = torch.tensor([ids_list], dtype=torch.long, device=device)

    completion_logprobs = []

    for _ in range(max_new_tokens):
        idx_cond = (
            input_ids
            if input_ids.shape[1] <= model.config.max_seq_len
            else input_ids[:, -model.config.max_seq_len:]
        )
        result = model(idx_cond)
        logits = result["logits"][:, -1, :]

        # Anti-repetition: token-level penalty.
        if repetition_penalty != 1.0:
            seen = set(input_ids[0].tolist())
            for tok in seen:
                if logits[0, tok] > 0:
                    logits[0, tok] = logits[0, tok] / repetition_penalty
                else:
                    logits[0, tok] = logits[0, tok] * repetition_penalty

        # Anti-repetition: forbid n-gram.
        if no_repeat_ngram_size > 0 and input_ids.shape[1] >= no_repeat_ngram_size - 1:
            seq = input_ids[0].tolist()
            n = no_repeat_ngram_size
            prefix = tuple(seq[-(n - 1):]) if n > 1 else ()
            if n > 1:
                forbidden = set()
                for i in range(len(seq) - n + 1):
                    if tuple(seq[i : i + n - 1]) == prefix:
                        forbidden.add(seq[i + n - 1])
                for tok in forbidden:
                    logits[0, tok] = float("-inf")

        if temperature > 0:
            logits_t = logits / temperature
        else:
            logits_t = logits

        # Top-k / top-p filtering.
        if top_k > 0:
            v, _ = torch.topk(logits_t, min(top_k, logits_t.size(-1)))
            logits_t = logits_t.masked_fill(logits_t < v[:, [-1]], float("-inf"))
        if top_p < 1.0:
            sorted_logits, sorted_indices = torch.sort(logits_t, descending=True)
            cum = torch.cumsum(F.softmax(sorted_logits, dim=-1), dim=-1)
            mask = cum > top_p
            mask[:, 1:] = mask[:, :-1].clone()
            mask[:, 0] = False
            to_remove = mask.scatter(1, sorted_indices, mask)
            logits_t = logits_t.masked_fill(to_remove, float("-inf"))

        probs = F.softmax(logits_t, dim=-1)
        next_tok = torch.multinomial(probs, num_samples=1)
        # Capture logprob of the SAMPLED token under the FILTERED, TEMP-SCALED dist.
        # NOTE: for GRPO we usually want logprob under the *original* policy
        # (unfiltered, temp=1.0). We'll re-compute these under the training-time
        # policy in the trainer. Here we save the raw logits-derived logprob of
        # the sampled token for diagnostic purposes only.
        log_probs = F.log_softmax(probs.clamp_min(1e-12).log(), dim=-1)  # = log(probs)
        token_logp = log_probs.gather(-1, next_tok).squeeze(-1)
        completion_logprobs.append(token_logp[0].item())

        input_ids = torch.cat([input_ids, next_tok], dim=1)
        if eos is not None and (next_tok == eos).all():
            break

    full_ids = input_ids[0]
    completion_ids = full_ids[prompt_len:]
    completion_logprobs_t = torch.tensor(
        completion_logprobs[: completion_ids.shape[0]], dtype=torch.float32
    )
    return full_ids, completion_logprobs_t


@torch.no_grad()
def _compute_logprobs(model, full_ids: torch.Tensor, prompt_len: int, device: torch.device) -> torch.Tensor:
    """Re-forward a sequence and return per-token logprob of completion tokens.

    full_ids: [T] (BOS + prompt + completion + maybe EOS)
    prompt_len: number of tokens that are prompt (BOS + prompt body)
    Returns: [Tc] float — logprob of completion[i] given everything before it.
    """
    model.eval()
    ids = full_ids.unsqueeze(0).to(device)
    if ids.shape[1] > model.config.max_seq_len:
        # Truncate from the left; preserve the suffix.
        ids = ids[:, -model.config.max_seq_len:]
        prompt_len = max(0, prompt_len - (full_ids.shape[0] - ids.shape[1]))

    out = model(ids)
    logits = out["logits"][0]                # [T, V]
    log_probs = F.log_softmax(logits, dim=-1)
    # Logprob of token i (in the sequence) is at position i-1 of log_probs.
    targets = ids[0, 1:]                     # [T-1]
    target_logps = log_probs[:-1].gather(-1, targets.unsqueeze(-1)).squeeze(-1)  # [T-1]
    # Completion span: indices prompt_len..T-1 in the original sequence
    # → in target_logps these are indices prompt_len-1..T-2 (since target[i] = ids[i+1]).
    completion_logps = target_logps[prompt_len - 1 :]
    return completion_logps.cpu()


def collect_rollouts(
    model,
    ref_model,
    tokenizer,
    prompts: list[str],
    n_per_prompt: int = 8,
    max_new_tokens: int = 400,
    temperature: float = 0.8,
    top_k: int = 50,
    top_p: float = 0.9,
    repetition_penalty: float = 1.2,
    no_repeat_ngram_size: int = 4,
    device: torch.device = torch.device("cuda"),
) -> list[list[Rollout]]:
    """Return a list of lists: outer = prompt index, inner = rollouts per prompt.

    Both the current policy `model` and the frozen reference `ref_model`
    contribute logprobs. The model used for sampling is `model` — these are
    the "old" logprobs for PPO/GRPO importance ratios.
    """
    all_rollouts: list[list[Rollout]] = []
    for prompt in prompts:
        group: list[Rollout] = []
        for _ in range(n_per_prompt):
            full_ids, gen_logps = _generate_with_logprobs(
                model, tokenizer, prompt,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_k=top_k, top_p=top_p,
                repetition_penalty=repetition_penalty,
                no_repeat_ngram_size=no_repeat_ngram_size,
                device=device,
            )
            prompt_body = tokenizer.encode(prompt, add_special_tokens=False)
            prompt_len = (1 if tokenizer.bos_token_id is not None else 0) + len(prompt_body)
            completion_ids = full_ids[prompt_len:]
            completion_text = tokenizer.decode(
                completion_ids.tolist(), skip_special_tokens=False
            )
            # Re-forward through SAMPLING policy to get clean logprobs at temp=1
            # (the gen_logps above are temp-scaled and post-filter; we want
            # un-modified logprobs for the importance ratio).
            old_logps = _compute_logprobs(model, full_ids, prompt_len, device)
            ref_logps = _compute_logprobs(ref_model, full_ids, prompt_len, device)
            group.append(Rollout(
                prompt_text=prompt,
                prompt_ids=full_ids[:prompt_len].cpu(),
                completion_ids=completion_ids.cpu(),
                completion_text=completion_text,
                old_logprobs=old_logps,
                ref_logprobs=ref_logps,
            ))
        all_rollouts.append(group)
    return all_rollouts


def compute_group_advantages(rewards: list[float], eps: float = 1e-6) -> list[float]:
    """Group-relative advantage normalization (the GR in GRPO).

    advantage_i = (r_i - mean(r_group)) / (std(r_group) + eps)
    """
    if not rewards:
        return []
    import statistics
    mean = statistics.mean(rewards)
    if len(rewards) >= 2:
        std = statistics.stdev(rewards)
    else:
        std = 0.0
    return [(r - mean) / (std + eps) for r in rewards]
