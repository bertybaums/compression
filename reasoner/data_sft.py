"""
SFT dataset for Reasoner fine-tuning (Phase 2).

Reads the same JSONL files as the Phase-1 pretraining UGFDataset, but formats
each record as an explicit (prompt, response) pair using the same CONTENT_TYPES
templates that drove corpus generation. The resulting training sequence is
[BOS] + prompt_tokens + response_tokens + [EOS], with labels set to -100 for
the prompt positions so loss only flows from the response.

Why a separate file from data.py: the SFT data path and collate are
distinguishable from pretrain artifacts at the file/import level. Phase 1 and
Phase 2 share the model (reasoner/model.py) but their data paths must not be
confusable.

Heldout / val mechanics mirror UGFDataset (doc-key heldout + random_val_fraction).
"""

import hashlib
import json
from pathlib import Path

import torch
import torch.nn.functional as F
from torch.utils.data import Dataset

from tokenizer.ugf_tokenizer import UGFTokenizer


# CONTENT_TYPES must stay in sync with corpus/generation/generate_reasoning.py.
# Copied here (not imported) so this module has no side effects on import — the
# generate_reasoning module reads .env and config.yaml at import time.
CONTENT_TYPES = {
    "concept_explanation": (
        "Write a clear explanation of the following idea. Think step by step. "
        "Make sure someone who has never studied this before could understand. "
        "Write in plain running prose -- no asterisks, no bold, no bullet lists, "
        "no numbered headers.\n\n"
        "Topic: {topic}\n\n"
        "Explanation:"
    ),
    "chain_of_thought": (
        "Work through the following problem step by step. Show your thinking "
        "at each step. Write steps as plain sentences joined into a paragraph "
        "(for example: 'First, we notice ... Then we can see ... This means ...'). "
        "Do NOT use numbered lists, bullet points, asterisks, or any markdown.\n\n"
        "Problem: {topic}\n\n"
        "Step-by-step thinking:"
    ),
    "socratic_dialogue": (
        "Write a short conversation between two people about the following topic. "
        "One person asks questions, the other explains. The conversation should "
        "go at least 6 turns. Use plain text only -- no asterisks, no bold.\n\n"
        "Topic: {topic}\n\n"
        "Conversation:\n"
        "Person 1:"
    ),
    "argument_analysis": (
        "Someone makes the following case. Break it down into its parts: what "
        "they are saying is true, what they think follows from that, and whether "
        "the thinking is good. Write this as flowing paragraphs of plain prose. "
        "Do NOT use asterisks, bold, bullet points, or numbered headers. You can "
        "refer to ideas as 'the first idea', 'the second idea', and so on inside "
        "the prose.\n\n"
        "The case: {topic}\n\n"
        "Breaking this down:"
    ),
    "thought_experiment": (
        "Walk through the following situation that makes you think. Describe what "
        "is happening, what the hard question is, and what different answers people "
        "might give and why. Write in flowing paragraphs of plain prose -- no "
        "asterisks, no bold, no bullet points, no numbered headers.\n\n"
        "Situation: {topic}\n\n"
        "Walk-through:"
    ),
}


def _stable_hash_in_val(rid: str, fraction: float, buckets: int = 10000) -> bool:
    """Stable, process-independent hash-based val selection. Mirrors data.py."""
    if fraction <= 0 or not rid:
        return False
    digest = hashlib.md5(rid.encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:4], "big") % buckets
    return bucket < int(fraction * buckets)


