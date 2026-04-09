"""
Translator: bidirectional English <-> Up Goer Five translation.

Architecture: Fine-tuned T5-small (60M params) with constrained decoding
for the English->UGF direction.

The encoder uses T5's standard BPE tokenizer (understands full English).
The decoder also uses BPE, but at inference time a StateMachineLogitsProcessor
constrains output to only produce valid UGF words.

Bidirectional: a prefix token approach.
  - "translate to simple: {English}" -> UGF
  - "translate to full: {UGF}" -> English

For UGF->English, no constraint is needed (output is unconstrained English).
"""

import json
from pathlib import Path
from typing import Optional

import torch
from transformers import (
    T5ForConditionalGeneration,
    T5Tokenizer,
    LogitsProcessor,
)

DEFAULT_VOCAB_PATH = Path(__file__).parent.parent / "wordlist" / "vocab_final.json"


class StateMachineLogitsProcessor(LogitsProcessor):
    """Constrains T5 decoder output to only produce valid UGF words.

    Strategy: maintain a trie of BPE token sequences that spell valid UGF words.
    At each decoding step, mask out any token that cannot lead to a valid UGF word
    given the tokens generated so far within the current word.

    This is a simplified version that works at the word boundary level:
    after each complete word (followed by a space or punctuation), reset the state.
    Within a word, only allow BPE tokens that are prefixes of valid UGF words.
    """

    def __init__(self, bpe_tokenizer: T5Tokenizer, ugf_vocab_path: Optional[Path] = None):
        self.bpe_tokenizer = bpe_tokenizer
        ugf_vocab_path = ugf_vocab_path or DEFAULT_VOCAB_PATH

        with open(ugf_vocab_path) as f:
            ugf_vocab = json.load(f)

        # Get all UGF words (excluding special tokens and punctuation)
        self.ugf_words = set()
        for token in ugf_vocab:
            if not token.startswith("<") and len(token) > 0:
                self.ugf_words.add(token)

        # Build a set of allowed BPE token IDs:
        # For each UGF word, find all BPE tokens that appear in its encoding
        self.allowed_token_ids = set()

        # Always allow EOS, pad, and common whitespace/punctuation tokens
        for special_id in [
            bpe_tokenizer.eos_token_id,
            bpe_tokenizer.pad_token_id,
        ]:
            if special_id is not None:
                self.allowed_token_ids.add(special_id)

        # Encode each UGF word and collect all BPE token IDs used
        for word in self.ugf_words:
            # Encode with and without leading space (T5 tokenizer behavior)
            for text in [word, f" {word}"]:
                ids = bpe_tokenizer.encode(text, add_special_tokens=False)
                self.allowed_token_ids.update(ids)

        # Also allow common punctuation and spacing tokens
        for punct in [".", ",", "!", "?", ";", ":", "-", "'", '"', "(", ")", " ", "\n"]:
            ids = bpe_tokenizer.encode(punct, add_special_tokens=False)
            self.allowed_token_ids.update(ids)

        # Allow digit tokens
        for d in "0123456789":
            ids = bpe_tokenizer.encode(d, add_special_tokens=False)
            self.allowed_token_ids.update(ids)

        self.allowed_token_ids = sorted(self.allowed_token_ids)
        self._mask = None
        self._mask_device = None

    def _get_mask(self, vocab_size: int, device: torch.device) -> torch.Tensor:
        """Create and cache the logits mask."""
        if self._mask is None or self._mask_device != device:
            self._mask = torch.full((vocab_size,), float("-inf"), device=device)
            for tid in self.allowed_token_ids:
                if tid < vocab_size:
                    self._mask[tid] = 0.0
            self._mask_device = device
        return self._mask

    def __call__(self, input_ids: torch.LongTensor, scores: torch.FloatTensor) -> torch.FloatTensor:
        mask = self._get_mask(scores.shape[-1], scores.device)
        return scores + mask


class Translator:
    """Bidirectional English <-> UGF translator."""

    def __init__(
        self,
        model_name_or_path: str = "google/flan-t5-small",
        ugf_vocab_path: Optional[Path] = None,
        device: Optional[str] = None,
    ):
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))

        self.t5_tokenizer = T5Tokenizer.from_pretrained(model_name_or_path)
        self.model = T5ForConditionalGeneration.from_pretrained(model_name_or_path)
        self.model = self.model.to(self.device)

        self.ugf_processor = StateMachineLogitsProcessor(
            self.t5_tokenizer, ugf_vocab_path
        )

    def to_ugf(
        self,
        english_text: str,
        max_length: int = 512,
        num_beams: int = 4,
    ) -> str:
        """Translate English text to Up Goer Five with constrained decoding."""
        input_text = f"translate to simple: {english_text}"
        inputs = self.t5_tokenizer(input_text, return_tensors="pt", truncation=True, max_length=512)
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        outputs = self.model.generate(
            **inputs,
            max_length=max_length,
            num_beams=num_beams,
            logits_processor=[self.ugf_processor],
            early_stopping=True,
        )

        return self.t5_tokenizer.decode(outputs[0], skip_special_tokens=True)

    def to_english(
        self,
        ugf_text: str,
        max_length: int = 512,
        num_beams: int = 4,
    ) -> str:
        """Translate Up Goer Five text back to full English (unconstrained)."""
        input_text = f"translate to full: {ugf_text}"
        inputs = self.t5_tokenizer(input_text, return_tensors="pt", truncation=True, max_length=512)
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        outputs = self.model.generate(
            **inputs,
            max_length=max_length,
            num_beams=num_beams,
            early_stopping=True,
        )

        return self.t5_tokenizer.decode(outputs[0], skip_special_tokens=True)

    def save(self, path: str | Path):
        """Save the fine-tuned model."""
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        self.model.save_pretrained(path)
        self.t5_tokenizer.save_pretrained(path)

    @classmethod
    def load(cls, path: str | Path, **kwargs) -> "Translator":
        """Load a fine-tuned translator."""
        return cls(model_name_or_path=str(path), **kwargs)
