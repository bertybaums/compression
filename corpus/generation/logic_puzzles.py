"""
Synthetic logic-puzzle generator with verifiable answers.

Produces tuples of (premises, conclusion, is_valid, rule, scenario) where:
- premises: list of English statements
- conclusion: English statement
- is_valid: ground-truth validity (bool)
- rule: name of the inference pattern used (modus_tollens, denying_antecedent, ...)
- scenario: the natural-language scenario this puzzle is built from

The puzzles cover the canonical propositional-logic patterns that intro logic
textbooks teach. Each is constructed by plugging a (antecedent, consequent)
scenario seed into a fixed template, so the truth value is determined by the
template (not by the model's reasoning).

This module is the ground-truth source for:
- Generating prompts for the CoT corpus
- Rejection-sampling: keeping only teacher CoT traces whose final verdict
  matches the template's known truth
- Verifier-based reward during the eventual RL stage

No external dependencies; deterministic given a seed.
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Puzzle:
    id: str
    rule: str
    is_valid: bool
    premises: list[str]
    conclusion: str
    scenario: dict  # raw seed pieces for traceability
    natural_prompt: str  # combined English statement


# ---------------------------------------------------------------------------
# Scenario seeds
# ---------------------------------------------------------------------------
# Each seed is a (P, Q) pair where "If P then Q" is a natural conditional in
# everyday English. The puzzle generator builds inference patterns from these.
#
# Seeds are kept deliberately mundane so the puzzles test logical structure
# rather than empirical knowledge. None of these seeds requires looking up
# facts to evaluate.

CONDITIONAL_SEEDS: list[dict] = [
    {"p": "it is raining", "q": "the ground is wet",
     "not_p": "it is not raining", "not_q": "the ground is not wet"},
    {"p": "she studies for the test", "q": "she passes the test",
     "not_p": "she does not study for the test", "not_q": "she does not pass the test"},
    {"p": "the door is unlocked", "q": "the door can be opened from outside",
     "not_p": "the door is locked", "not_q": "the door cannot be opened from outside"},
    {"p": "he turns on the light", "q": "the room is bright",
     "not_p": "he does not turn on the light", "not_q": "the room is not bright"},
    {"p": "the cat is in the kitchen", "q": "the cat can hear the can opener",
     "not_p": "the cat is not in the kitchen", "not_q": "the cat cannot hear the can opener"},
    {"p": "she takes the medicine", "q": "her headache goes away",
     "not_p": "she does not take the medicine", "not_q": "her headache does not go away"},
    {"p": "the bird is a robin", "q": "the bird has feathers",
     "not_p": "the bird is not a robin", "not_q": "the bird does not have feathers"},
    {"p": "the meeting starts at noon", "q": "everyone arrives before noon",
     "not_p": "the meeting does not start at noon", "not_q": "not everyone arrives before noon"},
    {"p": "the bread has risen", "q": "the yeast was alive",
     "not_p": "the bread has not risen", "not_q": "the yeast was not alive"},
    {"p": "the road is icy", "q": "driving is dangerous",
     "not_p": "the road is not icy", "not_q": "driving is not dangerous"},
    {"p": "the engine has fuel", "q": "the car can move",
     "not_p": "the engine has no fuel", "not_q": "the car cannot move"},
    {"p": "the seed gets water", "q": "the seed grows",
     "not_p": "the seed does not get water", "not_q": "the seed does not grow"},
    {"p": "the alarm rang", "q": "she woke up",
     "not_p": "the alarm did not ring", "not_q": "she did not wake up"},
    {"p": "the bridge is open", "q": "traffic can cross the river",
     "not_p": "the bridge is closed", "not_q": "traffic cannot cross the river"},
    {"p": "the team practiced all week", "q": "the team plays well on Saturday",
     "not_p": "the team did not practice all week", "not_q": "the team does not play well on Saturday"},
    {"p": "the fire has fuel", "q": "the fire keeps burning",
     "not_p": "the fire has no fuel", "not_q": "the fire goes out"},
    {"p": "the soup has salt", "q": "the soup tastes savory",
     "not_p": "the soup has no salt", "not_q": "the soup tastes bland"},
    {"p": "the river is high", "q": "the bank is flooded",
     "not_p": "the river is low", "not_q": "the bank is dry"},
    {"p": "the candidate wins the vote", "q": "the candidate takes office",
     "not_p": "the candidate loses the vote", "not_q": "the candidate does not take office"},
    {"p": "the book is on the shelf", "q": "she can borrow the book",
     "not_p": "the book is not on the shelf", "not_q": "she cannot borrow the book"},
]


DISJUNCTION_SEEDS: list[dict] = [
    {"p": "she will take the train", "q": "she will take the bus",
     "not_p": "she will not take the train", "not_q": "she will not take the bus"},
    {"p": "the package arrives today", "q": "the package arrives tomorrow",
     "not_p": "the package does not arrive today", "not_q": "the package does not arrive tomorrow"},
    {"p": "the answer is yes", "q": "the answer is no",
     "not_p": "the answer is not yes", "not_q": "the answer is not no"},
    {"p": "the cake is chocolate", "q": "the cake is vanilla",
     "not_p": "the cake is not chocolate", "not_q": "the cake is not vanilla"},
    {"p": "the visitor is from the north", "q": "the visitor is from the south",
     "not_p": "the visitor is not from the north", "not_q": "the visitor is not from the south"},
    {"p": "the suspect was at home", "q": "the suspect was at work",
     "not_p": "the suspect was not at home", "not_q": "the suspect was not at work"},
    {"p": "the door is open", "q": "the door is locked",
     "not_p": "the door is not open", "not_q": "the door is not locked"},
    {"p": "the runner finished first", "q": "the runner finished second",
     "not_p": "the runner did not finish first", "not_q": "the runner did not finish second"},
]


# ---------------------------------------------------------------------------
# Inference patterns
# ---------------------------------------------------------------------------

def modus_ponens(seed: dict) -> tuple[list[str], str, bool]:
    """If P then Q. P. ∴ Q. — VALID"""
    return ([f"If {seed['p']}, then {seed['q']}.", f"{seed['p'].capitalize()}."],
            f"{seed['q'].capitalize()}.", True)


def modus_tollens(seed: dict) -> tuple[list[str], str, bool]:
    """If P then Q. ¬Q. ∴ ¬P. — VALID"""
    return ([f"If {seed['p']}, then {seed['q']}.", f"{seed['not_q'].capitalize()}."],
            f"{seed['not_p'].capitalize()}.", True)


def denying_antecedent(seed: dict) -> tuple[list[str], str, bool]:
    """If P then Q. ¬P. ∴ ¬Q. — INVALID (formal fallacy)"""
    return ([f"If {seed['p']}, then {seed['q']}.", f"{seed['not_p'].capitalize()}."],
            f"{seed['not_q'].capitalize()}.", False)


def affirming_consequent(seed: dict) -> tuple[list[str], str, bool]:
    """If P then Q. Q. ∴ P. — INVALID (formal fallacy)"""
    return ([f"If {seed['p']}, then {seed['q']}.", f"{seed['q'].capitalize()}."],
            f"{seed['p'].capitalize()}.", False)


def hypothetical_syllogism(seed_a: dict, seed_b: dict) -> tuple[list[str], str, bool]:
    """If P then Q. If Q then R. ∴ If P then R. — VALID (transitive)

    We use seed_a's q as seed_b's p — i.e. compose two seeds. Caller is
    responsible for picking seeds where the composition is coherent.
    """
    return (
        [f"If {seed_a['p']}, then {seed_a['q']}.",
         f"If {seed_a['q']}, then {seed_b['q']}."],
        f"If {seed_a['p']}, then {seed_b['q']}.",
        True,
    )


def disjunctive_syllogism(seed: dict) -> tuple[list[str], str, bool]:
    """P ∨ Q. ¬P. ∴ Q. — VALID"""
    return ([f"Either {seed['p']} or {seed['q']}.", f"{seed['not_p'].capitalize()}."],
            f"{seed['q'].capitalize()}.", True)


def affirming_disjunct_inclusive(seed: dict) -> tuple[list[str], str, bool]:
    """P ∨ Q. P. ∴ ¬Q. — INVALID under inclusive-or (formal fallacy)

    English 'or' is ambiguous between inclusive and exclusive. We label this
    invalid because intro logic textbooks treat 'or' as inclusive by default
    and the inference from P to ¬Q does not go through.
    """
    return ([f"Either {seed['p']} or {seed['q']}.", f"{seed['p'].capitalize()}."],
            f"{seed['not_q'].capitalize()}.", False)


# ---------------------------------------------------------------------------
# Top-level generator
# ---------------------------------------------------------------------------

RULES: dict[str, tuple] = {
    "modus_ponens":           ("conditional", modus_ponens),
    "modus_tollens":          ("conditional", modus_tollens),
    "denying_antecedent":     ("conditional", denying_antecedent),
    "affirming_consequent":   ("conditional", affirming_consequent),
    "disjunctive_syllogism":  ("disjunction", disjunctive_syllogism),
    "affirming_disjunct":     ("disjunction", affirming_disjunct_inclusive),
}


def generate(n: int, seed: int = 42, include_hypothetical: bool = True) -> list[Puzzle]:
    """Generate n puzzles drawn uniformly over the rule set."""
    rng = random.Random(seed)
    rule_names = list(RULES.keys())
    if include_hypothetical:
        rule_names.append("hypothetical_syllogism")

    puzzles: list[Puzzle] = []
    for i in range(n):
        rule = rng.choice(rule_names)
        if rule == "hypothetical_syllogism":
            seed_a = rng.choice(CONDITIONAL_SEEDS)
            seed_b = rng.choice(CONDITIONAL_SEEDS)
            premises, conclusion, valid = hypothetical_syllogism(seed_a, seed_b)
            scenario = {"seed_a": seed_a, "seed_b": seed_b}
        else:
            seed_kind, fn = RULES[rule]
            pool = CONDITIONAL_SEEDS if seed_kind == "conditional" else DISJUNCTION_SEEDS
            scenario_seed = rng.choice(pool)
            premises, conclusion, valid = fn(scenario_seed)
            scenario = scenario_seed

        natural = build_prompt(premises, conclusion)
        puzzles.append(Puzzle(
            id=f"logic-{i:06d}",
            rule=rule,
            is_valid=valid,
            premises=premises,
            conclusion=conclusion,
            scenario=scenario,
            natural_prompt=natural,
        ))
    return puzzles


def build_prompt(premises: list[str], conclusion: str) -> str:
    """English-side prompt the teacher will see."""
    premise_block = " ".join(premises)
    return (
        f"{premise_block} Therefore, {conclusion.lower().rstrip('.')}. "
        f"Is this argument valid or invalid? Explain your reasoning."
    )


# ---------------------------------------------------------------------------
# Auto-verifier
# ---------------------------------------------------------------------------

VERDICT_KEYWORDS_VALID = {"valid", "follows", "correct", "sound", "good"}
VERDICT_KEYWORDS_INVALID = {"invalid", "does not follow", "incorrect", "fallacy", "fallacious", "bad"}


def extract_verdict(text: str) -> str | None:
    """Heuristic verdict extractor for teacher responses.

    Looks at the last 200 characters for verdict keywords. Returns "valid",
    "invalid", or None if ambiguous. The teacher is prompted to state its
    final verdict at the end, so this is usually robust.
    """
    tail = text[-400:].lower()
    has_valid = any(k in tail for k in VERDICT_KEYWORDS_VALID)
    has_invalid = any(k in tail for k in VERDICT_KEYWORDS_INVALID)
    if has_invalid and not has_valid:
        return "invalid"
    if has_valid and not has_invalid:
        return "valid"
    if has_valid and has_invalid:
        # Both keywords appear — last-occurrence wins.
        last_valid = max((tail.rfind(k) for k in VERDICT_KEYWORDS_VALID), default=-1)
        last_invalid = max((tail.rfind(k) for k in VERDICT_KEYWORDS_INVALID), default=-1)
        return "invalid" if last_invalid > last_valid else "valid"
    return None


def verify(puzzle: Puzzle, model_response: str) -> dict:
    """Score a model response against the puzzle's ground truth."""
    extracted = extract_verdict(model_response)
    expected = "valid" if puzzle.is_valid else "invalid"
    return {
        "expected": expected,
        "extracted": extracted,
        "correct": extracted == expected if extracted else None,
    }


def main():
    """Smoke test: generate 20 puzzles, print them."""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    puzzles = generate(args.n, seed=args.seed)
    if args.out:
        with open(args.out, "w") as f:
            for p in puzzles:
                f.write(json.dumps(asdict(p)) + "\n")
        print(f"Wrote {len(puzzles)} puzzles to {args.out}")
    else:
        for p in puzzles:
            print(f"[{p.rule}] valid={p.is_valid}")
            print(f"  premises: {p.premises}")
            print(f"  conclusion: {p.conclusion}")
            print()


if __name__ == "__main__":
    main()
