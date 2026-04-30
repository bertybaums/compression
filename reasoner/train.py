"""
Training loop for the Reasoner model.

Features:
  - Mixed precision (bf16) training
  - Gradient checkpointing to save memory
  - Gradient accumulation for effective large batch sizes
  - Cosine learning rate schedule with linear warmup
  - Checkpointing (save best 3 by validation loss)
  - Logging to tensorboard (and optionally wandb)
  - Resume from checkpoint

Usage:
  python reasoner/train.py --config configs/reasoner.yaml
  python reasoner/train.py --config configs/reasoner.yaml --resume checkpoints/step-10000.pt
"""

import argparse
import json
import math
import os
import time
from pathlib import Path

import torch
import torch.nn.functional as F
import yaml

from reasoner.model import Reasoner, ReasonerConfig
from reasoner.data import UGFDataset, ParallelUGFDataset, collate_fn
from torch.utils.data import ConcatDataset, DataLoader
from tokenizer.ugf_tokenizer import UGFTokenizer
from eval.training_probes import (
    load_sample_prompts,
    generate_samples,
    compute_probe_metrics,
    write_samples_log,
    write_rank_freq,
)


def get_lr(step: int, warmup_steps: int, max_steps: int, max_lr: float, min_lr: float) -> float:
    """Cosine learning rate schedule with linear warmup."""
    if step < warmup_steps:
        return max_lr * (step + 1) / warmup_steps
    if step >= max_steps:
        return min_lr
    progress = (step - warmup_steps) / (max_steps - warmup_steps)
    return min_lr + 0.5 * (max_lr - min_lr) * (1 + math.cos(math.pi * progress))


