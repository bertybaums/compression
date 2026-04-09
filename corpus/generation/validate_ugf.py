"""
UGF validation utilities for corpus generation.

Provides the vocabulary check used in the generation loop: after each API
response, verify that every word is in the Up Goer Five vocabulary. If not,
build a correction prompt listing the violations.
"""

import sys
import unicodedata
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tokenizer.ugf_tokenizer import UGFTokenizer

_TOKENIZER = None


def get_tokenizer() -> UGFTokenizer:
    global _TOKENIZER
    if _TOKENIZER is None:
        _TOKENIZER = UGFTokenizer()
    return _TOKENIZER


def normalize_unicode(text: str) -> str:
    """Normalize unicode characters that LLMs commonly substitute.

    Replaces smart quotes, en/em dashes, non-breaking hyphens, etc. with
    their ASCII equivalents so they don't trigger false vocab violations.
    """
    replacements = {
        "\u2010": "-",   # hyphen
        "\u2011": "-",   # non-breaking hyphen
        "\u2012": "-",   # figure dash
        "\u2013": "-",   # en dash
        "\u2014": "-",   # em dash
        "\u2015": "-",   # horizontal bar
        "\u2018": "'",   # left single quote
        "\u2019": "'",   # right single quote
        "\u201c": '"',   # left double quote
        "\u201d": '"',   # right double quote
        "\u2026": "...", # ellipsis
        "\u00a0": " ",   # non-breaking space
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def validate_ugf(text: str) -> tuple[bool, list[str]]:
    """Check if text uses only UGF vocabulary.

    Normalizes unicode before checking (smart quotes, fancy dashes, etc.).

    Returns:
        (is_valid, violations) where violations is a list of disallowed words.
    """
    text = normalize_unicode(text)
    return get_tokenizer().validate(text)


def build_correction_prompt(original_text: str, ugf_attempt: str, violations: list[str]) -> str:
    """Build a follow-up prompt asking the model to fix vocabulary violations."""
    violation_str = ", ".join(f'"{v}"' for v in violations[:20])
    if len(violations) > 20:
        violation_str += f" (and {len(violations) - 20} more)"

    return (
        f"Your translation contains words that are NOT in the allowed word list: "
        f"{violation_str}\n\n"
        f"Rewrite the translation using ONLY words from the allowed list. "
        f"Replace each disallowed word with a simple description using allowed words.\n\n"
        f"Original English text:\n{original_text}\n\n"
        f"Your previous attempt (with violations):\n{ugf_attempt}\n\n"
        f"Corrected Up Goer Five translation:"
    )
