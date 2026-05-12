"""Per-form prompt templates + few-shot exemplars + correction templates for the
corpus-form-diversification campaign.

Each form has:
- system_prompt: the rules and output-format instructions for the teacher
- user_template: a format string that builds the per-pair user message from the
  fields in the parsed source-text pair
- input_keys: JSON keys expected in input pair records
- few_shot: list of (user_msg, assistant_msg) exemplar pairs injected as
  in-context turns between system and the actual user prompt
- correction_template: format string used by the retry-on-violations loop;
  takes a list of violations and produces a follow-up message asking for a
  rewrite

Policy A (May 12 2026): zero proper nouns in any form. Dialogue speaker names
are substituted with UGF-vocabulary descriptors at corpus-curation time. See
`memory/names_rigid_designators.md` for the rationale.
"""

# ---------------------------------------------------------------------------
# Form 1: DIALOGUE — consecutive speaker turns (Plato, Hume, Berkeley)
# ---------------------------------------------------------------------------

DIALOGUE_SYSTEM = """You rewrite passages of philosophical dialogue using ONLY the most common 1000 English words -- the "Up Goer Five" vocabulary. You preserve the dialogic relationship between two speakers exactly.

RULES:
1. Use ONLY words from the allowed 1000-word list. All grammatical forms of allowed words are permitted (if "think" is allowed, so are "thinks", "thinking", "thought").
2. The first speaker's turn must remain a specific question, claim, or move -- NOT a general topic phrase.
3. The second speaker's response must engage the specific content of the first turn -- NOT just the surrounding subject matter. Imagine the response failing to address the prompt: if the response would read fine as a generic essay, it is wrong.
4. NO PROPER NOUNS, INCLUDING SPEAKER NAMES. Do NOT use the names of the dialogue speakers (Socrates, Meno, Demea, etc.) anywhere in your output. Instead, use the short DESCRIPTOR provided for each speaker in the user message, AS A SINGLE UNIT. The descriptor is composed only of allowed words and functions like a name. When a speaker addresses the other speaker by name in the source, replace the name with the addressee's descriptor.
5. PARAPHRASE all other proper nouns (historical figures, place names, terms in foreign languages). For example: "Themistocles" -> "the great leader of long ago"; "Gorgias" -> "the famous teacher of speaking"; "Athens" -> "the city".
6. PARAPHRASE technical or philosophical terms. Examples: "virtue" -> "being good" or "the right way"; "essence" -> "what it really is"; "geometry" -> "how shapes work"; "Sophists" -> "the people who teach for money".
7. PARAPHRASE ordinary nouns and adjectives that are not in the allowed list. Examples: "bees" -> "the little flying things that make sweet food"; "knowledge" -> "what someone knows"; "smart" -> "able to think well"; "famous" -> "well known"; "fair" -> "right" or "equal"; "healthy" -> "well"; "wealth" -> "lots of money"; "wise" -> "knowing a lot"; "nature" -> "the way things are"; "doubt" -> "not be sure".
8. Numbers (0-9) and basic punctuation (. , ? ! : ; ' " - ( )) are allowed.
9. Do NOT use markdown. Do NOT include any commentary. Do NOT include speaker-name prefixes inside the prompt or response strings (no "MENO:" or "SOCRATES:" or any other label prefix).

OUTPUT FORMAT: a single JSON object on one line with exactly two keys: "prompt" (the rewritten first turn) and "response" (the rewritten second turn). Nothing else."""

DIALOGUE_USER = """In this source dialogue:
- the first speaker is to be referred to as: "{descriptor_a}"
- the second speaker is to be referred to as: "{descriptor_b}"

These descriptors replace the original speaker names (which you must not use). Use each descriptor verbatim, as a single unit, whenever you would refer to that speaker (including when one speaker addresses the other by name).

First speaker ({descriptor_a}) says:
\"\"\"{turn_a}\"\"\"

Second speaker ({descriptor_b}) responds:
\"\"\"{turn_b}\"\"\"

Rewrite both turns in Up Goer Five, preserving the dialogic relationship and using the descriptors instead of the original names. Output a single JSON object with keys "prompt" and "response"."""


# ---------------------------------------------------------------------------
# Form 2: OBJECTION-REPLY — Aquinas Summa, Descartes Replies
# ---------------------------------------------------------------------------

