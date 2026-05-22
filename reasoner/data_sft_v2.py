"""
SFT v2 dataset for Reasoner — purist think-answer architecture.

Differs from data_sft.py (v1) in three ways:

1. Reads `corpus/processed/ugf_cot.jsonl` (CoT corpus, not the v1 reasoning
   corpus). Schema: {id, track, depth, prompt_text, reasoning, verdict (for
   logic) | conclusion (for philosophy), compliant, ...}.

2. Each record is reformatted with an explicit phrasal marker:

       [prompt_text]
       [reasoning]
       So my answer is:
       [answer]

   Where [answer] is rendered per track:
       logic.verdict == "follows"          → "The case follows."
       logic.verdict == "does not follow"  → "The case does not follow."
       philosophy.conclusion               → verbatim

3. Loss masking: the prompt is masked (labels = -100). The reasoning, marker
   phrase ("So my answer is:"), answer, and EOS are all trained. The model
   learns to emit the marker phrase as part of its generation pattern.

See docs/sft-v2-design-2026-05-18.md for the full rationale and the
locked decisions (asymmetric single marker, pure-UGF phrasing, fallback to
special tokens if parse-failure > 5%).
"""

import hashlib
import json
from pathlib import Path

import torch
import torch.nn.functional as F
from torch.utils.data import Dataset

from tokenizer.ugf_tokenizer import UGFTokenizer


# The single canonical marker phrase. All UGF words. Capital S, ends with colon.
ANSWER_MARKER = "So my answer is:"


def _render_logic_answer(verdict: str) -> str | None:
    if verdict == "follows":
        return "The case follows."
    if verdict == "does not follow":
        return "The case does not follow."
    return None


def _render_philosophy_answer(conclusion: str) -> str | None:
    conclusion = (conclusion or "").strip()
    if not conclusion:
        return None
    # Drop records whose conclusion happens to contain the marker phrase
    # (would otherwise produce two markers in the formatted sequence).
    if ANSWER_MARKER.lower() in conclusion.lower():
        return None
    return conclusion


def render_record(record: dict) -> tuple[str, str, str] | None:
    """Return (prompt, reasoning, answer) tuple or None if record is unusable."""
    if not record.get("compliant", False):
        return None
    prompt = (record.get("prompt_text") or "").strip()
    reasoning = (record.get("reasoning") or "").strip()
    if not prompt or not reasoning:
        return None
    if len(reasoning.split()) < 10:
        return None
    # The reasoning itself must not contain the marker phrase verbatim,
    # or we'll get two markers when concatenated with the synthetic one.
    if ANSWER_MARKER.lower() in reasoning.lower():
        return None

    track = record.get("track")
    if track == "logic":
        answer = _render_logic_answer(record.get("verdict", ""))
    elif track == "philosophy":
        answer = _render_philosophy_answer(record.get("conclusion", ""))
    else:
        return None
    if answer is None:
        return None
    return prompt, reasoning, answer


def _stable_hash_in_val(rid: str, fraction: float, buckets: int = 10000) -> bool:
    """Stable val selection. Mirrors data.py / data_sft.py."""
    if fraction <= 0 or not rid:
        return False
    digest = hashlib.md5(rid.encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:4], "big") % buckets
    return bucket < int(fraction * buckets)


