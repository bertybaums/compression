"""Dialogue-extraction POC: convert Plato's Meno (Jowett) into UGF (prompt, response)
pairs that preserve dialogic structure.

For each (turn_a, turn_b) consecutive-speaker pair, ask gpt-oss-120b (via
MindRouter) to rewrite both turns in UGF such that turn_a remains a specific
question/claim and turn_b remains a response that engages turn_a's specific
content. Save results to JSONL with per-call UGF compliance stats.

Usage:
    python3 corpus/poc/run_dialogue_poc.py --n 5    # 5-pair pilot
    python3 corpus/poc/run_dialogue_poc.py --n 50   # full POC
    python3 corpus/poc/run_dialogue_poc.py --n 50 --skip-first 5  # remaining 45

Outputs:
    corpus/poc/dialogue_meno_results.jsonl        (one record per call)
    corpus/poc/dialogue_meno_failures.jsonl       (calls that failed JSON parse / UGF check)
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

# Load .env (project root) -- pick up MINDROUTER_API_KEY
ENV_FILE = ROOT / ".env"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

from corpus.generation.validate_ugf import validate_ugf, normalize_unicode

MR_URL = "https://mindrouter.uidaho.edu/v1/chat/completions"
MR_KEY = os.environ.get("MINDROUTER_API_KEY", "")
MODEL = "openai/gpt-oss-120b"
REASONING_EFFORT = "medium"
MAX_TOKENS = 4096
TEMPERATURE = 0.7
MAX_CONCURRENT = 5
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0

PAIRS_PATH = Path(__file__).parent / "meno_pairs.jsonl"
RESULTS_PATH = Path(__file__).parent / "dialogue_meno_results.jsonl"
FAILURES_PATH = Path(__file__).parent / "dialogue_meno_failures.jsonl"

SYSTEM_PROMPT = """You rewrite passages of philosophical dialogue using ONLY the most common 1000 English words -- the "Up Goer Five" vocabulary. You preserve the dialogic relationship between two speakers exactly.