def save_checkpoint(model, optimizer, step, loss, config, path):
    """Save a training checkpoint."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    torch.save({
        "step": step,
        "model_state_dict": model.state_dict(),
        "optimizer_state_dict": optimizer.state_dict(),
        "loss": loss,
        "config": vars(config) if hasattr(config, "__dict__") else config,
    }, path)


def load_checkpoint(path, model, optimizer=None):
    """Load a training checkpoint."""
    ckpt = torch.load(path, map_location="cpu", weights_only=False)
    model.load_state_dict(ckpt["model_state_dict"])
    if optimizer is not None and "optimizer_state_dict" in ckpt:
        optimizer.load_state_dict(ckpt["optimizer_state_dict"])
    return ckpt.get("step", 0), ckpt.get("loss", float("inf"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default="configs/reasoner.yaml")
    parser.add_argument("--resume", type=str, default=None, help="Path to checkpoint to resume from")
    args = parser.parse_args()

    # --- Load config ---
    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    model_cfg = cfg.get("model", {})
    train_cfg = cfg.get("training", {})
    data_cfg = cfg.get("data", {})

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    # --- Tokenizer ---
    tokenizer = UGFTokenizer()
    print(f"Tokenizer vocab size: {tokenizer.vocab_size}")

    # --- Model ---
    config = ReasonerConfig(
        vocab_size=tokenizer.vocab_size,
        d_model=model_cfg.get("d_model", 2048),
        n_layers=model_cfg.get("n_layers", 32),
        n_heads=model_cfg.get("n_heads", 32),
        n_kv_heads=model_cfg.get("n_kv_heads", 8),
        d_ff=model_cfg.get("d_ff", 5504),
        max_seq_len=model_cfg.get("max_seq_len", 512),
        dropout=model_cfg.get("dropout", 0.0),
        tie_embeddings=model_cfg.get("tie_embeddings", True),
    )

    model = Reasoner(config)
    counts = model.count_parameters()
    print(f"Model parameters: {counts['total']:,} ({counts['total']/1e9:.2f}B)")

    # Gradient checkpointing
    if train_cfg.get("gradient_checkpointing", True):
        for layer in model.layers:
            layer._gradient_checkpointing = True
            # Hook into forward to use checkpointing
        # We'll implement this via torch.utils.checkpoint in the forward pass
        # For now, enable it on the module level
        model.gradient_checkpointing_enable = True
        print("Gradient checkpointing: enabled")

    model = model.to(device)

    # --- Data ---
    train_paths = data_cfg.get("train_paths", [])                   # reasoning-trace format
    parallel_train_paths = data_cfg.get("parallel_train_paths", []) # parallel-corpus UGF-side format
    val_path = data_cfg.get("val_path", None)
    max_seq_len = model_cfg.get("max_seq_len", 512)
    batch_size = train_cfg.get("batch_size", 8)
    num_workers = data_cfg.get("num_workers", 4)

    if not train_paths and not parallel_train_paths:
        print("ERROR: No training data paths specified in config.")
        return

    heldout_ids_path = data_cfg.get("heldout_ids_path", None)
    dataset_type = data_cfg.get("dataset_type", "reasoning")
    per_source_val = data_cfg.get("per_source_val", False)
    # random_val_fraction supplements the doc-key heldout for sources where
    # the heldout JSON doesn't naturally include any matching IDs (notably the
    # main `reasoning-NNNNNNN` corpus, which has no source-passage parents).
    random_val_fraction = data_cfg.get("random_val_fraction", 0.0)

    def _make_dataset(path: str, ds_type: str, include_only_heldout: bool = False):
        if ds_type == "reasoning":
            return UGFDataset(path, tokenizer, max_seq_len=max_seq_len,
                              heldout_ids_path=heldout_ids_path,
                              include_only_heldout=include_only_heldout,
                              random_val_fraction=random_val_fraction)
        elif ds_type == "parallel":
            return ParallelUGFDataset(path, tokenizer, max_seq_len=max_seq_len,
                                      heldout_ids_path=heldout_ids_path,
                                      include_only_heldout=include_only_heldout,
                                      random_val_fraction=random_val_fraction)
        else:
            raise ValueError(f"Unknown dataset_type: {ds_type}")

    # Per-source label for logging — derive from the basename.
    def _source_label(path: str, ds_type: str) -> str:
        stem = Path(path).stem
        return f"{ds_type}/{stem}"

    train_datasets = []
    val_loaders: dict[str, DataLoader] = {}
    for path in train_paths:
        ds = _make_dataset(path, dataset_type)
        print(f"  {path} ({dataset_type}): {len(ds)} sequences")
        train_datasets.append(ds)
        if per_source_val:
            val_ds = _make_dataset(path, dataset_type, include_only_heldout=True)
            if len(val_ds) > 0:
                val_loaders[_source_label(path, dataset_type)] = DataLoader(
                    val_ds, batch_size=batch_size, shuffle=False,
                    num_workers=num_workers,
                    collate_fn=lambda batch: collate_fn(batch, pad_id=tokenizer.pad_token_id),
                    pin_memory=True, drop_last=False,
                )
                print(f"    val: {len(val_ds)} held-out sequences")
    for path in parallel_train_paths:
        ds = _make_dataset(path, "parallel")
        print(f"  {path} (parallel): {len(ds)} sequences")
        train_datasets.append(ds)
        if per_source_val:
            val_ds = _make_dataset(path, "parallel", include_only_heldout=True)
            if len(val_ds) > 0:
                val_loaders[_source_label(path, "parallel")] = DataLoader(
                    val_ds, batch_size=batch_size, shuffle=False,
                    num_workers=num_workers,
                    collate_fn=lambda batch: collate_fn(batch, pad_id=tokenizer.pad_token_id),
                    pin_memory=True, drop_last=False,
                )
                print(f"    val: {len(val_ds)} held-out sequences")

    combined_train = ConcatDataset(train_datasets) if len(train_datasets) > 1 else train_datasets[0]
    train_loader = DataLoader(
        combined_train,
        batch_size=batch_size,
        shuffle=True,
        num_workers=num_workers,
        collate_fn=lambda batch: collate_fn(batch, pad_id=tokenizer.pad_token_id),
        pin_memory=True,
        drop_last=True,
    )
    print(f"Training set: {len(combined_train)} sequences total across {len(train_datasets)} source(s)")
    print(f"Validation: {len(val_loaders)} per-source held-out loader(s)")

    # Legacy single val_path is still honored if present and per_source_val is off.
    if val_path and not per_source_val:
        val_ds = _make_dataset(val_path, dataset_type)
        val_loaders["legacy/val_path"] = DataLoader(
            val_ds, batch_size=batch_size, shuffle=False,
            num_workers=num_workers,
            collate_fn=lambda batch: collate_fn(batch, pad_id=tokenizer.pad_token_id),
            pin_memory=True, drop_last=False,
        )
        print(f"Validation set (legacy): {len(val_ds)} sequences")

    # Sample prompts for the generation probe.
    sample_prompts_path = data_cfg.get("sample_prompts_path")
    sample_prompts = load_sample_prompts(sample_prompts_path) if sample_prompts_path else []
    if sample_prompts:
        print(f"Sample probe: {len(sample_prompts)} prompts loaded from {sample_prompts_path}")

    # --- Optimizer ---
    max_lr = train_cfg.get("max_lr", 3e-4)
    min_lr = train_cfg.get("min_lr", 3e-5)
    weight_decay = train_cfg.get("weight_decay", 0.1)
    warmup_steps = train_cfg.get("warmup_steps", 2000)
    grad_accum_steps = train_cfg.get("grad_accum_steps", 8)
    max_steps = train_cfg.get("max_steps", 200000)
    log_interval = train_cfg.get("log_interval", 50)
    save_interval = train_cfg.get("save_interval", 5000)
    eval_interval = train_cfg.get("eval_interval", 1000)
    sample_probe_every_n_evals = train_cfg.get("sample_probe_every_n_evals", 5)
    sample_log_dir = train_cfg.get("sample_log_dir", "logs/reasoner/samples")
    max_checkpoints = train_cfg.get("max_checkpoints", 3)
    eval_count = 0  # how many eval rounds have run, for sample-probe gating

    # Separate weight decay groups (no decay for norms and embeddings)
    decay_params = []
    no_decay_params = []
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

    # --- Mixed precision ---
    use_amp = train_cfg.get("use_amp", True) and device.type == "cuda"
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)
    amp_dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    print(f"Mixed precision: {amp_dtype if use_amp else 'disabled'}")

    # --- Resume ---
    start_step = 0
    if args.resume:
        print(f"Resuming from {args.resume}")
        start_step, _ = load_checkpoint(args.resume, model, optimizer)
        print(f"Resumed at step {start_step}")

    # --- Tensorboard ---
    log_dir = train_cfg.get("log_dir", "logs/reasoner")
    try:
        from torch.utils.tensorboard import SummaryWriter
        writer = SummaryWriter(log_dir)
        print(f"Tensorboard logging to {log_dir}")
    except ImportError:
        writer = None
        print("Tensorboard not available, skipping logging")

    # --- Training loop ---
    checkpoint_dir = Path(train_cfg.get("checkpoint_dir", "checkpoints/reasoner"))
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    saved_checkpoints = []  # track for max_checkpoints pruning

    model.train()
    optimizer.zero_grad()

    step = start_step
    total_tokens = 0
    running_loss = 0.0
    t0 = time.time()

    data_iter = iter(train_loader)

    while step < max_steps:
        # Get next batch (cycle through data = multi-epoch)
        try:
            batch = next(data_iter)
        except StopIteration:
            data_iter = iter(train_loader)
            batch = next(data_iter)

        input_ids = batch["input_ids"].to(device)
        labels = batch["labels"].to(device)
        attention_mask = batch["attention_mask"].to(device)

        # Count tokens (excluding padding)
        n_tokens = attention_mask.sum().item()

        with torch.amp.autocast("cuda", dtype=amp_dtype, enabled=use_amp):
            result = model(input_ids, labels=labels, attention_mask=attention_mask)
            loss = result["loss"] / grad_accum_steps

        scaler.scale(loss).backward()
        running_loss += loss.item()
        total_tokens += n_tokens

        # Gradient accumulation step
        if (step + 1) % grad_accum_steps == 0 or step == max_steps - 1:
            # Gradient clipping
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)

            # Update learning rate
            lr = get_lr(step // grad_accum_steps, warmup_steps, max_steps // grad_accum_steps, max_lr, min_lr)
            for param_group in optimizer.param_groups:
                param_group["lr"] = lr

            scaler.step(optimizer)
            scaler.update()
            optimizer.zero_grad()

        step += 1

        # Logging
        if step % log_interval == 0:
            elapsed = time.time() - t0
            avg_loss = running_loss / log_interval * grad_accum_steps
            tokens_per_sec = total_tokens / elapsed
            lr = optimizer.param_groups[0]["lr"]
            print(
                f"step {step:>7d} | loss {avg_loss:.4f} | lr {lr:.2e} | "
                f"{tokens_per_sec:.0f} tok/s | {elapsed:.0f}s"
            )
            if writer:
                writer.add_scalar("train/loss", avg_loss, step)
                writer.add_scalar("train/lr", lr, step)
                writer.add_scalar("train/tokens_per_sec", tokens_per_sec, step)
            running_loss = 0.0
            total_tokens = 0
            t0 = time.time()

        # Per-source held-out validation
        if val_loaders and step % eval_interval == 0:
            model.eval()
            agg_loss = 0.0
            agg_weight = 0
            for label, vl in val_loaders.items():
                vl_loss = 0.0
                vl_batches = 0
                with torch.no_grad():
                    for val_batch in vl:
                        v_input = val_batch["input_ids"].to(device)
                        v_labels = val_batch["labels"].to(device)
                        v_mask = val_batch["attention_mask"].to(device)
                        with torch.amp.autocast("cuda", dtype=amp_dtype, enabled=use_amp):
                            v_result = model(v_input, labels=v_labels, attention_mask=v_mask)
                        vl_loss += v_result["loss"].item()
                        vl_batches += 1
                        if vl_batches >= 100:  # cap per-source eval at 100 batches
                            break
                if vl_batches:
                    vl_loss /= vl_batches
                    ppl = math.exp(min(vl_loss, 30))  # cap to avoid overflow
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

            # Sample-generation probe (slower; runs every N eval rounds)
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

        # Checkpointing
        if step % save_interval == 0:
            ckpt_path = checkpoint_dir / f"step-{step:07d}.pt"
            save_checkpoint(model, optimizer, step, running_loss, config, ckpt_path)
            saved_checkpoints.append(ckpt_path)
            print(f"  Saved checkpoint: {ckpt_path}")

            # Prune old checkpoints
            while len(saved_checkpoints) > max_checkpoints:
                old = saved_checkpoints.pop(0)
                old.unlink(missing_ok=True)

    # Final checkpoint
    final_path = checkpoint_dir / "final.pt"
    save_checkpoint(model, optimizer, step, running_loss, config, final_path)
    print(f"Training complete. Final checkpoint: {final_path}")

    if writer:
        writer.close()


if __name__ == "__main__":
    main()
