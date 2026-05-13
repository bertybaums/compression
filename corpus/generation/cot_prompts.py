"""
Prompt templates for the UGF chain-of-thought corpus campaign.

Two tracks:
  1. LOGIC — argument-validity puzzles from corpus.generation.logic_puzzles,
     verifiable answers, used both for rejection-sampling at generation time
     and as the verifier signal during the RL stage.
  2. PHILOSOPHY — open-ended philosophical reasoning prompts. No crisp
     verifier; quality scored later by LLM-judge.

Both tracks share the project's standard UGF compliance system prompt
(extended from generate_reasoning.SYSTEM_PROMPT) and emit JSON for clean
parsing.

CoT depth comes in two variants — "short" (~3–5 steps) and "extended"
(~8–15 steps with alternatives considered). The runner mixes them.
"""

# ---------------------------------------------------------------------------
# Shared UGF compliance rules. Kept aligned with generate_reasoning.SYSTEM_PROMPT
# (don't drift). The compliance rules are the load-bearing constraint; the
# CoT-specific instructions are layered on top per-track.
# ---------------------------------------------------------------------------

UGF_RULES = """\
RULES FOR THE WORDS YOU USE:
1. Use ONLY words from the Up Goer Five list — the ten hundred most common English words. All grammatical forms of allowed words are permitted (if "think" is allowed, so are "thinks", "thinking", "thought").
2. When a concept has no direct simple word, DESCRIBE it using allowed words. Examples: "premise" -> "first idea"; "conclusion" -> "last idea"; "valid" -> "follows for sure"; "invalid" -> "does not follow"; "antecedent" -> "the first part of the if-then"; "consequent" -> "the second part of the if-then".
3. Preserve meaning and logical structure as faithfully as you can.
4. Do NOT use any word not on the list, even if it seems common.
5. Numbers (0-9) and basic punctuation (. , ! ? ; : - ' " ( )) are allowed.
6. Do NOT use markdown formatting. No asterisks (*), no bold, no italic, no headers, no bullet points, no dashes used as list markers. Write plain running prose.
7. Single letters used as variable names (A, B, C, etc.) must be replaced with numbered descriptions like "the first thing", "the second thing", "the third thing". Ordinals like "fourth", "fifth", "sixth" are NOT allowed — use "thing number four", "thing number five" instead.

Words NOT allowed include most technical, academic, or specialized vocabulary. Examples to paraphrase: 'philosophy', 'argument', 'premise', 'conclusion', 'fallacy', 'valid', 'invalid', 'inference', 'hypothesis', 'logic', 'evidence', 'rule', 'rules', 'false', 'example', 'common', 'type', 'direct', 'data', 'test', 'result', 'based', 'exact', 'handle', 'describe'.\
"""


# ---------------------------------------------------------------------------
# LOGIC TRACK
# ---------------------------------------------------------------------------

LOGIC_COT_SYSTEM = f"""You work through small arguments step by step, deciding whether the last sentence really follows from the first sentences.

{UGF_RULES}

HOW TO REASON:
- Read the sentences carefully.
- If you see an "if X, then Y" sentence, say what the "if" part is and what the "then" part is.
- Check what the other sentences tell you and what they do NOT tell you.
- Walk through your thinking in sentences joined into a paragraph. Examples of how to start steps: "First, we notice ...", "Then, we can see ...", "But wait — ...", "So this means ...".
- End with a clear answer: either the last sentence follows for sure, or it does not follow.

REASONING DEPTH:
- {{depth_instruction}}

OUTPUT FORMAT:
A single JSON object on one line with exactly two keys:
- "reasoning": a paragraph of your step-by-step thinking in simple English (the words from the list).
- "verdict": exactly one of the strings "follows" or "does not follow".

Nothing else. No markdown. No prose outside the JSON."""

LOGIC_DEPTH_SHORT = (
    "Keep your reasoning short — three to five steps is enough for a small "
    "argument. Do not pad."
)

LOGIC_DEPTH_EXTENDED = (
    "Take your time. Eight to fifteen steps. Where it helps, think about "
    "whether someone could agree with all the early sentences but still "
    "disagree with the last sentence — describe a small story where that "
    "could happen. Use that story to test whether the last sentence really "
    "follows."
)

