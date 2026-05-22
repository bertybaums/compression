"""
Stage-1 preference trainer for the v2 Reasoner: DPO / APO-zero.

The Labonne "Stage 1" we skipped before GRPO (see docs/dpo-stage1-design-2026-05-22.md).
A contrastive objective is the right tool for the v3 failure mode: the scalar
GRPO reward was gameable (the policy drifted into a fluent off-topic attractor),
whereas DPO/APO train on explicit (chosen, rejected) pairs — and we put v3's
off-topic boilerplate on the *rejected* side.

Two losses, behind --variant:
  - dpo:      L = -log σ( β·(Δ_w - Δ_l) )                  [Rafailov 2023]
  - apo_zero: L = -log σ( β·Δ_w ) - log σ( -β·Δ_l )         [D'Oosterlinck 2024]
    where Δ(y) = logπ_θ(y|x) - logπ_ref(y|x).
  APO-zero pushes chosen up and rejected down *independently*, which (a) prevents
  DPO's "both log-probs drift down together" failure and (b) was strongest for
  out-of-domain post-training on SmolLM3 — and OOD prompt-attention is our deficit.

Reference + policy both initialise from the SFT-v2 checkpoint (NOT the v3 RL
checkpoint — that one reward-hacked).

Length-bias guard: DPO can degenerate into "prefer longer/shorter." We default
to SUM log-probs (standard DPO/APO with a reference; β≈0.3) and *monitor* the
chosen/rejected length gap + win-direction correlation. `length_normalize: true`
switches to per-token-mean log-probs (SimPO-style) — if you flip it on, raise β
substantially (the per-token differences are ~1/length smaller).

Usage:
    python -m reasoner.train_dpo --config configs/reasoner_dpo_v1.yaml \\
        --resume checkpoints/reasoner_sft_v2/final.pt
    python -m reasoner.train_dpo --self-test     # CPU sanity check, no checkpoint
"""

import argparse
import json
import sys
import time
from pathlib import Path

import torch
import torch.nn.functional as F
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from reasoner.model import Reasoner, ReasonerConfig
from tokenizer.ugf_tokenizer import UGFTokenizer

ANSWER_MARKER = "So my answer is:"


# ----------------------------- data -----------------------------

class PreferenceDataset(torch.utils.data.Dataset):
    """Reads preference pairs and tokenizes each side in the SFT-v2 format.

    Input JSONL line: {prompt, chosen, rejected, track, ...}. `chosen` and
    `rejected` are full UGF completions (reasoning + marker + answer), without
    special tokens. Each side is tokenized as:

        [BOS] + prompt_ids + " " + completion_ids + [EOS]

    with prompt_len = 1 + len(prompt_ids). Completions are tail-truncated to fit
    max_seq_len; pairs whose prompt alone overflows are dropped.
    """

    def __init__(self, path, tokenizer: UGFTokenizer, max_seq_len: int = 512):
        self.tok = tokenizer
        self.max_seq_len = max_seq_len
        self.pairs = []
        n_dropped = 0
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                ex = self._encode_pair(r)
                if ex is None:
                    n_dropped += 1
                    continue
                self.pairs.append(ex)
        if n_dropped:
            print(f"DPO data: dropped {n_dropped} unusable pairs ({path})")
        print(f"DPO data: loaded {len(self.pairs)} pairs ({path})")

    def _encode_one(self, prompt_ids, completion_text):
        bos, eos = self.tok.bos_token_id, self.tok.eos_token_id
        comp_ids = self.tok.encode(" " + completion_text.strip(), add_special_tokens=False)
        prompt_len = (1 if bos is not None else 0) + len(prompt_ids)
        # Budget: BOS + prompt + completion + EOS must fit.
        max_comp = self.max_seq_len - prompt_len - 1  # -1 for EOS
        if max_comp <= 0:
            return None
        comp_ids = comp_ids[:max_comp]
        full = ([bos] if bos is not None else []) + prompt_ids + comp_ids + [eos]
        return torch.tensor(full, dtype=torch.long), prompt_len

    def _encode_pair(self, r):
        prompt = (r.get("prompt") or r.get("english_query") or "").strip()
        chosen = (r.get("chosen") or "").strip()
        rejected = (r.get("rejected") or "").strip()
        if not prompt or not chosen or not rejected:
            return None
        prompt_ids = self.tok.encode(prompt, add_special_tokens=False)
        c = self._encode_one(prompt_ids, chosen)
        rej = self._encode_one(prompt_ids, rejected)
        if c is None or rej is None:
            return None
        return {
            "chosen_ids": c[0], "chosen_plen": c[1],
            "rejected_ids": rej[0], "rejected_plen": rej[1],
            "track": r.get("track", ""),
        }

    def __len__(self):
        return len(self.pairs)

    def __getitem__(self, i):
        return self.pairs[i]


# ----------------------------- log-probs + loss -----------------------------

