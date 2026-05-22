"""
RL reward function for the v2 Reasoner.

Computes a scalar reward in [0, 1] for a single rollout, given the prompt
that produced it and a judge instance. The reward is the weighted sum of
four rubric dimensions normalized to [0, 1]:

    reward = 0.6 * substance + 0.2 * engagement + 0.1 * coherence + 0.1 * expressive_adequacy

But ONLY if the rollout passes four structural gates:
    1. UGF vocab compliance (validate_ugf)
    2. parse_ok (extract_answer finds the "So my answer is:" marker exactly once)
    3. no doom-loop (no 4-gram repeated 3+ times consecutively)
    4. answer length >= MIN_ANSWER_WORDS (default 5 words)

Failures get reward 0. Following the Numerals project's zero-gradient-trap
lesson, we use {0, +1} not {-1, +1} — never negative reward, so increasing
the rate of valid rollouts is always positively rewarded.

The doom-loop n-gram gate and the answer-length floor were added after the
SFT v2 milestone surfaced (a) Labonne-style doom-looping in some rollouts
and (b) v2's tendency to produce very short answers when judged
in isolation. See docs/rl-design-2026-05-18.md and the spot-check finding
in the May 19 conversation.
"""

import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from corpus.generation.validate_ugf import validate_ugf
from eval.parse_v2_answer import extract_answer

# Locked reward weights (May 16 target probe + May 18 RL design).
W_SUBSTANCE = 0.6
W_ENGAGEMENT = 0.2
W_COHERENCE = 0.1
W_EXPRESSIVE_ADEQUACY = 0.1

# Doom-loop gate parameters (Labonne / tlm-playbook 5_preference.md).
DOOM_NGRAM = 4
DOOM_THRESHOLD = 3  # 4-gram repeated >= 3 times -> reward 0

# Answer-length floor. Set to 3 so single-clause logic answers like
# "The case follows." pass; the judge handles substance-vs-brevity directly.
# The gate is here only to prevent degenerate empty / 1-word answers.
MIN_ANSWER_WORDS = 3

REWARD_SCALE = 4.0  # judge scores are in [0, 4]; we divide to land in [0, 1]


@dataclass
class RewardOutcome:
    reward: float
    reason: str            # "ok" or one of the failure modes
    parse_ok: bool
    vocab_ok: bool
    no_doom_loop: bool
    answer_long_enough: bool
    answer_text: str | None
    judge_scores: dict[str, float] | None  # per-dim means in [0, 4] from jury
    judge_n_valid: int | None              # how many jurors returned valid JSON


def has_doom_loop(text: str, n: int = DOOM_NGRAM, threshold: int = DOOM_THRESHOLD) -> bool:
    """True if any token n-gram appears >= threshold times consecutively.

    Cheap surface-level rule (token = whitespace-split word). Catches the
    Labonne-style "X X X X X" loops that the SFT v2 step-20K samples
    exhibited on some OOD prompts. Does NOT catch paraphrased / semantic
    repetition — that's the judge's job (and why we still run a judge).
    """
    tokens = text.split()
    if len(tokens) < n * threshold:
        return False
    # Slide along, look for any n-gram with >= threshold consecutive repeats.
    for i in range(len(tokens) - n * threshold + 1):
        ngram = tuple(tokens[i : i + n])
        # Count consecutive repeats starting at i.
        k = 1
        j = i + n
        while j + n <= len(tokens) and tuple(tokens[j : j + n]) == ngram:
            k += 1
            j += n
            if k >= threshold:
                return True
    return False


def compute_reward(rollout_text: str, judge_scores: dict[str, float] | None = None,
                   judge_n_valid: int | None = None) -> RewardOutcome:
    """Apply structural gates and (if judge_scores supplied) compute weighted reward.

    Args:
        rollout_text: the model's raw UGF output (after the prompt; the
            full continuation including the marker and any reasoning).
        judge_scores: optional dict with per-dim scores in [0, 4]. If None,
            the gates are checked but no reward is computed (returns 0).
            Callers should obtain scores from `MRJudge.score(...)` and pass
            them in here.

    Returns:
        RewardOutcome with the reward, the reason, and diagnostic flags.
    """
    # Gate 1: UGF vocab compliance.
    vocab_ok, _violations = validate_ugf(rollout_text)
    # Gate 2: parse_ok (exactly one "So my answer is:" marker, non-empty answer).
    parsed = extract_answer(rollout_text)
    parse_ok = parsed["parse_ok"]
    answer = parsed.get("answer") or ""
    # Gate 3: no doom-loop in the rollout.
    no_doom = not has_doom_loop(rollout_text)
    # Gate 4: answer length floor.
    long_enough = len(answer.split()) >= MIN_ANSWER_WORDS

    if not vocab_ok:
        return RewardOutcome(0.0, "vocab_fail", parse_ok, False, no_doom, long_enough, answer, None, None)
    if not parse_ok:
        return RewardOutcome(0.0, "parse_fail", False, True, no_doom, long_enough, None, None, None)
    if not no_doom:
        return RewardOutcome(0.0, "doom_loop", parse_ok, True, False, long_enough, answer, None, None)
    if not long_enough:
        return RewardOutcome(0.0, "answer_too_short", parse_ok, True, True, False, answer, None, None)

    if judge_scores is None:
        # All gates passed but no judge scores supplied. Caller should now
        # request judge scores for the answer and call us again. Return 0
        # so the rollout doesn't accidentally get a positive reward without
        # a judge call.
        return RewardOutcome(0.0, "judge_pending", True, True, True, True, answer, None, None)

    score = (
        W_SUBSTANCE * judge_scores.get("substance", 0)
        + W_ENGAGEMENT * judge_scores.get("engagement", 0)
        + W_COHERENCE * judge_scores.get("coherence", 0)
        + W_EXPRESSIVE_ADEQUACY * judge_scores.get("expressive_adequacy", 0)
    ) / REWARD_SCALE  # land in [0, 1]
    return RewardOutcome(
        round(score, 4), "ok", True, True, True, True, answer, judge_scores, judge_n_valid
    )


def reward_diagnostics(outcomes: list[RewardOutcome]) -> dict:
    """Aggregate diagnostics over a batch of rollouts."""
    n = len(outcomes)
    if n == 0:
        return {"n": 0}
    by_reason = Counter(o.reason for o in outcomes)
    rewards = [o.reward for o in outcomes]
    ok_rewards = [o.reward for o in outcomes if o.reason == "ok"]
    return {
        "n": n,
        "reward_mean": round(sum(rewards) / n, 4),
        "reward_ok_mean": round(sum(ok_rewards) / len(ok_rewards), 4) if ok_rewards else 0.0,
        "reward_max": round(max(rewards), 4),
        "rate_ok": round(by_reason.get("ok", 0) / n, 4),
        "rate_vocab_fail": round(by_reason.get("vocab_fail", 0) / n, 4),
        "rate_parse_fail": round(by_reason.get("parse_fail", 0) / n, 4),
        "rate_doom_loop": round(by_reason.get("doom_loop", 0) / n, 4),
        "rate_answer_too_short": round(by_reason.get("answer_too_short", 0) / n, 4),
    }
