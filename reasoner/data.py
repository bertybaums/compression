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
    """Dataset of tokenized UGF reasoning traces.

    The `heldout_ids_path` hook filters out any record whose
    `rsplit('-', 1)[0]` doc-key matches a held-out passage's doc-key.
    Main reasoning traces (ids like `reasoning-NNNNNNN`) never match, so
    the filter is a no-op for them. Derived reasoning traces that link
    back to parallel-corpus passages (cxbot, misc-corpora) are filtered
    consistently with the Translator's hold-out.
    """

    def __init__(
        self,
        data_path: str | Path,
        tokenizer: UGFTokenizer,
        max_seq_len: int = 512,
        text_field: str = "ugf_text",
        filter_compliant: bool = True,
        heldout_ids_path: str | Path | None = None,
    ):
        self.tokenizer = tokenizer
        self.max_seq_len = max_seq_len
        self.records = []

        heldout_doc_ids: set[str] = set()
        if heldout_ids_path is not None:
            with open(heldout_ids_path) as f:
                passage_ids = json.load(f)["heldout_passage_ids"]
            heldout_doc_ids = {pid.rsplit("-", 1)[0] for pid in passage_ids}

        n_skipped_heldout = 0
        with open(data_path, "r", encoding="utf-8") as f:
            for line in f:
                record = json.loads(line)
                if filter_compliant and not record.get("compliant", True):
                    continue
                if heldout_doc_ids:
                    rid = record.get("id", "")
                    if rid and rid.rsplit("-", 1)[0] in heldout_doc_ids:
                        n_skipped_heldout += 1
                        continue
                text = record.get(text_field, "")
                if text and len(text.split()) >= 10:  # skip very short
                    self.records.append(text)

        if heldout_ids_path is not None and n_skipped_heldout:
            print(f"Hold-out: skipped {n_skipped_heldout} reasoning records from {data_path}")

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
        heldout_ids_path: str | Path | None = None,
    ):
        self.tokenizer = tokenizer
        self.max_seq_len = max_seq_len
        self.records = []

        heldout_ids: set[str] = set()
        if heldout_ids_path is not None:
            with open(heldout_ids_path) as f:
                heldout_ids = set(json.load(f)["heldout_passage_ids"])
            print(f"Hold-out: excluding {len(heldout_ids)} passage IDs from {heldout_ids_path}")

        n_skipped_heldout = 0
        with open(data_path, "r", encoding="utf-8") as f:
            for line in f:
                record = json.loads(line)
                if filter_compliant and not record.get("compliant", True):
                    continue
                if record.get("id") in heldout_ids:
                    n_skipped_heldout += 1
                    continue
                text = record.get("ugf", "")
                if text and len(text.split()) >= 10:
                    self.records.append(text)
        if heldout_ids_path is not None:
            print(f"Hold-out: skipped {n_skipped_heldout} records")

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
    heldout_ids_path: str | Path | None = None,
) -> DataLoader:
    """Create a DataLoader for Reasoner training.

    Args:
        dataset_type: "reasoning" for UGF reasoning traces,
                      "parallel" for UGF side of parallel corpus.
        heldout_ids_path: JSON file of held-out passage IDs. For "parallel"
                          dataset, filters by exact ID match. For "reasoning"
                          dataset, filters by doc-key (so cxbot/misc-corpora
                          reasoning traces whose IDs link back to a held-out
                          passage are excluded; main reasoning-NNNNNNN traces
                          have no doc-key collision so the filter is a no-op
                          for them).
    """
    if dataset_type == "reasoning":
        dataset = UGFDataset(
            data_path, tokenizer, max_seq_len,
            heldout_ids_path=heldout_ids_path,
        )
    elif dataset_type == "parallel":
        dataset = ParallelUGFDataset(
            data_path, tokenizer, max_seq_len,
            heldout_ids_path=heldout_ids_path,
        )
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
