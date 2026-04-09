"""
Dataset and data loading for Reasoner training.

Reads JSONL files of pure UGF reasoning traces, tokenizes with UGFTokenizer,
and produces padded/truncated sequences for the training loop.
"""

import json
from pathlib import Path

import torch
from torch.utils.data import Dataset, DataLoader

from tokenizer.ugf_tokenizer import UGFTokenizer


class UGFDataset(Dataset):
    """Dataset of tokenized UGF reasoning traces."""

    def __init__(
        self,
        data_path: str | Path,
        tokenizer: UGFTokenizer,
        max_seq_len: int = 512,
        text_field: str = "ugf_text",
        filter_compliant: bool = True,
    ):
        self.tokenizer = tokenizer
        self.max_seq_len = max_seq_len
        self.records = []

        with open(data_path, "r", encoding="utf-8") as f:
            for line in f:
                record = json.loads(line)
                if filter_compliant and not record.get("compliant", True):
                    continue
                text = record.get(text_field, "")
                if text and len(text.split()) >= 10:  # skip very short
                    self.records.append(text)

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        text = self.records[idx]

        # Tokenize with BOS/EOS
        token_ids = self.tokenizer.encode(text, add_special_tokens=True)

        # Truncate to max_seq_len
        if len(token_ids) > self.max_seq_len:
            token_ids = token_ids[: self.max_seq_len - 1] + [self.tokenizer.eos_token_id]

        # For causal LM: input = tokens[:-1], labels = tokens[1:]
        # But we pass the full sequence and let the model shift internally
        input_ids = torch.tensor(token_ids, dtype=torch.long)

        # Labels: same as input_ids, with padding positions set to -100
        labels = input_ids.clone()

        return {"input_ids": input_ids, "labels": labels}


class ParallelUGFDataset(Dataset):
    """Dataset of UGF text from parallel corpus (for pretraining the Reasoner
    on the UGF side of the parallel translations)."""

    def __init__(
        self,
        data_path: str | Path,
        tokenizer: UGFTokenizer,
        max_seq_len: int = 512,
        filter_compliant: bool = True,
    ):
        self.tokenizer = tokenizer
        self.max_seq_len = max_seq_len
        self.records = []

        with open(data_path, "r", encoding="utf-8") as f:
            for line in f:
                record = json.loads(line)
                if filter_compliant and not record.get("compliant", True):
                    continue
                text = record.get("ugf", "")
                if text and len(text.split()) >= 10:
                    self.records.append(text)

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        text = self.records[idx]
        token_ids = self.tokenizer.encode(text, add_special_tokens=True)

        if len(token_ids) > self.max_seq_len:
            token_ids = token_ids[: self.max_seq_len - 1] + [self.tokenizer.eos_token_id]

        input_ids = torch.tensor(token_ids, dtype=torch.long)
        labels = input_ids.clone()

        return {"input_ids": input_ids, "labels": labels}


def collate_fn(batch: list[dict], pad_id: int = 0) -> dict[str, torch.Tensor]:
    """Pad sequences to the longest in the batch."""
    max_len = max(item["input_ids"].shape[0] for item in batch)

    input_ids = []
    labels = []
    attention_mask = []

    for item in batch:
        seq_len = item["input_ids"].shape[0]
        pad_len = max_len - seq_len

        input_ids.append(F.pad(item["input_ids"], (0, pad_len), value=pad_id))
        # Pad labels with -100 (ignore index for cross_entropy)
        labels.append(F.pad(item["labels"], (0, pad_len), value=-100))
        # Attention mask: 1 for real tokens, 0 for padding
        mask = torch.ones(seq_len, dtype=torch.long)
        attention_mask.append(F.pad(mask, (0, pad_len), value=0))

    return {
        "input_ids": torch.stack(input_ids),
        "labels": torch.stack(labels),
        "attention_mask": torch.stack(attention_mask),
    }


# Need F for collate_fn
import torch.nn.functional as F


def create_dataloader(
    data_path: str | Path,
    tokenizer: UGFTokenizer,
    max_seq_len: int = 512,
    batch_size: int = 8,
    shuffle: bool = True,
    num_workers: int = 4,
    dataset_type: str = "reasoning",
) -> DataLoader:
    """Create a DataLoader for Reasoner training.

    Args:
        dataset_type: "reasoning" for UGF reasoning traces,
                      "parallel" for UGF side of parallel corpus.
    """
    if dataset_type == "reasoning":
        dataset = UGFDataset(data_path, tokenizer, max_seq_len)
    elif dataset_type == "parallel":
        dataset = ParallelUGFDataset(data_path, tokenizer, max_seq_len)
    else:
        raise ValueError(f"Unknown dataset_type: {dataset_type}")

    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle,
        num_workers=num_workers,
        collate_fn=lambda batch: collate_fn(batch, pad_id=tokenizer.pad_token_id),
        pin_memory=True,
        drop_last=True,
    )