def completion_logprob(model, full_ids: torch.Tensor, prompt_len: int,
                       length_normalize: bool, device) -> torch.Tensor:
    """Sum (or per-token mean) log-prob of the completion span. Keeps grad iff
    the model's params require grad and we're not under no_grad."""
    ids = full_ids.unsqueeze(0).to(device)
    logits = model(ids)["logits"][0]                       # [T, V]
    logp = F.log_softmax(logits.float(), dim=-1)
    targets = ids[0, 1:]                                   # [T-1]
    tok_logp = logp[:-1].gather(-1, targets.unsqueeze(-1)).squeeze(-1)  # [T-1]
    comp = tok_logp[prompt_len - 1:]                       # completion tokens only
    if comp.numel() == 0:
        return logits.new_zeros(())
    return comp.mean() if length_normalize else comp.sum()


def preference_loss(d_w: torch.Tensor, d_l: torch.Tensor, beta: float,
                    variant: str) -> torch.Tensor:
    if variant == "dpo":
        return -F.logsigmoid(beta * (d_w - d_l))
    if variant == "apo_zero":
        # Push chosen up (Δ_w > 0) and rejected down (Δ_l < 0), independently.
        return -F.logsigmoid(beta * d_w) - F.logsigmoid(-beta * d_l)
    raise ValueError(f"unknown variant {variant}")


# ----------------------------- training -----------------------------

def _build_model(config, device):
    return Reasoner(config).to(device)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str)
    parser.add_argument("--resume", type=str, help="SFT v2 checkpoint to init policy + ref from.")
    parser.add_argument("--self-test", action="store_true", help="CPU sanity check, no checkpoint.")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    with open(args.config) as f:
        cfg = yaml.safe_load(f)
    mcfg, tcfg, dcfg = cfg["model"], cfg["training"], cfg["data"]
    dpo = cfg["dpo"]

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    tokenizer = UGFTokenizer()
    config = ReasonerConfig(
        vocab_size=tokenizer.vocab_size,
        d_model=mcfg["d_model"], n_layers=mcfg["n_layers"], n_heads=mcfg["n_heads"],
        n_kv_heads=mcfg["n_kv_heads"], d_ff=mcfg["d_ff"], max_seq_len=mcfg["max_seq_len"],
        dropout=mcfg.get("dropout", 0.0), tie_embeddings=mcfg.get("tie_embeddings", True),
    )

    from reasoner.train import load_checkpoint
    print(f"Init policy + frozen ref from {args.resume}")
    policy = _build_model(config, device)
    load_checkpoint(args.resume, policy)
    ref = _build_model(config, device)
    load_checkpoint(args.resume, ref)
    ref.eval()
    for p in ref.parameters():
        p.requires_grad_(False)

    ds = PreferenceDataset(dcfg["pairs"], tokenizer, max_seq_len=mcfg["max_seq_len"])
    loader = torch.utils.data.DataLoader(ds, batch_size=1, shuffle=True, num_workers=0,
                                         collate_fn=lambda b: b[0])

    optimizer = torch.optim.AdamW(policy.parameters(), lr=tcfg["lr"],
                                  betas=(0.9, 0.95), weight_decay=tcfg.get("weight_decay", 0.0))

    variant = dpo.get("variant", "apo_zero")
    beta = dpo.get("beta", 0.3)
    length_norm = dpo.get("length_normalize", False)
    nll_coef = dpo.get("nll_anchor_coef", 0.0)
    grad_accum = tcfg.get("grad_accum", 8)
    epochs = tcfg.get("epochs", 1)

    log_dir = Path(tcfg["log_dir"]); log_dir.mkdir(parents=True, exist_ok=True)
    ckpt_dir = Path(tcfg["checkpoint_dir"]); ckpt_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = log_dir / "dpo_metrics.jsonl"

    print(f"variant={variant} beta={beta} length_norm={length_norm} nll_coef={nll_coef} "
          f"grad_accum={grad_accum} epochs={epochs} pairs={len(ds)}")

    step = 0
    optimizer.zero_grad()
    t0 = time.time()
    for epoch in range(epochs):
        for i, ex in enumerate(loader):
            # Policy log-probs (with grad).
            lp_w = completion_logprob(policy, ex["chosen_ids"], ex["chosen_plen"], length_norm, device)
            lp_l = completion_logprob(policy, ex["rejected_ids"], ex["rejected_plen"], length_norm, device)
            # Reference log-probs (frozen).
            with torch.no_grad():
                rp_w = completion_logprob(ref, ex["chosen_ids"], ex["chosen_plen"], length_norm, device)
                rp_l = completion_logprob(ref, ex["rejected_ids"], ex["rejected_plen"], length_norm, device)
            d_w = lp_w - rp_w
            d_l = lp_l - rp_l

            loss = preference_loss(d_w, d_l, beta, variant)
            if nll_coef > 0:
                # NLL-on-chosen stabiliser (per-token CE on the chosen completion).
                nll = -(lp_w if length_norm else lp_w / max(ex["chosen_ids"].numel() - ex["chosen_plen"], 1))
                loss = loss + nll_coef * nll

            (loss / grad_accum).backward()

            step += 1
            if step % grad_accum == 0:
                torch.nn.utils.clip_grad_norm_(policy.parameters(), 1.0)
                optimizer.step()
                optimizer.zero_grad()

            if step % dpo.get("log_every", 50) == 0:
                rec = {
                    "step": step, "epoch": epoch, "loss": float(loss.item()),
                    "d_w": float(d_w.item()), "d_l": float(d_l.item()),
                    "margin": float((d_w - d_l).item()),
                    "win": int(d_w.item() > d_l.item()),
                    "len_w": int(ex["chosen_ids"].numel() - ex["chosen_plen"]),
                    "len_l": int(ex["rejected_ids"].numel() - ex["rejected_plen"]),
                    "wall_s": round(time.time() - t0, 1),
                }
                with open(metrics_path, "a") as f:
                    f.write(json.dumps(rec) + "\n")
                print(f"step {step:5d} | loss {rec['loss']:.4f} | d_w {rec['d_w']:+.3f} "
                      f"d_l {rec['d_l']:+.3f} | margin {rec['margin']:+.3f} | "
                      f"len_w {rec['len_w']} len_l {rec['len_l']}", flush=True)

            if step % dpo.get("save_every", 500) == 0:
                _save(policy, config, step, ckpt_dir / f"step-{step:06d}.pt")

    # Flush any remaining grads.
    if step % grad_accum != 0:
        torch.nn.utils.clip_grad_norm_(policy.parameters(), 1.0)
        optimizer.step()
        optimizer.zero_grad()

    _save(policy, config, step, ckpt_dir / "final.pt")
    print(f"Done. {step} pairs in {time.time() - t0:.0f}s. final ckpt: {ckpt_dir / 'final.pt'}")


