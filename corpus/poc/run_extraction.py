"""Generic form-parameterized extraction runner for the corpus-diversification POC.

Reads parsed source-text pairs from a JSONL file, applies the per-form prompt
template (see forms.py), calls gpt-oss-120b via MindRouter, and saves the
resulting (UGF prompt, UGF response) pairs with per-call compliance details.

Usage:
    python3 corpus/poc/run_extraction.py \\
        --form dialogue \\
        --pairs corpus/poc/hume_pairs.jsonl \\
        --results corpus/poc/dialogue_hume_results.jsonl \\
        --failures corpus/poc/dialogue_hume_failures.jsonl \\
        --n 50

Supported forms (see forms.py): dialogue, objection_reply, skeptical_mode.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import aiohttp

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

ENV_FILE = ROOT / ".env"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

from corpus.generation.validate_ugf import validate_ugf, normalize_unicode
from corpus.generation.forms import FORMS, build_user_message, allowed_proper_nouns_for

MR_URL = "https://mindrouter.uidaho.edu/v1/chat/completions"
MR_KEY = os.environ.get("MINDROUTER_API_KEY", "")
MODEL = "openai/gpt-oss-120b"
REASONING_EFFORT = "medium"
# Generous budget: gpt-oss-120b consumes tokens for reasoning_content before
# emitting content. Longer source passages (Hume, Aquinas, Sextus) need more
# headroom than Meno did. v1's generate_reasoning.py uses ~10K for 120b.
MAX_TOKENS = 12288
TEMPERATURE = 0.7
MAX_CONCURRENT = 5
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0


async def call_mr(session: aiohttp.ClientSession, system_prompt: str, user_message: str,
                  sem: asyncio.Semaphore) -> dict:
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
        "reasoning_effort": REASONING_EFFORT,
    }
    headers = {
        "Authorization": f"Bearer {MR_KEY}",
        "Content-Type": "application/json",
    }
    last_err = None
    for attempt in range(MAX_RETRIES):
        async with sem:
            try:
                async with session.post(MR_URL, json=payload, headers=headers,
                                        timeout=aiohttp.ClientTimeout(total=360)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        content = data["choices"][0]["message"].get("content")
                        if content is None:
                            last_err = "content=null (thinking budget exhausted)"
                            await asyncio.sleep(RETRY_BACKOFF * (2 ** attempt))
                            continue
                        return {"ok": True, "content": content.strip()}
                    elif resp.status == 429:
                        await asyncio.sleep(RETRY_BACKOFF * (2 ** attempt) * 4)
                        last_err = f"429 (attempt {attempt+1})"
                    else:
                        body = (await resp.text())[:200]
                        last_err = f"HTTP {resp.status}: {body}"
                        await asyncio.sleep(RETRY_BACKOFF * (2 ** attempt))
            except asyncio.TimeoutError:
                last_err = "timeout"
                await asyncio.sleep(RETRY_BACKOFF * (2 ** attempt))
            except aiohttp.ClientError as e:
                last_err = f"{type(e).__name__}: {e}"
                await asyncio.sleep(RETRY_BACKOFF * (2 ** attempt))
    return {"ok": False, "error": last_err}


def split_violations(violations: list[str], allowed_pns: set[str]) -> tuple[list[str], list[str], list[str]]:
    """Split into (pn_allowed_by_rule, pn_other, lexical).
    pn_allowed_by_rule = capitalized words whose lowercase form is in allowed_pns
    pn_other = capitalized words NOT in allowed_pns
    lexical = lowercase (or genuine-vocabulary) violations
    """
    pn_ok, pn_other, lex = [], [], []
    for v in violations:
        if v and v[0].isupper():
            if v.lower() in allowed_pns:
                pn_ok.append(v)
            else:
                pn_other.append(v)
        else:
            lex.append(v)
    return pn_ok, pn_other, lex


def parse_and_validate(content: str, allowed_pns: set[str]) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = "\n".join(text.splitlines()[1:])
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3].rstrip()

    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        return {"json_ok": False, "error": f"JSONDecodeError: {e}", "raw": content[:300]}

    if not isinstance(obj, dict) or "prompt" not in obj or "response" not in obj:
        return {"json_ok": False, "error": "missing keys", "raw": content[:300]}

    p, r = obj["prompt"], obj["response"]
    if not (isinstance(p, str) and isinstance(r, str)):
        return {"json_ok": False, "error": "non-string values", "raw": content[:300]}

    p_norm, r_norm = normalize_unicode(p), normalize_unicode(r)
    p_ok, p_viol = validate_ugf(p_norm)
    r_ok, r_viol = validate_ugf(r_norm)

    p_pn_ok, p_pn_other, p_lex = split_violations(p_viol, allowed_pns)
    r_pn_ok, r_pn_other, r_lex = split_violations(r_viol, allowed_pns)

    p_adj_violations = p_lex + p_pn_other
    r_adj_violations = r_lex + r_pn_other
    p_adj_ok = len(p_adj_violations) == 0
    r_adj_ok = len(r_adj_violations) == 0

    return {
        "json_ok": True,
        "prompt": p_norm,
        "response": r_norm,
        "prompt_ugf_strict_ok": p_ok,
        "response_ugf_strict_ok": r_ok,
        "prompt_violations_strict": p_viol,
        "response_violations_strict": r_viol,
        "prompt_ugf_adj_ok": p_adj_ok,
        "response_ugf_adj_ok": r_adj_ok,
        "prompt_violations_adj": p_adj_violations,
        "response_violations_adj": r_adj_violations,
        "prompt_pn_allowed": p_pn_ok,
        "response_pn_allowed": r_pn_ok,
        "prompt_pn_other": p_pn_other,
        "response_pn_other": r_pn_other,
        "prompt_lexical_violations": p_lex,
        "response_lexical_violations": r_lex,
        "both_strict_ok": p_ok and r_ok,
        "both_adj_ok": p_adj_ok and r_adj_ok,
    }


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--form", required=True, choices=list(FORMS.keys()))
    ap.add_argument("--pairs", required=True, help="path to JSONL of source pairs")
    ap.add_argument("--results", required=True, help="path to write JSONL of extracted UGF pairs")
    ap.add_argument("--failures", required=True, help="path to write JSONL of failed calls")
    ap.add_argument("--n", type=int, default=50, help="number of pairs to process")
    ap.add_argument("--skip-first", type=int, default=0)
    ap.add_argument("--append", action="store_true")
    args = ap.parse_args()

    if not MR_KEY:
        print("ERROR: MINDROUTER_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    pairs_path = Path(args.pairs)
    results_path = Path(args.results)
    failures_path = Path(args.failures)

    pairs = [json.loads(l) for l in pairs_path.read_text().splitlines() if l.strip()]
    pairs = pairs[args.skip_first:args.skip_first + args.n]
    print(f"[{args.form}] Processing {len(pairs)} pairs (model={MODEL}@{REASONING_EFFORT}, concurrency={MAX_CONCURRENT})")

    spec = FORMS[args.form]
    system_prompt = spec["system_prompt"]

    mode = "a" if args.append else "w"
    results_f = results_path.open(mode, encoding="utf-8")
    failures_f = failures_path.open(mode, encoding="utf-8")

    sem = asyncio.Semaphore(MAX_CONCURRENT)
    t0 = time.monotonic()

    connector = aiohttp.TCPConnector(ssl=False, limit=0)
    async with aiohttp.ClientSession(connector=connector) as session:
        async def one(pair: dict) -> tuple[dict, dict]:
            user = build_user_message(args.form, pair)
            res = await call_mr(session, system_prompt, user, sem)
            return pair, res
        completed = await asyncio.gather(*[one(p) for p in pairs])

    n_call_ok = n_json_ok = n_both_strict = n_both_adj = n_p_adj = n_r_adj = 0
    n_lex_total = 0

    for pair, call_res in completed:
        rec = {"id": pair.get("id", "?")}
        rec.update({k: pair.get(k) for k in spec["input_keys"]})
        if not call_res.get("ok"):
            rec["status"] = "call_failed"
            rec["error"] = call_res.get("error")
            failures_f.write(json.dumps(rec) + "\n")
            continue
        n_call_ok += 1

        allowed_pns = allowed_proper_nouns_for(args.form, pair)
        parsed = parse_and_validate(call_res["content"], allowed_pns)
        if not parsed["json_ok"]:
            rec["status"] = "json_failed"
            rec["error"] = parsed["error"]
            rec["raw_content"] = parsed.get("raw")
            failures_f.write(json.dumps(rec) + "\n")
            continue

        n_json_ok += 1
        n_p_adj += int(parsed["prompt_ugf_adj_ok"])
        n_r_adj += int(parsed["response_ugf_adj_ok"])
        n_both_strict += int(parsed["both_strict_ok"])
        n_both_adj += int(parsed["both_adj_ok"])
        n_lex_total += (len(parsed["prompt_lexical_violations"])
                       + len(parsed["response_lexical_violations"]))

        rec["status"] = "ok"
        rec.update({k: parsed[k] for k in (
            "prompt", "response",
            "prompt_ugf_strict_ok", "response_ugf_strict_ok",
            "prompt_ugf_adj_ok", "response_ugf_adj_ok",
            "prompt_violations_strict", "response_violations_strict",
            "prompt_violations_adj", "response_violations_adj",
            "prompt_pn_allowed", "response_pn_allowed",
            "prompt_pn_other", "response_pn_other",
            "prompt_lexical_violations", "response_lexical_violations",
        )})
        results_f.write(json.dumps(rec) + "\n")

    results_f.close()
    failures_f.close()

    dt = time.monotonic() - t0
    n = len(pairs)
    print()
    print(f"=== {args.form} POC ({pairs_path.name}, n={n}, wall {dt:.1f}s) ===")
    print(f"  API call ok           : {n_call_ok}/{n} ({100*n_call_ok/n:.0f}%)")
    print(f"  JSON parse ok         : {n_json_ok}/{n} ({100*n_json_ok/n:.0f}%)")
    print(f"  Both UGF (strict)     : {n_both_strict}/{n} ({100*n_both_strict/n:.0f}%)")
    print(f"  Prompt UGF (adjusted) : {n_p_adj}/{n} ({100*n_p_adj/n:.0f}%)")
    print(f"  Response UGF (adjusted): {n_r_adj}/{n} ({100*n_r_adj/n:.0f}%)")
    print(f"  Both UGF (adjusted)   : {n_both_adj}/{n} ({100*n_both_adj/n:.0f}%)")
    print(f"  Mean lexical violations: {n_lex_total/max(n_json_ok,1):.2f} per call (excludes proper nouns)")
    print()
    print(f"  Results -> {results_path}")
    print(f"  Failures -> {failures_path}")


if __name__ == "__main__":
    asyncio.run(main())
