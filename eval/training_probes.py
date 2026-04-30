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

  - Zipf slope: log-rank vs. log-frequency OLS slope on the top-N tokens.
    Natural English is ~ -1. A much-shallower (closer to 0) slope = uniform
    use across vocabulary; a much-steeper slope = collapse to a few stock
    tokens. Tracking this over training surfaces emergent power-law
    structure (cf. Ramji et al. 2026, "Thinking Without Words", Figure 4 —
    they find Zipfian emerges over abstract vocab during RL).

  - Sample generations themselves: written to disk for human inspection.

  - Token rank-frequency table: written to disk per step, so we can plot the
    distribution evolution over training without re-running.

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


def _zipf_slope(sorted_counts: list[int], top_n: int = 200) -> float:
    """Fit log(rank) vs log(frequency) with simple OLS on the top-N tokens.

    Returns the slope. For natural English this is ~ -1 (Zipf's law).
    Closer to 0 = flatter / more uniform usage.
    More negative than -1 = sharper concentration on top tokens.
    Returns 0.0 if there's not enough data to fit (< 5 distinct tokens).
    """
    pos_counts = [c for c in sorted_counts if c > 0]
    n = min(len(pos_counts), top_n)
    if n < 5:
        return 0.0
    log_ranks = [math.log(r + 1) for r in range(n)]   # rank 1, 2, ..., n
    log_freqs = [math.log(c) for c in pos_counts[:n]]
    mean_x = sum(log_ranks) / n
    mean_y = sum(log_freqs) / n
    num = sum((log_ranks[i] - mean_x) * (log_freqs[i] - mean_y) for i in range(n))
    den = sum((log_ranks[i] - mean_x) ** 2 for i in range(n))
    if den == 0:
        return 0.0
    return num / den


def compute_probe_metrics(samples: list[dict], tokenizer) -> dict:
    """Compute UNK rate, vocabulary-coverage entropy, and Zipf slope.

    Returns a dict with scalar metrics plus a `rank_freq` list (top-100
    [token_id, count] entries) for offline plotting.
    """
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
        max_h = math.log(tokenizer.vocab_size)
        coverage = h / max_h if max_h > 0 else 0.0
        unique_tokens = len(counts)

        # Zipf rank-frequency: sort counts descending, fit log-rank vs log-freq
        sorted_counts = sorted(counts.values(), reverse=True)
        zipf_slope = _zipf_slope(sorted_counts, top_n=200)
        # Top-100 (token_id, count) for offline analysis. Convert to list of pairs.
        sorted_items = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:100]
        rank_freq = [[int(tid), int(c)] for tid, c in sorted_items]
    else:
        h = 0.0
        coverage = 0.0
        unique_tokens = 0
        zipf_slope = 0.0
        rank_freq = []

    return {
        "unk_rate": unk_rate,
        "entropy_nats": h,
        "coverage": coverage,           # h / log(vocab_size), in [0, 1]
        "unique_tokens": unique_tokens,
        "n_total_tokens": n_total,
        "zipf_slope": zipf_slope,       # ~ -1 for natural English
        "rank_freq": rank_freq,         # top-100 [token_id, count] for plotting
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


def write_rank_freq(metrics: dict, step: int, log_dir: str | Path, tokenizer) -> Path:
    """Append a per-step rank-frequency snapshot for offline plotting.

    Format: one JSON line per step in `rank_freq.jsonl`. Includes the top-100
    [token_str, count] pairs and summary metrics so a plotting script can
    pull the file and reconstruct the distribution evolution.
    """
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    out_path = log_dir / "rank_freq.jsonl"
    rf_with_strings = [
        [tokenizer.convert_ids_to_tokens(tid), c]
        for tid, c in metrics.get("rank_freq", [])
    ]
    record = {
        "step": step,
        "zipf_slope": metrics.get("zipf_slope", 0.0),
        "entropy_nats": metrics.get("entropy_nats", 0.0),
        "coverage": metrics.get("coverage", 0.0),
        "unique_tokens": metrics.get("unique_tokens", 0),
        "n_total_tokens": metrics.get("n_total_tokens", 0),
        "rank_freq": rf_with_strings,
    }
    with open(out_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return out_path