LOGIC_COT_USER = """Here is the argument:

{premises_block}

The last sentence is: {conclusion}

Does this last sentence really follow for sure from the earlier sentences? Walk through your thinking step by step in simple English words, then give your final answer as "follows" or "does not follow"."""


# ---------------------------------------------------------------------------
# PHILOSOPHY TRACK
# ---------------------------------------------------------------------------

PHILOSOPHY_COT_SYSTEM = f"""You think carefully about a hard question step by step, showing your reasoning as you go.

{UGF_RULES}

HOW TO REASON:
- Read the question carefully.
- Walk through your thinking in sentences joined into a paragraph. Examples of how to start steps: "First, we notice ...", "Then, we can see ...", "But someone might say ...", "Even so, ...", "So this means ...".
- Where it makes sense, consider an objection or a counterexample before settling on your view.
- End with a clear answer that follows from the thinking you just did.

REASONING DEPTH:
- {{depth_instruction}}

OUTPUT FORMAT:
A single JSON object on one line with exactly two keys:
- "reasoning": a paragraph of your step-by-step thinking in simple English.
- "conclusion": one or two sentences stating what you have concluded.

Nothing else. No markdown. No prose outside the JSON."""

PHILOSOPHY_DEPTH_SHORT = (
    "Keep your reasoning concise — three to five steps. Get to a clear "
    "answer without padding."
)

PHILOSOPHY_DEPTH_EXTENDED = (
    "Take your time. Eight to fifteen steps. Consider at least one "
    "objection or counterexample to your initial view before settling. "
    "Show your mind changing if it does."
)

PHILOSOPHY_COT_USER = """Here is the question:

{topic}

Think through this step by step in simple English words. Consider what is at stake, what the strongest answer might be, and whether there is a good reason to think the opposite. Then state your conclusion."""


# ---------------------------------------------------------------------------
# Per-track config dispatch
# ---------------------------------------------------------------------------

TRACKS = {
    "logic": {
        "system_prompt": LOGIC_COT_SYSTEM,
        "user_template": LOGIC_COT_USER,
        "depth_variants": {
            "short": LOGIC_DEPTH_SHORT,
            "extended": LOGIC_DEPTH_EXTENDED,
        },
        "output_keys": ["reasoning", "verdict"],
    },
    "philosophy": {
        "system_prompt": PHILOSOPHY_COT_SYSTEM,
        "user_template": PHILOSOPHY_COT_USER,
        "depth_variants": {
            "short": PHILOSOPHY_DEPTH_SHORT,
            "extended": PHILOSOPHY_DEPTH_EXTENDED,
        },
        "output_keys": ["reasoning", "conclusion"],
    },
}


def build_messages(track: str, depth: str, **fields) -> list[dict]:
    """Build [system, user] messages for a single generation call.

    Args:
        track: "logic" or "philosophy"
        depth: "short" or "extended"
        fields: either {premises_block, conclusion} for logic, or {topic} for philosophy.

    Returns OpenAI-style messages list.
    """
    if track not in TRACKS:
        raise ValueError(f"unknown track {track!r}; expected one of {list(TRACKS)}")
    cfg = TRACKS[track]
    if depth not in cfg["depth_variants"]:
        raise ValueError(f"unknown depth {depth!r}; expected short or extended")

    system = cfg["system_prompt"].format(depth_instruction=cfg["depth_variants"][depth])
    user = cfg["user_template"].format(**fields)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def smoke():
    """Print sample message blocks for inspection."""
    import json
    from corpus.generation.logic_puzzles import generate as gen_puzzles
    p = gen_puzzles(1)[0]
    print("=== LOGIC short ===")
    for m in build_messages("logic", "short",
                            premises_block="\n".join(p.premises),
                            conclusion=p.conclusion):
        print(f"--- {m['role']} ({len(m['content'])} chars) ---")
        print(m["content"][:600] + ("..." if len(m["content"]) > 600 else ""))
    print()
    print("=== PHILOSOPHY extended ===")
    for m in build_messages("philosophy", "extended",
                            topic="Can a person be morally responsible for actions they did under coercion?"):
        print(f"--- {m['role']} ({len(m['content'])} chars) ---")
        print(m["content"][:600] + ("..." if len(m["content"]) > 600 else ""))


if __name__ == "__main__":
    smoke()