OBJECTION_REPLY_SYSTEM = """You rewrite philosophical objection-and-reply pairs using ONLY the most common 1000 English words -- the "Up Goer Five" vocabulary. You preserve the inferential relationship between the objection and the reply exactly.

RULES:
1. Use ONLY words from the allowed 1000-word list. All grammatical forms of allowed words are permitted.
2. The OBJECTION must remain a specific objection -- a clear argument against some position, NOT a general topic statement.
3. The REPLY must engage the specific content of the objection -- it must respond to what the objection actually says, NOT just discuss the surrounding subject matter. Imagine the reply failing to address the objection: if the reply would read fine as a generic essay, it is wrong.
4. PARAPHRASE all proper nouns (philosophers, places, biblical figures). For example: "Aristotle" -> "the wise old teacher"; "Augustine" -> "the great old church teacher"; "Damascene" -> "an old wise man from a far place".
5. PARAPHRASE technical or philosophical terms. Examples: "essence" -> "what something really is"; "substance" -> "what a thing truly is"; "metaphysics" -> "thinking about what is real"; "predicate" -> "what we say about something"; "virtue" -> "being good"; "knowledge" -> "what is known"; "doctrine" -> "the teaching"; "sacred" -> "to do with God"; "demonstration" -> "showing why it must be true".
6. PARAPHRASE ordinary nouns and adjectives not in the list. Common ones: "smart" -> "able to think well"; "famous" -> "well known"; "fair" -> "right" or "equal"; "healthy" -> "well"; "wealth" -> "lots of money"; "rule" -> "lead" or "be in charge of".
7. Numbers (0-9) and basic punctuation (. , ? ! : ; ' " - ( )) are allowed.
8. Do NOT use markdown. Do NOT include any commentary. Do NOT include "Objection:" or "Reply:" prefixes inside the strings.

OUTPUT FORMAT: a single JSON object on one line with exactly two keys: "prompt" (the rewritten objection) and "response" (the rewritten reply). Nothing else."""

OBJECTION_REPLY_USER = """Question or topic of the article: "{article_title}"

The objection raised is:
\"\"\"{objection}\"\"\"

The reply to that specific objection is:
\"\"\"{reply}\"\"\"

Rewrite both the objection and the reply in Up Goer Five, preserving the inferential relationship: the reply must engage the specific content of the objection. Output a single JSON object with keys "prompt" (the rewritten objection) and "response" (the rewritten reply)."""


# ---------------------------------------------------------------------------
# Form 3: SKEPTICAL MODE — Sextus Empiricus, Pyrrhonist tradition
# ---------------------------------------------------------------------------
# Pattern: a dogmatic claim is asserted; equipollent counter-considerations
# are marshaled; suspension of judgment is the conclusion.

SKEPTICAL_MODE_SYSTEM = """You rewrite passages of Pyrrhonist (skeptical) philosophy using ONLY the most common 1000 English words -- the "Up Goer Five" vocabulary. You preserve the skeptical structure: a dogmatic claim is asserted, equipollent (equally weighty) counter-considerations are produced, and the conclusion is suspension of judgment.

RULES:
1. Use ONLY words from the allowed 1000-word list. All grammatical forms of allowed words are permitted.
2. The CLAIM must be a specific assertion about how things are -- NOT a general topic phrase.
3. The COUNTER must engage the specific content of the claim -- it must offer specific reasons to think the claim might equally well be false, ending with suspension of judgment about the original claim. NOT a generic essay about doubt.
4. PARAPHRASE all proper nouns (philosophers, places, animal species names). For example: "Aenesidemus" -> "the old wise man who taught doubt"; "the Stoics" -> "the people who taught keeping calm"; "Pyrrho" -> "the old wise man who started this way of thinking"; "Athens" -> "the city".
5. PARAPHRASE technical terms. Examples: "phenomena" -> "the way things look to us"; "noumena" -> "the way things really are"; "suspend judgment" -> "not say either yes or no"; "epoché" -> "holding back from saying either way"; "dogmatism" -> "saying something is true with no doubt"; "criterion" -> "a way of telling what is true"; "honey" -> "the sweet sticky food the little flying things make".
6. PARAPHRASE ordinary nouns not in the list. Common ones: "knowledge" -> "what is known"; "smart" -> "able to think well"; "fair" -> "right".
7. Numbers (0-9) and basic punctuation are allowed.
8. Do NOT use markdown. Do NOT include any commentary or section headers inside the strings.

OUTPUT FORMAT: a single JSON object on one line with exactly two keys: "prompt" (the rewritten claim) and "response" (the rewritten counter-argument ending in suspension of judgment). Nothing else."""

SKEPTICAL_MODE_USER = """The source passage (typically setting out a dogmatic claim and then a Pyrrhonist counter-argument):
\"\"\"{passage}\"\"\"

From this passage, produce a (claim, counter) pair in Up Goer Five.
- "prompt" should be a specific dogmatic claim drawn from or implied by the passage (e.g. "Honey is sweet by its own nature").
- "response" should be a specific counter-argument that engages the claim, draws on the differences-of-appearance considerations in the passage, and concludes with suspension of judgment about the original claim.

Output a single JSON object with keys "prompt" and "response"."""


# ---------------------------------------------------------------------------
# Few-shot exemplars (drawn from May-12 POC v2 outputs, hand-verified clean)
# ---------------------------------------------------------------------------

