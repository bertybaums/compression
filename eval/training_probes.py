"""
Training-time probes for the Reasoner.

These run inside the training loop at eval_interval (or a multiple of it for
the slower sample-generation probe). They surface signals that catch failure
modes a held-out PPL number alone would miss:

  - <UNK> rate in generations: how often the model "wants" to say something
    OOV. Should be vanishingly rare since the data was curated for ≥98%
    UGF compliance and non-compliant records are filtered by the data
    loader. A spike means the model is reaching for concepts it can't
    render.

  - Vocabulary coverage entropy: Shannon entropy of the token distribution
    over a sample of generations. Low entropy = model has collapsed to a
    small subset of the vocabulary (a few stock phrases).

  - Sample generations themselves: written to disk for human inspection.

The "compliance rate" metric you'd expect here is structurally 100% — the
output head is sized to the UGF vocab so the model literally cannot emit a
non-UGF token. We don't track it.
"""

import json
import math
from collections import Counter
from pathlib import Path

import torch


def load_sample_prompts(path: str | Path) -> list[dict]:
    """Read fixed prompts from a JSONL file. Each line: {id, kind, prompt}."""
    path = Path(path)
    if not path.exists():
        return []
    prompts = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                prompts.append(json.loads(line))
    return prompts


@torch.no_grad()
def generate_samples(
    model,
    tokenizer,
    prompts: list[dict],
    max_new_tokens: int = 256,
    temperature: float = 0.8,
    top_k: int = 50,
    top_p: float = 0.9,
    device: torch.device | None = None,
) -> list[dict]:
    """Run model.generate on each prompt. Returns prompts annotated with 'completion' field."""
    device = device or next(model.parameters()).device
    eos_id = tokenizer.eos_token_id
    bos_id = tokenizer.bos_token_id
    out = []
    for p in prompts:
        text = p["prompt"]
        # Prepend BOS only; we do NOT want a trailing EOS in the prompt
        # since that's the model's stop signal during training.
        body = tokenizer.encode(text, add_special_tokens=False)
        ids = ([bos_id] if bos_id is not None else []) + body
        input_ids = torch.tensor([ids], dtype=torch.long, device=device)
        gen = model.generate(
            input_ids,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_k=top_k,
            top_p=top_p,
            eos_token_id=eos_id,
        )
        # Strip the prompt tokens from the output
        completion_ids = gen[0, input_ids.shape[1]:].tolist()
        completion_text = tokenizer.decode(completion_ids, skip_special_tokens=False)
        out.append({**p, "completion_ids": completion_ids, "completion_text": completion_text})
    return out


def compute_probe_metrics(samples: list[dict], tokenizer) -> dict[str, float]:
    """Compute UNK rate and vocabulary-coverage entropy across the sample set."""
    unk_id = tokenizer.unk_token_id
    special_ids = {
        tokenizer.pad_token_id, tokenizer.bos_token_id,
        tokenizer.eos_token_id, tokenizer.unk_token_id,
    }
    # Strip None (some specials may be unset)
    special_ids = {s for s in special_ids if s is not None}

    all_token_ids = []
    n_unk = 0
    n_total = 0
    for s in samples:
        for tid in s["completion_ids"]:
            if tid in special_ids:
                if tid == unk_id:
                    n_unk += 1
                    n_total += 1
                # don't count BOS/EOS/PAD in either numerator or denominator
                continue
            all_token_ids.append(tid)
            n_total += 1

    unk_rate = n_unk / n_total if n_total else 0.0

    # Shannon entropy over non-special tokens (in nats per token, normalized
    # by log(vocab_size) to get [0, 1] coverage score)
    if all_token_ids:
        counts = Counter(all_token_ids)
        total = sum(counts.values())
        h = 0.0
        for c in counts.values():
            p = c / total
            h -= p * math.log(p)
        # Normalize: max entropy is log(vocab_size) — but practical max is
        # log(distinct_tokens). We report raw entropy + a coverage ratio
        # vs. log(vocab_size).
        max_h = math.log(tokenizer.vocab_size)
        coverage = h / max_h if max_h > 0 else 0.0
        unique_tokens = len(counts)
    else:
        h = 0.0
        coverage = 0.0
        unique_tokens = 0

    return {
        "unk_rate": unk_rate,
        "entropy_nats": h,
        "coverage": coverage,           # h / log(vocab_size), in [0, 1]
        "unique_tokens": unique_tokens,
        "n_total_tokens": n_total,
    }


def write_samples_log(samples: list[dict], step: int, log_dir: str | Path) -> Path:
    """Write samples to a per-step text file for human inspection."""
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    out_path = log_dir / f"samples_step-{step:07d}.txt"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"Sample generations at step {step}\n")
        f.write("=" * 70 + "\n\n")
        for s in samples:
            f.write(f"[{s['id']}] kind={s.get('kind', '?')}\n")
            f.write(f"PROMPT: {s['prompt']}\n\n")
            f.write(f"COMPLETION: {s['completion_text']}\n")
            f.write("\n" + "-" * 70 + "\n\n")
    return out_path