RULES:
1. Use ONLY words from the allowed 1000-word list. All grammatical forms of allowed words are permitted (if "think" is allowed, so are "thinks", "thinking", "thought").
2. The first speaker's turn must remain a specific question, claim, or move -- NOT a general topic phrase.
3. The second speaker's response must engage the specific content of the first turn -- NOT just the surrounding subject matter. Imagine the response failing to address the prompt: if the response would read fine as a generic essay, it is wrong.
4. KEEP the names of the speakers in the dialogue verbatim (e.g. "Socrates", "Meno", "Anytus", "Boy") -- these are names of people in the conversation and are allowed.
5. PARAPHRASE all other proper nouns (historical figures who are not speaking, place names, terms in foreign languages). For example: "Themistocles" -> "the great leader of long ago"; "Gorgias" -> "the famous teacher of speaking"; "Athens" -> "the city".
6. PARAPHRASE technical or philosophical terms. Examples: "virtue" -> "being good" or "the right way"; "essence" -> "what it really is"; "geometry" -> "how shapes work"; "Sophists" -> "the people who teach for money".
7. PARAPHRASE ordinary nouns that are not in the allowed list. Examples: "bees" -> "the little flying things that make sweet food"; "horses" -> "the big animals people ride"; "ruler" -> "the one who is in charge".
8. Numbers (0-9) and basic punctuation (. , ? ! : ; ' " - ( )) are allowed.
9. Do NOT use markdown. Do NOT include any commentary.

OUTPUT FORMAT: a single JSON object on one line with exactly two keys: "prompt" (the rewritten first turn) and "response" (the rewritten second turn). Nothing else."""

USER_TEMPLATE = """First speaker ({speaker_a}) says:
\"\"\"{turn_a}\"\"\"

Second speaker ({speaker_b}) responds:
\"\"\"{turn_b}\"\"\"

Rewrite both turns in Up Goer Five, preserving the dialogic relationship. Output a single JSON object with keys "prompt" and "response"."""


async def call_mr(session: aiohttp.ClientSession, pair: dict, sem: asyncio.Semaphore) -> dict:
    """Send a single dialogue-extraction call. Returns a result dict."""
    user = USER_TEMPLATE.format(
        speaker_a=pair["speaker_a"],
        turn_a=pair["turn_a"],
        speaker_b=pair["speaker_b"],
        turn_b=pair["turn_b"],
    )
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
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
                        return {"ok": True, "content": content.strip(), "raw": data}
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


# Dialogue speakers in Meno that are allowed verbatim by rule 4.
DIALOGUE_SPEAKERS = {"socrates", "meno", "anytus", "boy"}


def split_violations(violations: list[str]) -> tuple[list[str], list[str]]:
    """Split violations into (proper_noun_like, lexical).

    Proper-noun-like = starts with uppercase (i.e. capitalized in the output,
    suggesting the model treated it as a name). Lexical = everything else.
    """
    pn, lex = [], []
    for v in violations:
        if v and v[0].isupper():
            pn.append(v)
        else:
            lex.append(v)
    return pn, lex


def parse_and_validate(content: str) -> dict:
    """Parse JSON output and run UGF compliance check on prompt + response."""
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

    # Strict: as-is. Adjusted: strip dialogue-speaker names (allowed by rule 4)
    # and report PN-like vs lexical separately for measurement.
    p_pn, p_lex = split_violations(p_viol)
    r_pn, r_lex = split_violations(r_viol)
    # Names of *dialogue* speakers (allowed by rule 4) don't count even strictly,
    # by project convention. Names of historical figures (should-be-paraphrased) DO count
    # as lexical violations of rule 5.
    p_pn_speaker = [w for w in p_pn if w.lower() in DIALOGUE_SPEAKERS]
    p_pn_other = [w for w in p_pn if w.lower() not in DIALOGUE_SPEAKERS]
    r_pn_speaker = [w for w in r_pn if w.lower() in DIALOGUE_SPEAKERS]
    r_pn_other = [w for w in r_pn if w.lower() not in DIALOGUE_SPEAKERS]

    p_adj_violations = p_lex + p_pn_other  # excludes dialogue-speaker PNs
    r_adj_violations = r_lex + r_pn_other
    p_adj_ok = len(p_adj_violations) == 0
    r_adj_ok = len(r_adj_violations) == 0

    return {
        "json_ok": True,
        "prompt": p_norm,
        "response": r_norm,
        # Strict (original validator output)
        "prompt_ugf_strict_ok": p_ok,
        "response_ugf_strict_ok": r_ok,
        "prompt_violations_strict": p_viol,
        "response_violations_strict": r_viol,
        # Adjusted (dialogue-speaker PNs excluded)
        "prompt_ugf_adj_ok": p_adj_ok,
        "response_ugf_adj_ok": r_adj_ok,
        "prompt_violations_adj": p_adj_violations,
        "response_violations_adj": r_adj_violations,
        "prompt_pn_speaker": p_pn_speaker,
        "response_pn_speaker": r_pn_speaker,
        "prompt_pn_other": p_pn_other,
        "response_pn_other": r_pn_other,
        "prompt_lexical_violations": p_lex,
        "response_lexical_violations": r_lex,
        "both_strict_ok": p_ok and r_ok,
        "both_adj_ok": p_adj_ok and r_adj_ok,
    }


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5, help="number of pairs to process")
    ap.add_argument("--skip-first", type=int, default=0, help="skip first K pairs (resume)")
    ap.add_argument("--append", action="store_true", help="append to results file rather than overwrite")
    args = ap.parse_args()

    if not MR_KEY:
        print("ERROR: MINDROUTER_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    pairs = [json.loads(l) for l in PAIRS_PATH.read_text().splitlines() if l.strip()]
    pairs = pairs[args.skip_first:args.skip_first + args.n]
    print(f"Processing {len(pairs)} pairs (skip-first={args.skip_first}, model={MODEL}, effort={REASONING_EFFORT}, concurrency={MAX_CONCURRENT})")

    mode = "a" if args.append else "w"
    results_f = RESULTS_PATH.open(mode, encoding="utf-8")
    failures_f = FAILURES_PATH.open(mode, encoding="utf-8")

    sem = asyncio.Semaphore(MAX_CONCURRENT)
    t0 = time.monotonic()

    connector = aiohttp.TCPConnector(ssl=False, limit=0)  # MR uses self-signed cert
    async with aiohttp.ClientSession(connector=connector) as session:
        results = await asyncio.gather(*[call_mr(session, p, sem) for p in pairs])

    n_call_ok = sum(1 for r in results if r.get("ok"))
    n_json_ok = 0
    n_both_strict = 0
    n_both_adj = 0
    n_p_adj = 0
    n_r_adj = 0
    n_lex_total = 0  # total lexical (non-PN) violations across all calls

    for pair, call_res in zip(pairs, results):
        rec = {"id": pair["id"], "speaker_a": pair["speaker_a"], "speaker_b": pair["speaker_b"],
               "src_turn_a": pair["turn_a"], "src_turn_b": pair["turn_b"]}
        if not call_res.get("ok"):
            rec["status"] = "call_failed"
            rec["error"] = call_res.get("error")
            failures_f.write(json.dumps(rec) + "\n")
            continue

        parsed = parse_and_validate(call_res["content"])
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

        rec.update({"status": "ok"})
        rec.update({k: parsed[k] for k in (
            "prompt", "response",
            "prompt_ugf_strict_ok", "response_ugf_strict_ok",
            "prompt_ugf_adj_ok", "response_ugf_adj_ok",
            "prompt_violations_strict", "response_violations_strict",
            "prompt_violations_adj", "response_violations_adj",
            "prompt_pn_speaker", "response_pn_speaker",
            "prompt_pn_other", "response_pn_other",
            "prompt_lexical_violations", "response_lexical_violations",
        )})
        results_f.write(json.dumps(rec) + "\n")

    results_f.close()
    failures_f.close()

    dt = time.monotonic() - t0
    n = len(pairs)
    print()
    print(f"=== POC results (n={n}, wall time {dt:.1f}s, model={MODEL}@{REASONING_EFFORT}) ===")
    print(f"  API call ok               : {n_call_ok}/{n} ({100*n_call_ok/n:.0f}%)")
    print(f"  JSON parse ok             : {n_json_ok}/{n} ({100*n_json_ok/n:.0f}%)")
    print(f"  Both turns UGF (strict)   : {n_both_strict}/{n} ({100*n_both_strict/n:.0f}%)  [counts dialogue-speaker names as violations]")
    print(f"  Prompt UGF (adjusted)     : {n_p_adj}/{n} ({100*n_p_adj/n:.0f}%)")
    print(f"  Response UGF (adjusted)   : {n_r_adj}/{n} ({100*n_r_adj/n:.0f}%)")
    print(f"  Both turns UGF (adjusted) : {n_both_adj}/{n} ({100*n_both_adj/n:.0f}%)  [allows Socrates/Meno/Anytus/Boy by rule 4]")
    print(f"  Mean lexical violations   : {n_lex_total/max(n_json_ok,1):.2f} per call (excludes proper nouns)")
    print()
    print(f"  Results -> {RESULTS_PATH}")
    print(f"  Failures -> {FAILURES_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