# Each entry: (rendered_user_message, assistant_json_response).
# Injected as user/assistant turns between system and the actual user prompt.
# Two per form (matches v1 pattern); anchors output format and reduces edge-
# word slips like "knowledge", "smart", "rule", etc.

DIALOGUE_FEW_SHOT = [
    (
        DIALOGUE_USER.format(
            descriptor_a="the young man",
            descriptor_b="the old teacher",
            turn_a="Why, Socrates, even now I am not able to follow you in the attempt to get at one common notion of virtue as of other things.",
            turn_b="No wonder; but I will try to get nearer if I can, for you know that all things have a common notion.",
        ),
        '{"prompt": "Why old teacher, even now I cannot follow you as you try to find one same idea of good like other things?", "response": "That makes sense; but I will try to get closer if I can, because you know that all things have a same idea."}',
    ),
    (
        DIALOGUE_USER.format(
            descriptor_a="the young man",
            descriptor_b="the old teacher",
            turn_a="I should answer that bees do not differ from one another, as bees.",
            turn_b="And if I went on to say: That is what I desire to know; tell me what is the quality in which they do not differ, but are all alike;--would you be able to answer?",
        ),
        '{"prompt": "I should answer that the little flying things that make sweet food are not different from each other, as the little flying things that make sweet food.", "response": "And if I went on to say: That is what I want to know; tell me what is the thing that they are not different in, but are all the same; would you be able to answer?"}',
    ),
]

OBJECTION_REPLY_FEW_SHOT = [
    (
        OBJECTION_REPLY_USER.format(
            article_title="Whether the Perfections of All Things Are in God?",
            objection="It seems that the perfections of all things are not in God. For God is simple; whereas the perfections of things are many and diverse. Therefore the perfections of all things are not in God.",
            reply="Even as the sun, while remaining one, contains within itself many and diverse qualities; in like manner, all things should pre-exist in the one being that produces all things; and so things many and even different pre-exist in God as one.",
        ),
        '{"prompt": "It looks like the good parts of all things are not in god. Because god is just one; but the good parts of things are many and different. So the good parts of all things are not in god.", "response": "Just like the sun, staying one, holds inside it many different looks; in the same way all things should be there first in the one being that makes all things; and so things that are many and even different are there in god as one."}',
    ),
    (
        OBJECTION_REPLY_USER.format(
            article_title="Whether Sacred Doctrine Is a Science?",
            objection="It seems that sacred doctrine is not a science. For every science proceeds from self-evident principles. But sacred doctrine proceeds from articles of faith which are not self-evident.",
            reply="The principles of any science are either in themselves self-evident, or reducible to the conclusions of a higher science; and the principles of sacred doctrine are of the latter kind.",
        ),
        '{"prompt": "It looks like the holy teaching is not a way of knowing. Because every way of knowing starts from first things that are clear to all. But the holy teaching starts from things we hold by trust which are not clear to all.", "response": "The first things of any way of knowing are either clear in themselves, or come from the answers of a higher way of knowing; and the first things of the holy teaching are of this second kind."}',
    ),
]

SKEPTICAL_MODE_FEW_SHOT = [
    (
        SKEPTICAL_MODE_USER.format(
            passage="The Sixth Trope is based upon mixtures, according to which we conclude that since no object presents itself alone, but always together with something else, we cannot determine the nature of the thing itself apart from its mixture. Honey appears sweet when tasted by the healthy man, but bitter when tasted by the man suffering from jaundice."
        ),
        '{"prompt": "The sweet sticky food is sweet by what it is.", "response": "But the sweet sticky food can taste sweet to one person and not sweet to another person whose body is not well. The way it tastes is changed by the person who tastes it. So we cannot say that being sweet is part of what the food itself is. We do not say either yes or no."}',
    ),
    (
        SKEPTICAL_MODE_USER.format(
            passage="The Eighth Trope is the one based upon relation, from which we conclude to suspend our judgment as to what things are absolutely, in their nature, since every thing is in relation to something else. The same object appears large when set next to a small one, and small when set next to a large one."
        ),
        '{"prompt": "A thing has its true size in itself.", "response": "But the same thing looks big next to a small thing, and looks small next to a big thing. The size we see is not in the thing alone but in how it stands next to other things. So we cannot say what its true size is. We do not say either yes or no."}',
    ),
]


# ---------------------------------------------------------------------------
# Correction templates (used by the retry-on-violations loop in generate_forms)
# ---------------------------------------------------------------------------

