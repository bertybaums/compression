"""
Dataset and data loading for Reasoner training.

Reads JSONL files of pure UGF reasoning traces, tokenizes with UGFTokenizer,
and produces padded/truncated sequences for the training loop.

Hold-out mechanism: a record is held-out if EITHER
  (a) its doc-key (`id.rsplit('-', 1)[0]`) appears in heldout_ids_path's
      passage-ID list (used for cxbot, misccorpora, parallel — sources
      where reasoning records derive from a specific source passage), OR
  (b) `random_val_fraction > 0` and its stable hash falls in the chosen
      bucket (used for the main `reasoning-NNNNNNN` corpus, where there's
      no source-passage parent for the doc-key trick to bite on).

Both conditions can apply to the same record harmlessly. The combined
held-out subset is at least `random_val_fraction` for any source.
"""

import hashlib
import json
from pathlib import Path

import torch
from torch.utils.data import Dataset, DataLoader

from tokenizer.ugf_tokenizer import UGFTokenizer


def _stable_hash_in_val(rid: str, fraction: float, buckets: int = 10000) -> bool:
    """Stable, process-independent hash-based val selection."""
    if fraction <= 0 or not rid:
        return False
    digest = hashlib.md5(rid.encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:4], "big") % buckets
    return bucket < int(fraction * buckets)


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
        include_only_heldout: bool = False,
        random_val_fraction: float = 0.0,
    ):
        self.tokenizer = tokenizer
        self.max_seq_len = max_seq_len
        self.records = []

        heldout_doc_ids: set[str] = set()
        if heldout_ids_path is not None:
            with open(heldout_ids_path) as f:
                passage_ids = json.load(f)["heldout_passage_ids"]
            heldout_doc_ids = {pid.rsplit("-", 1)[0] for pid in passage_ids}

        n_skipped = 0
        with open(data_path, "r", encoding="utf-8") as f:
            for line in f:
                record = json.loads(line)
                if filter_compliant and not record.get("compliant", True):
                    continue
                rid = record.get("id", "")
                doc_key = rid.rsplit("-", 1)[0] if rid else ""
                is_heldout = (
                    (bool(heldout_doc_ids) and doc_key in heldout_doc_ids)
                    or _stable_hash_in_val(rid, random_val_fraction)
                )
                if include_only_heldout:
                    if not is_heldout:
                        n_skipped += 1
                        continue
                else:
                    if is_heldout:
                        n_skipped += 1
                        continue
                text = record.get(text_field, "")
                if text and len(text.split()) >= 10:  # skip very short
                    self.records.append(text)

        if (heldout_ids_path is not None or random_val_fraction > 0) and n_skipped:
            mode = "kept-only" if include_only_heldout else "skipped"
            print(f"Hold-out: {mode} {n_skipped} reasoning records ({data_path})")

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
        include_only_heldout: bool = False,
        random_val_fraction: float = 0.0,
    ):
        self.tokenizer = tokenizer
        self.max_seq_len = max_seq_len
        self.records = []

        heldout_ids: set[str] = set()
        if heldout_ids_path is not None:
            with open(heldout_ids_path) as f:
                heldout_ids = set(json.load(f)["heldout_passage_ids"])

        n_skipped = 0
        with open(data_path, "r", encoding="utf-8") as f:
            for line in f:
                record = json.loads(line)
                if filter_compliant and not record.get("compliant", True):
                    continue
                rid = record.get("id", "")
                is_heldout = (
                    (rid in heldout_ids)
                    or _stable_hash_in_val(rid, random_val_fraction)
                )
                if include_only_heldout:
                    if not is_heldout:
                        n_skipped += 1
                        continue
                else:
                    if is_heldout:
                        n_skipped += 1
                        continue
                text = record.get("ugf", "")
                if text and len(text.split()) >= 10:
                    self.records.append(text)
        if (heldout_ids_path is not None or random_val_fraction > 0) and n_skipped:
            mode = "kept-only" if include_only_heldout else "skipped"
            print(f"Hold-out: {mode} {n_skipped} records ({data_path})")

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
