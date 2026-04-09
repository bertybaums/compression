"""
Fine-tune T5-small as a bidirectional English <-> UGF translator.

Reads the parallel corpus (English, UGF pairs) and trains in both directions:
  - "translate to simple: {English}" -> UGF
  - "translate to full: {UGF}" -> English

Usage:
  python translator/train.py --config configs/translator.yaml
"""

import argparse
import json
import random
from pathlib import Path

import torch
import yaml
from torch.utils.data import Dataset, DataLoader
from transformers import (
    T5ForConditionalGeneration,
    T5Tokenizer,
    get_cosine_schedule_with_warmup,
)


class ParallelCorpusDataset(Dataset):
    """Dataset of (English, UGF) pairs for translator training.

    Creates both translation directions from each pair.
    """

    def __init__(
        self,
        data_path: str | Path,
        tokenizer: T5Tokenizer,
        max_source_len: int = 256,
        max_target_len: int = 384,
        filter_compliant: bool = True,
    ):
        self.tokenizer = tokenizer
        self.max_source_len = max_source_len
        self.max_target_len = max_target_len
        self.examples = []

        with open(data_path) as f:
            for line in f:
                record = json.loads(line)
                if filter_compliant and not record.get("compliant", True):
                    continue
                english = record.get("english", "").strip()
                ugf = record.get("ugf", "").strip()
                if english and ugf:
                    # Both directions
                    self.examples.append({
                        "source": f"translate to simple: {english}",
                        "target": ugf,
                    })
                    self.examples.append({
                        "source": f"translate to full: {ugf}",
                        "target": english,
                    })

        random.shuffle(self.examples)
        print(f"Loaded {len(self.examples)} training examples ({len(self.examples)//2} pairs, both directions)")

    def __len__(self):
        return len(self.examples)

    def __getitem__(self, idx):
        ex = self.examples[idx]

        source = self.tokenizer(
            ex["source"],
            max_length=self.max_source_len,
            truncation=True,
            padding="max_length",
            return_tensors="pt",
        )
        target = self.tokenizer(
            ex["target"],
            max_length=self.max_target_len,
            truncation=True,
            padding="max_length",
            return_tensors="pt",
        )

        # Replace padding token id with -100 for loss computation
        labels = target["input_ids"].squeeze()
        labels[labels == self.tokenizer.pad_token_id] = -100

        return {
            "input_ids": source["input_ids"].squeeze(),
            "attention_mask": source["attention_mask"].squeeze(),
            "labels": labels,
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default="configs/translator.yaml")
    args = parser.parse_args()

    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    # --- Model ---
    model_name = cfg.get("model", {}).get("base_model", "google/flan-t5-small")
    tokenizer = T5Tokenizer.from_pretrained(model_name)
    model = T5ForConditionalGeneration.from_pretrained(model_name)
    model = model.to(device)
    print(f"Model: {model_name} ({sum(p.numel() for p in model.parameters())/1e6:.1f}M params)")

    # --- Data ---
    data_cfg = cfg.get("data", {})
    train_path = data_cfg.get("train_path", "corpus/processed/parallel_corpus.jsonl")
    max_source_len = data_cfg.get("max_source_len", 256)
    max_target_len = data_cfg.get("max_target_len", 384)

    dataset = ParallelCorpusDataset(
        train_path, tokenizer, max_source_len, max_target_len
    )

    # Split: 95% train, 5% val
    val_size = max(100, int(0.05 * len(dataset)))
    train_size = len(dataset) - val_size
    train_dataset, val_dataset = torch.utils.data.random_split(dataset, [train_size, val_size])

    train_cfg = cfg.get("training", {})
    batch_size = train_cfg.get("batch_size", 32)

    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True, num_workers=4, pin_memory=True)
    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False, num_workers=4)

    print(f"Train: {len(train_dataset)} examples, Val: {len(val_dataset)} examples")

    # --- Optimizer ---
    lr = train_cfg.get("lr", 3e-4)
    epochs = train_cfg.get("epochs", 10)
    warmup_steps = train_cfg.get("warmup_steps", 500)
    total_steps = len(train_loader) * epochs

    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    scheduler = get_cosine_schedule_with_warmup(optimizer, warmup_steps, total_steps)

    # --- Mixed precision ---
    use_amp = train_cfg.get("use_amp", True) and device.type == "cuda"
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)
    amp_dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16

    # --- Training ---
    checkpoint_dir = Path(train_cfg.get("checkpoint_dir", "checkpoints/translator"))
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    best_val_loss = float("inf")

    for epoch in range(epochs):
        model.train()
        epoch_loss = 0.0
        for i, batch in enumerate(train_loader):
            batch = {k: v.to(device) for k, v in batch.items()}

            with torch.amp.autocast("cuda", dtype=amp_dtype, enabled=use_amp):
                outputs = model(**batch)
                loss = outputs.loss

            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(optimizer)
            scaler.update()
            scheduler.step()
            optimizer.zero_grad()

            epoch_loss += loss.item()

            if (i + 1) % 100 == 0:
                avg = epoch_loss / (i + 1)
                print(f"  Epoch {epoch+1}/{epochs} step {i+1}/{len(train_loader)} loss={avg:.4f}")

        avg_train_loss = epoch_loss / len(train_loader)

        # Validation
        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for batch in val_loader:
                batch = {k: v.to(device) for k, v in batch.items()}
                with torch.amp.autocast("cuda", dtype=amp_dtype, enabled=use_amp):
                    outputs = model(**batch)
                val_loss += outputs.loss.item()
        avg_val_loss = val_loss / len(val_loader)

        print(f"Epoch {epoch+1}/{epochs}: train_loss={avg_train_loss:.4f} val_loss={avg_val_loss:.4f}")

        # Save best
        if avg_val_loss < best_val_loss:
            best_val_loss = avg_val_loss
            save_path = checkpoint_dir / "best"
            model.save_pretrained(save_path)
            tokenizer.save_pretrained(save_path)
            print(f"  New best model saved to {save_path}")

    # Save final
    final_path = checkpoint_dir / "final"
    model.save_pretrained(final_path)
    tokenizer.save_pretrained(final_path)
    print(f"Training complete. Final model: {final_path}")


if __name__ == "__main__":
    main()