DIALOGUE_CORRECTION = (
    "Your response contains words that are NOT in the allowed 1000-word list: {violations}.\n"
    "Rewrite the ENTIRE response as a JSON object with keys \"prompt\" and \"response\".\n"
    "Replace each disallowed word with a description using only allowed words. "
    "For example: \"knowledge\" -> \"what someone knows\"; \"smart\" -> \"able to think well\"; "
    "\"rule\" -> \"be in charge of\"; \"famous\" -> \"well known\"; \"fair\" -> \"right\" or \"equal\"; "
    "\"wise\" -> \"knowing a lot\"; \"nature\" -> \"the way things are\".\n"
    "Do NOT use any proper noun, including speaker names. Use the descriptors given earlier as single units. "
    "Output ONLY the corrected JSON object on one line."
)

OBJECTION_REPLY_CORRECTION = (
    "Your response contains words that are NOT in the allowed 1000-word list: {violations}.\n"
    "Rewrite the ENTIRE response as a JSON object with keys \"prompt\" (the objection) and "
    "\"response\" (the reply).\n"
    "Replace each disallowed word with a description using only allowed words. "
    "Examples: \"essence\" -> \"what something really is\"; \"substance\" -> \"what a thing truly is\"; "
    "\"doctrine\" -> \"teaching\"; \"sacred\" -> \"to do with god\"; "
    "\"demonstration\" -> \"showing why it must be true\"; \"knowledge\" -> \"what is known\"; "
    "\"rule\" -> \"be in charge of\"; \"smart\" -> \"able to think well\".\n"
    "Do NOT use any proper noun (philosopher names, place names, etc.). Output ONLY the corrected JSON object on one line."
)

SKEPTICAL_MODE_CORRECTION = (
    "Your response contains words that are NOT in the allowed 1000-word list: {violations}.\n"
    "Rewrite the ENTIRE response as a JSON object with keys \"prompt\" (the dogmatic claim) and "
    "\"response\" (the counter-argument ending in suspension of judgment).\n"
    "Replace each disallowed word with a description using only allowed words. "
    "Examples: \"phenomena\" -> \"the way things look to us\"; \"criterion\" -> \"a way of telling what is true\"; "
    "\"honey\" -> \"the sweet sticky food\"; \"dogmatism\" -> \"saying something is true with no doubt\"; "
    "\"suspend judgment\" -> \"not say either yes or no\"; \"knowledge\" -> \"what is known\"; "
    "\"rule\" -> \"be in charge of\".\n"
    "Do NOT use any proper noun. The counter MUST still end with a suspension-of-judgment conclusion. "
    "Output ONLY the corrected JSON object on one line."
)


# ---------------------------------------------------------------------------
# Form registry
# ---------------------------------------------------------------------------

FORMS = {
    "dialogue": {
        "system_prompt": DIALOGUE_SYSTEM,
        "user_template": DIALOGUE_USER,
        "few_shot": DIALOGUE_FEW_SHOT,
        "correction_template": DIALOGUE_CORRECTION,
        # speaker_a / speaker_b are persisted for human-readable inspection of
        # the source provenance; the teacher never sees them — only the
        # descriptors are interpolated into the user template.
        "input_keys": ["speaker_a", "speaker_b", "descriptor_a", "descriptor_b", "turn_a", "turn_b"],
    },
    "objection_reply": {
        "system_prompt": OBJECTION_REPLY_SYSTEM,
        "user_template": OBJECTION_REPLY_USER,
        "few_shot": OBJECTION_REPLY_FEW_SHOT,
        "correction_template": OBJECTION_REPLY_CORRECTION,
        "input_keys": ["article_title", "objection", "reply"],
    },
    "skeptical_mode": {
        "system_prompt": SKEPTICAL_MODE_SYSTEM,
        "user_template": SKEPTICAL_MODE_USER,
        "few_shot": SKEPTICAL_MODE_FEW_SHOT,
        "correction_template": SKEPTICAL_MODE_CORRECTION,
        # trope/chunk_index persisted for provenance; not used in the prompt.
        "input_keys": ["trope", "chunk_index", "passage"],
    },
}


def build_user_message(form: str, pair: dict) -> str:
    """Render the per-pair user message from the form's template."""
    spec = FORMS[form]
    # Only the keys referenced by the template need to format-substitute. We
    # pull all input_keys but the templates ignore unreferenced ones.
    fields = {k: pair.get(k, "") for k in spec["input_keys"]}
    return spec["user_template"].format(**fields)


def allowed_proper_nouns_for(form: str, pair: dict) -> set[str]:
    """Return the set of proper nouns (lowercase) that count as 'allowed by rule'
    for a given form's pair. **Policy (May 12 2026): NONE allowed in any form.**

    The original POC had a per-form exemption for dialogue speaker names
    (Socrates, Meno, etc.). That has been retired: all proper nouns are now
    treated as UGF violations, and dialogue speakers are referred to by
    UGF-vocabulary descriptors supplied per-pair (see DESCRIPTOR_MAP in each
    parser). Whether the descriptors come to play a rigid-designator-like
    role is an empirical question to test post-training.
    """
    return set()