class UGFSFTDataset(Dataset):
    """Wraps UGF reasoning records as (prompt, response) pairs for SFT.

    For each record:
      prompt = CONTENT_TYPES[record.content_type].format(topic=record.topic)
      response = record.ugf_text

    The training sequence is [BOS] + prompt_tokens + response_tokens + [EOS],
    with labels set to -100 for prompt positions so loss only flows from the
    response. Records lacking a known content_type or without a usable
    response are skipped (these are mostly parallel-corpus records, which
    don't fit the SFT prompt schema).
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
        self.records: list[tuple[str, str]] = []  # (prompt_str, response_str)

        heldout_doc_ids: set[str] = set()
        if heldout_ids_path is not None:
            with open(heldout_ids_path) as f:
                passage_ids = json.load(f)["heldout_passage_ids"]
            heldout_doc_ids = {pid.rsplit("-", 1)[0] for pid in passage_ids}

        n_skipped = 0
        n_no_content_type = 0
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

                content_type = record.get("content_type")
                if content_type not in CONTENT_TYPES:
                    n_no_content_type += 1
                    continue
                topic = record.get("topic", "")
                response = record.get(text_field, "")
                if not response or len(response.split()) < 10:
                    continue

                prompt = CONTENT_TYPES[content_type].format(topic=topic)
                self.records.append((prompt, response))

        if (heldout_ids_path is not None or random_val_fraction > 0) and n_skipped:
            mode = "kept-only" if include_only_heldout else "skipped"
            print(f"Hold-out: {mode} {n_skipped} SFT records ({data_path})")
        if n_no_content_type:
            print(f"SFT: skipped {n_no_content_type} records without content_type ({data_path})")

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        prompt_str, response_str = self.records[idx]
        bos_id = self.tokenizer.bos_token_id
        eos_id = self.tokenizer.eos_token_id

        prompt_ids = self.tokenizer.encode(prompt_str, add_special_tokens=False)
        response_ids = self.tokenizer.encode(response_str, add_special_tokens=False)

        # [BOS] + prompt + response + [EOS]
        full_ids = [bos_id] + prompt_ids + response_ids + [eos_id]
        prompt_prefix_len = 1 + len(prompt_ids)  # BOS counts as part of prompt prefix

        # Truncate from the right (drop response tail) if too long.
        if len(full_ids) > self.max_seq_len:
            full_ids = full_ids[: self.max_seq_len - 1] + [eos_id]
            prompt_prefix_len = min(prompt_prefix_len, len(full_ids))

        input_ids = torch.tensor(full_ids, dtype=torch.long)
        labels = input_ids.clone()
        # Mask prompt positions so loss only flows from response tokens.
        labels[:prompt_prefix_len] = -100

        return {"input_ids": input_ids, "labels": labels}


class UGFSFTPlainDataset(UGFSFTDataset):
    """Like UGFSFTDataset, but reads `prompt` and `response` directly from each
    record instead of building the prompt from a content_type template.

    For form-diverse corpora (dialogue / objection-reply) whose `prompt` field is
    already the specific turn or objection, not a topic phrase to be wrapped. The
    tokenization, prompt-masking, and collate are identical to the parent; only
    record loading differs. Records are kept iff they carry both a non-empty
    `prompt` and `response` (and, when filter_compliant, compliant != False).
    """

    def __init__(
        self,
        data_path,
        tokenizer: UGFTokenizer,
        max_seq_len: int = 512,
        filter_compliant: bool = True,
        heldout_ids_path=None,
        include_only_heldout: bool = False,
        random_val_fraction: float = 0.0,
    ):
        self.tokenizer = tokenizer
        self.max_seq_len = max_seq_len
        self.records: list[tuple[str, str]] = []

        heldout_doc_ids: set[str] = set()
        if heldout_ids_path is not None and Path(heldout_ids_path).exists():
            with open(heldout_ids_path) as f:
                passage_ids = json.load(f)["heldout_passage_ids"]
            heldout_doc_ids = {pid.rsplit("-", 1)[0] for pid in passage_ids}

        n_skipped = 0
        n_dropped = 0
        with open(data_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
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

                prompt = (record.get("prompt") or "").strip()
                response = (record.get("response") or "").strip()
                if not prompt or not response:
                    n_dropped += 1
                    continue
                self.records.append((prompt, response))

        if (heldout_ids_path is not None or random_val_fraction > 0) and n_skipped:
            mode = "kept-only" if include_only_heldout else "skipped"
            print(f"Hold-out: {mode} {n_skipped} plain-SFT records ({data_path})")
        if n_dropped:
            print(f"Plain-SFT: dropped {n_dropped} records missing prompt/response ({data_path})")
        print(f"Plain-SFT: loaded {len(self.records)} (prompt, response) pairs ({data_path})")


def sft_collate_fn(batch: list[dict], pad_id: int = 0) -> dict[str, torch.Tensor]:
    """Pad SFT batch. Pads input_ids with pad_id, labels with -100, mask with 0."""
    max_len = max(item["input_ids"].shape[0] for item in batch)
    input_ids, labels, attention_mask = [], [], []
    for item in batch:
        seq_len = item["input_ids"].shape[0]
        pad_len = max_len - seq_len
        input_ids.append(F.pad(item["input_ids"], (0, pad_len), value=pad_id))
        labels.append(F.pad(item["labels"], (0, pad_len), value=-100))
        mask = torch.ones(seq_len, dtype=torch.long)
        attention_mask.append(F.pad(mask, (0, pad_len), value=0))
    return {
        "input_ids": torch.stack(input_ids),
        "labels": torch.stack(labels),
        "attention_mask": torch.stack(attention_mask),
    }
