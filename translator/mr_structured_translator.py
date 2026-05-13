"""
MR-based EN→UGF translator using gpt-oss-120b + short prompt + JSON output +
post-hoc UGF validation + retry-on-violations.

This is the "path-1" translator from the May 13 decision: hard regex
constraint via MR's json_schema pattern silently failed for the full
3,616-word UGF vocab, so we get UGF compliance the same way the corpus
generators do — prompt instruction + validator + retry — but with a strong
base model instead of a trained T5.

Single-call (non-async) — used for the 115-item logic-textbook bench and
ad-hoc translation. For high-volume parallel translation use a producer-
consumer runner instead.
"""

import json
import os
import re
import ssl
import sys
import time
import urllib.request
from pathlib import Path

import yaml
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

from corpus.generation.validate_ugf import validate_ugf

CONFIG_PATH = Path(__file__).parent.parent / "corpus" / "generation" / "config.yaml"
with open(CONFIG_PATH) as f:
    CONFIG = yaml.safe_load(f)

load_dotenv(Path(__file__).parent.parent / ".env")

MINDROUTER_BASE_URL = CONFIG["mindrouter"]["base_url"]
MINDROUTER_API_KEY = os.environ.get("MINDROUTER_API_KEY", "")

DEFAULT_MODEL = "openai/gpt-oss-120b"
DEFAULT_MAX_RETRIES = 3


SYSTEM_PROMPT = """You rewrite English sentences using ONLY the most common 1000 English words — the "Up Goer Five" vocabulary.

RULES:
1. Use ONLY words from the Up Goer Five list. All grammatical forms of allowed words are permitted.
2. When a concept has no direct simple word, DESCRIBE it using only allowed words. Examples: "alligator" -> "the long animal with sharp teeth that lives in water"; "modus tollens" -> "the way of taking back from a result that did not happen"; "reptile" -> "the kind of animal with scales that is cold to the touch".
3. DISTINGUISH similar concepts. Do not collapse "alligator" and "crocodile" into the same paraphrase — find words that pick out one from the other (e.g. by where they live, what their face looks like).
4. Preserve the meaning of the input exactly. Do not add information that was not in the input. Do not invent names or examples.
5. Do NOT use proper nouns (names of people, places, organizations). If a proper noun appears in the input, describe it ("the famous teacher of long ago"; "the great city").
6. Numbers and basic punctuation (. , ; : ! ? - ' " ( )) are allowed.
7. Do NOT add commentary, prefixes like "Translation:", or extra prose.

OUTPUT FORMAT: a single JSON object on one line with one key "translation". Nothing else."""


USER_TEMPLATE = "Rewrite this in Up Goer Five:\n\n{english}"


def _http_post(url: str, payload: dict, headers: dict, timeout: int = 120) -> dict:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
        return json.loads(resp.read())


def _try_parse_translation(raw: str) -> str:
    """Pull `translation` out of a JSON response. Tolerate code fences and
    incidental prose around the JSON."""
    candidate = raw.strip()
    if candidate.startswith("```"):
        lines = candidate.split("\n")
        candidate = "\n".join(l for l in lines if not l.strip().startswith("```"))
    try:
        obj = json.loads(candidate)
        if isinstance(obj, dict) and "translation" in obj:
            return str(obj["translation"]).strip()
    except json.JSONDecodeError:
        pass
    # Fall back: find first {...} block
    m = re.search(r"\{[\s\S]*\}", candidate)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict) and "translation" in obj:
                return str(obj["translation"]).strip()
        except json.JSONDecodeError:
            pass
    # Last resort: return the raw text
    return candidate


def translate(
    english: str,
    model: str = DEFAULT_MODEL,
    max_retries: int = DEFAULT_MAX_RETRIES,
    reasoning_effort: str = "low",
    max_tokens: int = 2000,
) -> dict:
    """Translate an English string to UGF. Retries up to max_retries times on
    UGF-compliance violations, with the violating words called out in the
    correction message.

    Returns:
        {
          "translation": str,        # the UGF text
          "compliant": bool,
          "violations": list[str],   # final remaining (may be empty)
          "attempts": int,
          "latency_s": float,
        }
    """
    if not MINDROUTER_API_KEY:
        raise SystemExit("MINDROUTER_API_KEY not set")
    url = f"{MINDROUTER_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {MINDROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": USER_TEMPLATE.format(english=english)},
    ]
    t0 = time.time()
    translation = ""
    compliant = False
    violations: list[str] = []
    attempts = 0

    for attempt in range(max_retries):
        attempts += 1
        payload = {
            "model": model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "max_tokens": max_tokens,
            "reasoning_effort": reasoning_effort,
            "temperature": 0.3,
        }
        body = _http_post(url, payload, headers)
        content = (body.get("choices") or [{}])[0].get("message", {}).get("content", "")
        if not content:
            # Thinking-budget exhaustion or empty content — bump max_tokens and retry
            max_tokens = int(max_tokens * 1.5)
            continue
        translation = _try_parse_translation(content)
        compliant, violations = validate_ugf(translation)
        if compliant:
            break
        # Build correction
        messages.append({"role": "assistant", "content": content})
        messages.append({
            "role": "user",
            "content": (
                f"Your output contains words not in the allowed list: "
                f"{', '.join(repr(v) for v in violations[:15])}. "
                f"Rewrite the JSON object, replacing each disallowed word with a "
                f"description that uses only allowed words. Output exactly one "
                f"JSON object on a single line with one key 'translation'."
            ),
        })

    return {
        "translation": translation,
        "compliant": compliant,
        "violations": violations,
        "attempts": attempts,
        "latency_s": round(time.time() - t0, 2),
    }


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", default="Alligators are on average larger than crocodiles.")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()
    r = translate(args.text, model=args.model)
    print(json.dumps(r, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