class UGFSFTv2Dataset(Dataset):
    """SFT v2 dataset: think-answer-formatted CoT traces with phrasal marker.

    Each item, when tokenized, produces:

        [BOS] + prompt_ids + response_ids + [EOS]

    where response_ids tokenizes "{reasoning} {ANSWER_MARKER} {answer}".

    Labels mask BOS + prompt; everything else is trained.

    Sequence-length policy: if the full tokenized sequence exceeds
    max_seq_len, the reasoning span is truncated from its TAIL (preserving
    the prompt at the front, and the marker + answer + EOS at the back).
    Records whose prompt + marker + answer + EOS alone exceeds max_seq_len
    are dropped at construction time.
    """

    def __init__(
        self,
        data_path: str | Path,
        tokenizer: UGFTokenizer,
        max_seq_len: int = 512,
        heldout_ids_path: str | Path | None = None,
        include_only_heldout: bool = False,
        random_val_fraction: float = 0.0,
    ):
        self.tokenizer = tokenizer
        self.max_seq_len = max_seq_len
        # Each item: (prompt_str, reasoning_str, answer_str)
        self.records: list[tuple[str, str, str]] = []

        heldout_doc_ids: set[str] = set()
        if heldout_ids_path is not None:
            with open(heldout_ids_path) as f:
                passage_ids = json.load(f)["heldout_passage_ids"]
            heldout_doc_ids = {pid.rsplit("-", 1)[0] for pid in passage_ids}

        n_dropped_unrenderable = 0
        n_dropped_too_long = 0
        n_skipped_holdout = 0

        with open(data_path, "r", encoding="utf-8") as f:
            for line in f:
                record = json.loads(line)
                rendered = render_record(record)
                if rendered is None:
                    n_dropped_unrenderable += 1
                    continue
                prompt, reasoning, answer = rendered

                # Hold-out gating (same convention as data_sft.py).
                rid = record.get("id", "")
                doc_key = rid.rsplit("-", 1)[0] if rid else ""
                is_heldout = (
                    (bool(heldout_doc_ids) and doc_key in heldout_doc_ids)
                    or _stable_hash_in_val(rid, random_val_fraction)
                )
                if include_only_heldout:
                    if not is_heldout:
                        n_skipped_holdout += 1
                        continue
                else:
                    if is_heldout:
                        n_skipped_holdout += 1
                        continue

                # Cheap length-budget pre-check: drop records where the
                # non-truncatable spans (prompt + marker + answer + EOS)
                # alone overflow max_seq_len.
                fixed_text = f"{prompt} {ANSWER_MARKER} {answer}"
                fixed_tokens = tokenizer.encode(fixed_text, add_special_tokens=False)
                if 1 + len(fixed_tokens) + 1 > max_seq_len:  # +BOS +EOS
                    n_dropped_too_long += 1
                    continue

                self.records.append((prompt, reasoning, answer))

        if n_dropped_unrenderable:
            print(f"SFTv2: dropped {n_dropped_unrenderable} unrenderable records ({data_path})")
        if n_dropped_too_long:
            print(f"SFTv2: dropped {n_dropped_too_long} records exceeding max_seq_len ({data_path})")
        if n_skipped_holdout:
            mode = "kept-only" if include_only_heldout else "skipped"
            print(f"SFTv2 hold-out: {mode} {n_skipped_holdout} records ({data_path})")
        print(f"SFTv2: loaded {len(self.records)} records ({data_path})")

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        prompt_str, reasoning_str, answer_str = self.records[idx]
        bos_id = self.tokenizer.bos_token_id
        eos_id = self.tokenizer.eos_token_id

        prompt_ids = self.tokenizer.encode(prompt_str, add_special_tokens=False)
        marker_ids = self.tokenizer.encode(f" {ANSWER_MARKER} ", add_special_tokens=False)
        answer_ids = self.tokenizer.encode(answer_str, add_special_tokens=False)
        reasoning_ids = self.tokenizer.encode(f" {reasoning_str}", add_special_tokens=False)

        # Budget for reasoning: max_seq_len - [BOS + prompt + marker + answer + EOS]
        fixed_len = 1 + len(prompt_ids) + len(marker_ids) + len(answer_ids) + 1
        budget = self.max_seq_len - fixed_len
        if budget < 0:
            # Should not happen: pre-check in __init__ guarantees fixed_len <= max_seq_len.
            # If it does happen, truncate the answer (last resort).
            overflow = -budget
            answer_ids = answer_ids[:max(1, len(answer_ids) - overflow)]
            fixed_len = 1 + len(prompt_ids) + len(marker_ids) + len(answer_ids) + 1
            budget = self.max_seq_len - fixed_len

        # Truncate reasoning from the tail if needed. (Tail-truncation
        # preserves the start of the reasoning, which is typically where
        # the most important framing happens.)
        if len(reasoning_ids) > budget:
            reasoning_ids = reasoning_ids[:budget]

        full_ids = (
            [bos_id]
            + prompt_ids
            + reasoning_ids
            + marker_ids
            + answer_ids
            + [eos_id]
        )
        prompt_prefix_len = 1 + len(prompt_ids)  # BOS + prompt

        input_ids = torch.tensor(full_ids, dtype=torch.long)
        labels = input_ids.clone()
        labels[:prompt_prefix_len] = -100  # mask BOS + prompt; train on everything after

        return {"input_ids": input_ids, "labels": labels}


def sft_v2_collate_fn(batch: list[dict], pad_id: int = 0) -> dict[str, torch.Tensor]:
    """Pad SFT v2 batch. Identical to sft_collate_fn in data_sft.py; included
    here for the v2 train loop to import without cross-importing data_sft."""
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