def _save(model, config, step, path):
    torch.save({"step": step, "model_state_dict": model.state_dict(),
                "config": config.__dict__}, path)
    print(f"  saved {path}", flush=True)


def self_test():
    """CPU sanity check: tiny random model, synthetic pairs, a few steps.
    Verifies tokenize → forward → completion-logprob → DPO/APO loss → backward."""
    print("=== train_dpo self-test (CPU, tiny random model) ===")
    tok = UGFTokenizer()
    config = ReasonerConfig(vocab_size=tok.vocab_size, d_model=64, n_layers=2,
                            n_heads=4, n_kv_heads=2, d_ff=128, max_seq_len=128)
    device = torch.device("cpu")
    policy = Reasoner(config).to(device)
    ref = Reasoner(config).to(device)
    ref.load_state_dict(policy.state_dict())
    for p in ref.parameters():
        p.requires_grad_(False)

    pairs = [
        {"prompt": "what makes a thing good", "track": "philosophy",
         "chosen": "We look at what the thing does for people and check each part with care. So my answer is: A thing is good when it helps people live well.",
         "rejected": "People care more about keeping what they have because losing feels worse than winning helps them. So my answer is: People do not like to lose."},
        {"prompt": "does the case follow", "track": "logic",
         "chosen": "If the first is true then the second is true. The first is true. So my answer is: The case follows.",
         "rejected": "We think about many things and people. So my answer is: The case does not follow."},
    ]
    tmp = Path("/tmp/_dpo_selftest_pairs.jsonl")
    tmp.write_text("\n".join(json.dumps(p) for p in pairs))
    ds = PreferenceDataset(tmp, tok, max_seq_len=128)
    assert len(ds) == 2, f"expected 2 pairs, got {len(ds)}"

    opt = torch.optim.AdamW(policy.parameters(), lr=1e-3)
    for variant in ("dpo", "apo_zero"):
        losses = []
        for it in range(6):
            ex = ds[it % len(ds)]
            lp_w = completion_logprob(policy, ex["chosen_ids"], ex["chosen_plen"], False, device)
            lp_l = completion_logprob(policy, ex["rejected_ids"], ex["rejected_plen"], False, device)
            with torch.no_grad():
                rp_w = completion_logprob(ref, ex["chosen_ids"], ex["chosen_plen"], False, device)
                rp_l = completion_logprob(ref, ex["rejected_ids"], ex["rejected_plen"], False, device)
            loss = preference_loss(lp_w - rp_w, lp_l - rp_l, beta=0.3, variant=variant)
            assert torch.isfinite(loss), f"{variant}: non-finite loss"
            opt.zero_grad(); loss.backward()
            gnorm = torch.nn.utils.clip_grad_norm_(policy.parameters(), 1.0)
            assert torch.isfinite(gnorm), f"{variant}: non-finite grad"
            opt.step()
            losses.append(float(loss.item()))
        print(f"  {variant}: losses {[round(l,3) for l in losses]}  "
              f"({'down' if losses[-1] < losses[0] else 'up'})")
    # Length-normalized path runs without error.
    _ = completion_logprob(policy, ds[0]["chosen_ids"], ds[0]["chosen_plen"], True, device)
    print("self-test OK: tokenize+forward+logprob+loss+backward all finite; both variants run.")


if __name__ == "__main__":
    main()
