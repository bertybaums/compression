"""
UGF (Up Goer Five) word-level tokenizer.

A tokenizer whose vocabulary contains only the ~3,600 inflected forms derived
from the 1,000 most common English lemmas (Munroe's Thing Explainer / XKCD
Simple Writer list), plus punctuation, numerals, and special tokens.

Implements the HuggingFace PreTrainedTokenizer interface so it can be used
with standard training loops and data utilities.
"""

import json
import re
from pathlib import Path
from typing import Optional

from transformers import PreTrainedTokenizer


DEFAULT_VOCAB_PATH = Path(__file__).parent.parent / "wordlist" / "vocab_final.json"

# Regex to split text into word tokens and non-word tokens (punctuation, newlines, etc.)
# Matches: sequences of word chars + apostrophes (for contractions), single digits,
# newlines (as their own token), or any other single non-whitespace char
_TOKENIZE_RE = re.compile(r"[a-zA-Z]+(?:'[a-zA-Z]+)*|\d|\n|\S")


class UGFTokenizer(PreTrainedTokenizer):
    """Word-level tokenizer for the Up Goer Five vocabulary."""

    model_input_names = ["input_ids", "attention_mask"]

    def __init__(
        self,
        vocab_path: Optional[str | Path] = None,
        **kwargs,
    ):
        # Load vocabulary before calling super().__init__
        vocab_path = Path(vocab_path) if vocab_path else DEFAULT_VOCAB_PATH
        with open(vocab_path, "r", encoding="utf-8") as f:
            self._token_to_id: dict[str, int] = json.load(f)
        self._id_to_token: dict[int, str] = {v: k for k, v in self._token_to_id.items()}

        # Set special token strings for parent class
        kwargs.setdefault("pad_token", "<PAD>")
        kwargs.setdefault("unk_token", "<UNK>")
        kwargs.setdefault("bos_token", "<BOS>")
        kwargs.setdefault("eos_token", "<EOS>")

        super().__init__(**kwargs)

    # --- Required overrides for PreTrainedTokenizer ---

    @property
    def vocab_size(self) -> int:
        return len(self._token_to_id)

    def get_vocab(self) -> dict[str, int]:
        return dict(self._token_to_id)

    def build_inputs_with_special_tokens(
        self, token_ids_0: list[int], token_ids_1: Optional[list[int]] = None
    ) -> list[int]:
        bos = [self.bos_token_id]
        eos = [self.eos_token_id]
        if token_ids_1 is None:
            return bos + token_ids_0 + eos
        return bos + token_ids_0 + eos + bos + token_ids_1 + eos

    def _tokenize(self, text: str, **kwargs) -> list[str]:
        """Split text into word-level tokens."""
        tokens = []
        raw_tokens = _TOKENIZE_RE.findall(text)
        for raw in raw_tokens:
            lower = raw.lower()
            if lower in self._token_to_id:
                # Check if the original was capitalized (and not a single char)
                if raw[0].isupper() and len(raw) > 1:
                    tokens.append("<CAP>")
                tokens.append(lower)
            elif raw in self._token_to_id:
                tokens.append(raw)
            else:
                # Unknown word
                tokens.append("<UNK>")
        return tokens

    def _convert_token_to_id(self, token: str) -> int:
        return self._token_to_id.get(token, self._token_to_id["<UNK>"])

    def _convert_id_to_token(self, index: int) -> str:
        return self._id_to_token.get(index, "<UNK>")

    def convert_tokens_to_string(self, tokens: list[str]) -> str:
        """Reconstruct text from tokens, handling <CAP> and punctuation spacing."""
        parts = []
        capitalize_next = False
        for tok in tokens:
            if tok in ("<BOS>", "<EOS>", "<PAD>", "<UNK>"):
                continue
            if tok == "<CAP>":
                capitalize_next = True
                continue
            if tok == "\n":
                parts.append("\n")
                continue

            # Punctuation that should not have a leading space
            if tok in (".", ",", "!", "?", ";", ":", ")", "'", '"') and parts:
                text = tok
            # Opening punctuation that should not have a trailing space
            elif tok in ("(", '"') and not parts:
                text = tok
            else:
                text = (" " + tok) if parts and parts[-1] != "\n" else tok

            if capitalize_next:
                text = text[0] + text[1:].capitalize() if len(text) > 1 and text[0] == " " else text.capitalize()
                capitalize_next = False

            parts.append(text)

        return "".join(parts).strip()

    def save_vocabulary(self, save_directory: str, filename_prefix: Optional[str] = None) -> tuple[str]:
        save_directory = Path(save_directory)
        save_directory.mkdir(parents=True, exist_ok=True)
        prefix = f"{filename_prefix}-" if filename_prefix else ""
        vocab_file = save_directory / f"{prefix}vocab.json"
        with open(vocab_file, "w", encoding="utf-8") as f:
            json.dump(self._token_to_id, f, indent=2, ensure_ascii=False)
        return (str(vocab_file),)

    # --- UGF-specific utilities ---

    def validate(self, text: str) -> tuple[bool, list[str]]:
        """Check whether all words in text are in the UGF vocabulary.

        Returns:
            (is_valid, violations) where violations is a list of out-of-vocabulary words.
        """
        raw_tokens = _TOKENIZE_RE.findall(text)
        violations = []
        for raw in raw_tokens:
            lower = raw.lower()
            # Allow if the lowercase form is in vocab, or the raw form (for punctuation/numerals)
            if lower not in self._token_to_id and raw not in self._token_to_id:
                violations.append(raw)
        return (len(violations) == 0, violations)

    def ugf_compliance_ratio(self, text: str) -> float:
        """Fraction of tokens in text that are in the UGF vocabulary."""
        raw_tokens = _TOKENIZE_RE.findall(text)
        if not raw_tokens:
            return 1.0
        valid = sum(
            1 for raw in raw_tokens
            if raw.lower() in self._token_to_id or raw in self._token_to_id
        )
        return valid / len(raw_tokens)
