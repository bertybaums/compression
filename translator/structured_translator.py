"""
Structured-output English -> UGF Translator.

Uses a strong base model with hard logit-mask constraint to the UGF vocabulary.
No training: the base model's general paraphrase competence handles the
semantics; the mask enforces lexical compliance at every decoding step.

The hypothesis under test: a short prompt + hard constraint produces better
EN->UGF translations than our trained T5 with long prompt and soft constraint.
"""

import json
from pathlib import Path
from typing import Optional

import torch
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    LogitsProcessor,
    PreTrainedTokenizerBase,
)

DEFAULT_VOCAB_PATH = Path(__file__).parent.parent / "wordlist" / "vocab_final.json"

DEFAULT_PROMPT_TEMPLATE = (
    "Rewrite the following text using only the simplest, most common English "
    "words. Preserve the meaning.\n\n{text}"
)


class UGFLogitsProcessor(LogitsProcessor):
    """Hard UGF constraint, generalized to any HF tokenizer.

    Same word-level mask strategy as translator.model.StateMachineLogitsProcessor,
    but accepts any tokenizer (not just T5) and lets callers pass extra allowed
    token ids (e.g. chat-template end-of-turn tokens) so the model can still
    terminate its response.
    """

    def __init__(
        self,
        tokenizer: PreTrainedTokenizerBase,
        ugf_vocab_path: Optional[Path] = None,
        extra_allowed_token_ids: Optional[list[int]] = None,
        capitalize_variants: bool = True,
    ):
        self.tokenizer = tokenizer
        ugf_vocab_path = ugf_vocab_path or DEFAULT_VOCAB_PATH

        with open(ugf_vocab_path) as f:
            ugf_vocab = json.load(f)

        self.ugf_words: set[str] = {
            tok for tok in ugf_vocab if tok and not tok.startswith("<")
        }

        self.allowed_token_ids: set[int] = set()

        for special_id in [
            tokenizer.eos_token_id,
            tokenizer.bos_token_id,
            tokenizer.pad_token_id,
        ]:
            if special_id is not None:
                self.allowed_token_ids.add(special_id)

        for word in self.ugf_words:
            forms = [word, f" {word}"]
            if capitalize_variants:
                forms += [word.capitalize(), f" {word.capitalize()}"]
            for text in forms:
                ids = tokenizer.encode(text, add_special_tokens=False)
                self.allowed_token_ids.update(ids)

        for punct in [
            ".", ",", "!", "?", ";", ":", "-", "'", '"', "(", ")",
            " ", "\n", "  ", "\n\n",
        ]:
            ids = tokenizer.encode(punct, add_special_tokens=False)
            self.allowed_token_ids.update(ids)

        for d in "0123456789":
            ids = tokenizer.encode(d, add_special_tokens=False)
            self.allowed_token_ids.update(ids)

        if extra_allowed_token_ids:
            self.allowed_token_ids.update(extra_allowed_token_ids)

        self.allowed_token_ids = sorted(self.allowed_token_ids)
        self._mask: Optional[torch.Tensor] = None
        self._mask_device: Optional[torch.device] = None

    def _get_mask(self, vocab_size: int, device: torch.device) -> torch.Tensor:
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


# Special tokens that, depending on the model, end an assistant turn. We allow
# any that the tokenizer actually knows about so the model can stop.
TURN_END_TOKEN_CANDIDATES = [
    "<|im_end|>",
    "<|return|>",
    "<|endoftext|>",
    "<|end|>",
    "<|eot_id|>",
    "<|end_of_turn|>",
]


def _resolve_turn_end_token_ids(tokenizer: PreTrainedTokenizerBase) -> list[int]:
    """Return token ids for any chat-format end-of-turn tokens this tokenizer knows."""
    found: list[int] = []
    unk = tokenizer.unk_token_id
    for name in TURN_END_TOKEN_CANDIDATES:
        try:
            tid = tokenizer.convert_tokens_to_ids(name)
        except Exception:
            tid = None
        if tid is None or tid == unk:
            continue
        found.append(tid)
    return found


class StructuredTranslator:
    """English -> UGF using a strong base model + hard UGF mask.

    Default base: openai/gpt-oss-20b. Any HF causal LM works.
    """

    def __init__(
        self,
        model_name_or_path: str = "openai/gpt-oss-20b",
        ugf_vocab_path: Optional[Path] = None,
        device_map: str = "auto",
        torch_dtype: torch.dtype = torch.bfloat16,
    ):
        self.model_name = model_name_or_path
        self.tokenizer = AutoTokenizer.from_pretrained(model_name_or_path)
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name_or_path,
            torch_dtype=torch_dtype,
            device_map=device_map,
        )
        self.model.eval()

        extra_allowed = _resolve_turn_end_token_ids(self.tokenizer)

        self.ugf_processor = UGFLogitsProcessor(
            self.tokenizer,
            ugf_vocab_path=ugf_vocab_path,
            extra_allowed_token_ids=extra_allowed,
        )

    def _build_prompt(self, user_msg: str) -> str:
        if getattr(self.tokenizer, "chat_template", None):
            return self.tokenizer.apply_chat_template(
                [{"role": "user", "content": user_msg}],
                tokenize=False,
                add_generation_prompt=True,
            )
        return user_msg + "\n\n"

    def to_ugf(
        self,
        english_text: str,
        prompt_template: str = DEFAULT_PROMPT_TEMPLATE,
        max_new_tokens: int = 300,
        temperature: float = 0.7,
        do_sample: bool = True,
    ) -> str:
        user_msg = prompt_template.format(text=english_text)
        prompt = self._build_prompt(user_msg)

        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)

        with torch.inference_mode():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=do_sample,
                temperature=temperature,
                logits_processor=[self.ugf_processor],
                pad_token_id=self.tokenizer.pad_token_id or self.tokenizer.eos_token_id,
            )

        completion_ids = outputs[0, inputs["input_ids"].shape[1]:]
        return self.tokenizer.decode(completion_ids, skip_special_tokens=True).strip()


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="openai/gpt-oss-20b")
    parser.add_argument(
        "--text",
        default="Alligators are on average larger than crocodiles.",
    )
    args = parser.parse_args()

    print(f"Loading {args.model}...")
    translator = StructuredTranslator(model_name_or_path=args.model)
    print(f"Allowed token count: {len(translator.ugf_processor.allowed_token_ids)}")
    print(f"\nInput:  {args.text}")
    print(f"Output: {translator.to_ugf(args.text)}")


if __name__ == "__main__":
    main()
