"""
RL-time judge: MR-based async client returning 4-dim rubric scores.

During RL training the judge is called per rollout (often 96 calls per
training step at the design's 8 rollouts × 4 prompts × 3 jurors). We use
MindRouter's `Nemotron-3-Super-120b` as the judge model rather than Claude
subagents because the SLURM training job cannot dispatch Agent calls.
Nemotron was selected (a) because it is NOT one of our teachers
(gpt-oss-120b, gemma-4-26b, qwen3.6-27b) — so no teacher-judge
contamination — and (b) because an 8-item calibration probe (May 19)
showed tight alignment with Claude subagent scores on the heavily-weighted
dims (mean abs diff: engagement 0.29, substance 0.43; the 0.1-weight
expressive_adequacy disagrees most at 1.14 but in a benign direction —
Nemotron is stricter).

The judge prompt restates the Reasoner rubric and asks for a single JSON
object with 4-dim scores plus brief justifications.

Jury voting: call the judge N times in parallel and average the per-dim
scores. The jury reduces noise in the per-rollout reward signal, which
matters for GRPO advantage normalization (high judge variance inflates
advantage magnitudes and destabilizes training).
"""

import asyncio
import json
import ssl
import time
from pathlib import Path
from typing import Any

import aiohttp

DIMS = ("engagement", "coherence", "substance", "expressive_adequacy")

JUDGE_SYSTEM_PROMPT = """You are scoring a short response written in a restricted vocabulary (Up Goer Five — about 1,000 common English words). Score on merit. Be honest. Give 0 freely when the response does not address the prompt.

Rubric (each dimension is 0/1/2/3/4, anchored at 0, 2, 4 — interpolate 1 and 3):

D1 Engagement: 0=wanders/restates prompt only; 2=touches the question but misses central ask; 4=engages the prompt's central question directly.

D2 Coherence: 0=self-contradictory or fragmented; 2=mostly readable but with gaps or sloppy steps; 4=each move follows the prior; no contradictions.

D3 Substance: 0=mere restatement or truisms; 2=identifies a relevant case/distinction/move but does not push it; 4=develops a counterexample, traces an analogy, or surfaces a non-obvious distinction.

D4 Expressive adequacy: 0=restriction breaks the argument (circumlocutions obscure the point); 2=clunky but point is recoverable; 4=UGF feels native.

Reply with ONLY a single JSON object, no markdown, no commentary. Exactly:
{"engagement":{"score":<int 0-4>,"justification":"<1 sentence>"},"coherence":{"score":<int>,"justification":"<1 sentence>"},"substance":{"score":<int>,"justification":"<1 sentence>"},"expressive_adequacy":{"score":<int>,"justification":"<1 sentence>"}}
"""


def _build_user_message(prompt: str, response: str) -> str:
    return f"PROMPT:\n{prompt}\n\nRESPONSE:\n{response}\n\nReturn ONLY the JSON object."


class MRJudge:
    """Async MR judge client with jury voting and a shared rate-limiter handle.

    `rate_bucket` is an AsyncTokenBucket instance (corpus/generation/rate_limiter.py).
    Each judge call acquires one token before firing — keeps us under MR's 200 rpm cap.
    """

    def __init__(
        self,
        api_url: str,
        api_key: str,
        rate_bucket,
        model: str = "Nemotron-3-Super-120b",
        jury_size: int = 3,
        max_tokens: int = 1500,
        reasoning_effort: str | None = None,  # Nemotron does not use this
        request_timeout: float = 60.0,
        max_retries: int = 3,
    ):
        self.api_url = api_url
        self.api_key = api_key
        self.rate_bucket = rate_bucket
        self.model = model
        self.jury_size = jury_size
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort
        self.request_timeout = request_timeout
        self.max_retries = max_retries
        self._ssl = ssl.create_default_context()
        self._ssl.check_hostname = False
        self._ssl.verify_mode = ssl.CERT_NONE

    async def _single_judge_call(
        self, session: aiohttp.ClientSession, prompt: str, response: str
    ) -> dict[str, Any] | None:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_message(prompt, response)},
            ],
            "max_tokens": self.max_tokens,
            "temperature": 0.4,
        }
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        for attempt in range(self.max_retries):
            await self.rate_bucket.acquire()
            try:
                async with session.post(
                    self.api_url,
                    json=payload,
                    headers=headers,
                    ssl=self._ssl,
                    timeout=aiohttp.ClientTimeout(total=self.request_timeout),
                ) as resp:
                    if resp.status == 200:
                        body = await resp.json()
                        content = (
                            (body.get("choices") or [{}])[0]
                            .get("message", {})
                            .get("content")
                        )
                        # Empty content (filter / truncation / etc.) returns
                        # None here; the jury aggregator drops failed jurors
                        # and proceeds with the remaining ones.
                        return _parse_judge_json(content)
                    if resp.status in (422, 429, 500, 502, 503, 504):
                        await asyncio.sleep(2 ** attempt)
                        continue
                    return None
            except (aiohttp.ClientError, asyncio.TimeoutError):
                await asyncio.sleep(2 ** attempt)
                continue
        return None

    async def score(
        self, session: aiohttp.ClientSession, prompt: str, response: str
    ) -> dict[str, float] | None:
        """Score one (prompt, response) pair via jury voting.

        Returns a dict with per-dim mean scores in [0, 4], plus a `_n_valid`
        field indicating how many jurors returned parseable JSON. None if
        fewer than 2 jurors returned valid scores (call rejected as too noisy).
        """
        results = await asyncio.gather(
            *[self._single_judge_call(session, prompt, response) for _ in range(self.jury_size)]
        )
        valid = [r for r in results if r is not None]
        if len(valid) < 2:
            return None
        out: dict[str, float] = {}
        for dim in DIMS:
            scores = [r[dim] for r in valid if dim in r]
            if not scores:
                return None
            out[dim] = sum(scores) / len(scores)
        out["_n_valid"] = float(len(valid))
        return out


def _parse_judge_json(content: str | None) -> dict[str, int] | None:
    """Pull the JSON object out of the judge's reply and return {dim: int}."""
    if not content:
        return None
    content = content.strip()
    # Strip optional code fences.
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
    # Find the first {...} block.
    start = content.find("{")
    end = content.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(content[start : end + 1])
    except json.JSONDecodeError:
        return None
    out: dict[str, int] = {}
    for dim in DIMS:
        entry = obj.get(dim)
        if not isinstance(entry, dict):
            return None
        score = entry.get("score")
        if not isinstance(score, (int, float)):
            return None
        si = int(score)
        if si < 0 or si > 4:
            return None
        out[dim] = si
    return out
