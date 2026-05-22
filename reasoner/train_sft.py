"""
SFT training loop for the Reasoner model (Phase 2).

Differs from reasoner/train.py only in the data path: SFT uses
UGFSFTDataset/sft_collate_fn (prompt-masked labels) instead of
UGFDataset/collate_fn (next-token over flat traces). The model, optimizer,
training loop, and probe machinery are identical.

This is kept as a separate file (rather than dispatching inside train.py) so
SFT-specific code is visually distinguishable from pretrain code at the
file level. Helper functions (get_lr, save_checkpoint, load_checkpoint) are
imported from train.py to avoid duplication.

Usage:
  python -m reasoner.train_sft --config configs/reasoner_sft.yaml \\
      --resume checkpoints/reasoner_pretrain_v1/final.pt
"""

import argparse
import math
import time
from pathlib import Path

import torch
import yaml
from torch.utils.data import ConcatDataset, DataLoader

from reasoner.model import Reasoner, ReasonerConfig
from reasoner.data_sft import UGFSFTDataset, sft_collate_fn
from reasoner.data_sft_v2 import UGFSFTv2Dataset, sft_v2_collate_fn
from reasoner.train import get_lr, save_checkpoint, load_checkpoint
from tokenizer.ugf_tokenizer import UGFTokenizer
from eval.training_probes import (
    load_sample_prompts,
    generate_samples,
    compute_probe_metrics,
    write_samples_log,
    write_rank_freq,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default="configs/reasoner_sft.yaml")
    parser.add_argument("--resume", type=str, required=True,
                        help="Pretrain checkpoint to initialize from (required for SFT)")
    args = parser.parse_args()

    # --- Load config ---
    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    model_cfg = cfg.get("model", {})
    train_cfg = cfg.get("training", {})
    data_cfg = cfg.get("data", {})

    dataset_type = data_cfg.get("dataset_type")
    if dataset_type not in ("sft", "sft_v2"):
        raise ValueError(
            f"reasoner.train_sft expects dataset_type: sft or sft_v2 in config, "
            f"got {dataset_type!r}. Use reasoner.train for pretraining."
        )
    is_v2 = (dataset_type == "sft_v2")
    if is_v2:
        dataset_cls = UGFSFTv2Dataset
        _collate = sft_v2_collate_fn
        print("SFT v2 (purist think-answer with 'So my answer is:' marker)")
    else:
        dataset_cls = UGFSFTDataset
        _collate = sft_collate_fn
        print("SFT v1 (5-template format anchoring)")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    # --- Tokenizer ---
    tokenizer = UGFTokenizer()
    print(f"Tokenizer vocab size: {tokenizer.vocab_size}")

    # --- Model ---
    config = ReasonerConfig(
        vocab_size=tokenizer.vocab_size,
        d_model=model_cfg.get("d_model", 1024),
        n_layers=model_cfg.get("n_layers", 16),
        n_heads=model_cfg.get("n_heads", 16),
        n_kv_heads=model_cfg.get("n_kv_heads", 4),
        d_ff=model_cfg.get("d_ff", 3072),
        max_seq_len=model_cfg.get("max_seq_len", 512),
        dropout=model_cfg.get("dropout", 0.0),
        tie_embeddings=model_cfg.get("tie_embeddings", True),
    )

    model = Reasoner(config)
    counts = model.count_parameters()
    print(f"Model parameters: {counts['total']:,} ({counts['total']/1e6:.1f}M)")

    if train_cfg.get("gradient_checkpointing", True):
        for layer in model.layers:
            layer._gradient_checkpointing = True
        model.gradient_checkpointing_enable = True
        print("Gradient checkpointing: enabled")

    model = model.to(device)

    # --- Data (SFT only — parallel corpus is excluded) ---
    train_paths = data_cfg.get("train_paths", [])
    max_seq_len = model_cfg.get("max_seq_len", 512)
    batch_size = train_cfg.get("batch_size", 8)
    num_workers = data_cfg.get("num_workers", 4)

    if not train_paths:
        print("ERROR: No SFT training data paths in config.")
        return

    heldout_ids_path = data_cfg.get("heldout_ids_path", None)
    per_source_val = data_cfg.get("per_source_val", False)
    random_val_fraction = data_cfg.get("random_val_fraction", 0.0)

    def _make_sft_dataset(path: str, include_only_heldout: bool = False):
        return dataset_cls(
            path, tokenizer, max_seq_len=max_seq_len,
            heldout_ids_path=heldout_ids_path,
            include_only_heldout=include_only_heldout,
            random_val_fraction=random_val_fraction,
        )

    def _source_label(path: str) -> str:
        prefix = "sft_v2" if is_v2 else "sft"
        return f"{prefix}/{Path(path).stem}"

    train_datasets = []
    val_loaders: dict[str, DataLoader] = {}
    for path in train_paths:
        ds = _make_sft_dataset(path)
        print(f"  {path} (sft): {len(ds)} (prompt, response) pairs")
        train_datasets.append(ds)
        if per_source_val:
            val_ds = _make_sft_dataset(path, include_only_heldout=True)
            if len(val_ds) > 0:
                val_loaders[_source_label(path)] = DataLoader(
                    val_ds, batch_size=batch_size, shuffle=False,
                    num_workers=num_workers,
                    collate_fn=lambda batch: _collate(batch, pad_id=tokenizer.pad_token_id),
                    pin_memory=True, drop_last=False,
                )
                print(f"    val: {len(val_ds)} held-out pairs")

    combined_train = ConcatDataset(train_datasets) if len(train_datasets) > 1 else train_datasets[0]
    train_loader = DataLoader(
        combined_train,
        batch_size=batch_size,
        shuffle=True,
        num_workers=num_workers,
        collate_fn=lambda batch: sft_collate_fn(batch, pad_id=tokenizer.pad_token_id),
        pin_memory=True,
        drop_last=True,
    )
    print(f"SFT training set: {len(combined_train)} pairs across {len(train_datasets)} source(s)")
    print(f"Validation: {len(val_loaders)} per-source held-out loader(s)")

    sample_prompts_path = data_cfg.get("sample_prompts_path")
    sample_prompts = load_sample_prompts(sample_prompts_path) if sample_prompts_path else []
    if sample_prompts:
        print(f"Sample probe: {len(sample_prompts)} prompts loaded from {sample_prompts_path}")

    # --- Optimizer ---
    max_lr = train_cfg.get("max_lr", 5e-5)
    min_lr = train_cfg.get("min_lr", 5e-6)
    weight_decay = train_cfg.get("weight_decay", 0.05)
    warmup_steps = train_cfg.get("warmup_steps", 500)
    grad_accum_steps = train_cfg.get("grad_accum_steps", 8)
    max_steps = train_cfg.get("max_steps", 30000)
    log_interval = train_cfg.get("log_interval", 50)
    save_interval = train_cfg.get("save_interval", 2000)
    eval_interval = train_cfg.get("eval_interval", 500)
    sample_probe_every_n_evals = train_cfg.get("sample_probe_every_n_evals", 4)
    sample_log_dir = train_cfg.get("sample_log_dir", "logs/reasoner_sft/samples")
    max_checkpoints = train_cfg.get("max_checkpoints", 3)
    eval_count = 0

    decay_params, no_decay_params = [], []
    for name, param in model.named_parameters():
        if not param.requires_grad:
            continue
        if "norm" in name or "tok_emb" in name:
            no_decay_params.append(param)
        else:
            decay_params.append(param)

    optimizer = torch.optim.AdamW([
        {"params": decay_params, "weight_decay": weight_decay},
        {"params": no_decay_params, "weight_decay": 0.0},
    ], lr=max_lr, betas=(0.9, 0.95))

    use_amp = train_cfg.get("use_amp", True) and device.type == "cuda"
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)
    amp_dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    print(f"Mixed precision: {amp_dtype if use_amp else 'disabled'}")

    # --- Resume from pretrain checkpoint (mandatory for SFT) ---
    print(f"Initializing SFT from pretrain checkpoint: {args.resume}")
    pretrain_step, pretrain_loss = load_checkpoint(args.resume, model)
    print(f"  pretrain step={pretrain_step}, loss={pretrain_loss:.4f}")
    # SFT counts steps from 0 — we don't continue the pretrain step counter.
    start_step = 0

    # --- Tensorboard ---
    log_dir = train_cfg.get("log_dir", "logs/reasoner_sft")
    try:
        from torch.utils.tensorboard import SummaryWriter
        writer = SummaryWriter(log_dir)
        print(f"Tensorboard logging to {log_dir}")
    except ImportError:
        writer = None
        print("Tensorboard not available, skipping logging")

    checkpoint_dir = Path(train_cfg.get("checkpoint_dir", "checkpoints/reasoner_sft_v1"))
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    saved_checkpoints = []

    model.train()
    optimizer.zero_grad()

    step = start_step
    total_tokens = 0
    running_loss = 0.0
    t0 = time.time()

    data_iter = iter(train_loader)

    while step < max_steps:
        try:
            batch = next(data_iter)
        except StopIteration:
            data_iter = iter(train_loader)
            batch = next(data_iter)

        input_ids = batch["input_ids"].to(device)
        labels = batch["labels"].to(device)
        attention_mask = batch["attention_mask"].to(device)

        # Count loss-eligible tokens (non-pad AND non-prompt — i.e., labels != -100)
        n_tokens = (labels != -100).sum().item()

        with torch.amp.autocast("cuda", dtype=amp_dtype, enabled=use_amp):
            result = model(input_ids, labels=labels, attention_mask=attention_mask)
            loss = result["loss"] / grad_accum_steps

        scaler.scale(loss).backward()
        running_loss += loss.item()
        total_tokens += n_tokens

        if (step + 1) % grad_accum_steps == 0 or step == max_steps - 1:
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            lr = get_lr(step // grad_accum_steps, warmup_steps, max_steps // grad_accum_steps, max_lr, min_lr)
            for param_group in optimizer.param_groups:
                param_group["lr"] = lr
            scaler.step(optimizer)
            scaler.update()
            optimizer.zero_grad()

        step += 1

        if step % log_interval == 0:
            elapsed = time.time() - t0
            avg_loss = running_loss / log_interval * grad_accum_steps
            tokens_per_sec = total_tokens / elapsed
            lr = optimizer.param_groups[0]["lr"]
            print(
                f"step {step:>7d} | sft_loss {avg_loss:.4f} | lr {lr:.2e} | "
                f"{tokens_per_sec:.0f} tok/s | {elapsed:.0f}s"
            )
            if writer:
                writer.add_scalar("train/sft_loss", avg_loss, step)
                writer.add_scalar("train/lr", lr, step)
                writer.add_scalar("train/tokens_per_sec", tokens_per_sec, step)
            running_loss = 0.0
            total_tokens = 0
            t0 = time.time()

        if val_loaders and step % eval_interval == 0:
            model.eval()
            agg_loss, agg_weight = 0.0, 0
            for label, vl in val_loaders.items():
                vl_loss, vl_batches = 0.0, 0
                with torch.no_grad():
                    for val_batch in vl:
                        v_input = val_batch["input_ids"].to(device)
                        v_labels = val_batch["labels"].to(device)
                        v_mask = val_batch["attention_mask"].to(device)
                        with torch.amp.autocast("cuda", dtype=amp_dtype, enabled=use_amp):
                            v_result = model(v_input, labels=v_labels, attention_mask=v_mask)
                        vl_loss += v_result["loss"].item()
                        vl_batches += 1
                        if vl_batches >= 100:
                            break
                if vl_batches:
                    vl_loss /= vl_batches
                    ppl = math.exp(min(vl_loss, 30))
                    print(f"  val[{label}]: loss={vl_loss:.4f} ppl={ppl:.2f} ({vl_batches} batches)")
                    if writer:
                        writer.add_scalar(f"val/loss/{label}", vl_loss, step)
                        writer.add_scalar(f"val/ppl/{label}", ppl, step)
                    agg_loss += vl_loss * vl_batches
                    agg_weight += vl_batches
            if agg_weight:
                overall = agg_loss / agg_weight
                print(f"  val[overall]: loss={overall:.4f} ppl={math.exp(min(overall, 30)):.2f}")
                if writer:
                    writer.add_scalar("val/loss/overall", overall, step)
                    writer.add_scalar("val/ppl/overall", math.exp(min(overall, 30)), step)
            eval_count += 1

            if sample_prompts and (eval_count % sample_probe_every_n_evals == 0):
                samples = generate_samples(
                    model, tokenizer, sample_prompts,
                    max_new_tokens=256, temperature=0.8, top_k=50, top_p=0.9,
                    device=device,
                )
                metrics = compute_probe_metrics(samples, tokenizer)
                out_path = write_samples_log(samples, step, sample_log_dir)
                rf_path = write_rank_freq(metrics, step, sample_log_dir, tokenizer)
                print(
                    f"  probe[step={step}]: unk_rate={metrics['unk_rate']:.4f} "
                    f"unique={metrics['unique_tokens']} "
                    f"coverage={metrics['coverage']:.3f} "
                    f"zipf_slope={metrics['zipf_slope']:.3f} "
                    f"-> {out_path}"
                )
                if writer:
                    writer.add_scalar("probe/unk_rate", metrics["unk_rate"], step)
                    writer.add_scalar("probe/unique_tokens", metrics["unique_tokens"], step)
                    writer.add_scalar("probe/coverage", metrics["coverage"], step)
                    writer.add_scalar("probe/zipf_slope", metrics["zipf_slope"], step)

            model.train()

        if step % save_interval == 0:
            ckpt_path = checkpoint_dir / f"step-{step:07d}.pt"
            save_checkpoint(model, optimizer, step, running_loss, config, ckpt_path)
            saved_checkpoints.append(ckpt_path)
            print(f"  Saved SFT checkpoint: {ckpt_path}")
            while len(saved_checkpoints) > max_checkpoints:
                old = saved_checkpoints.pop(0)
                old.unlink(missing_ok=True)

    final_path = checkpoint_dir / "final.pt"
    save_checkpoint(model, optimizer, step, running_loss, config, final_path)
    print(f"SFT complete. Final checkpoint: {final_path}")

    if writer:
        writer.close()


if __name__ == "__main__":
    main()
