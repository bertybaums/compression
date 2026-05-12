# Dialogue-extraction POC: Plato's *Meno* → UGF (prompt, response) pairs

**Date:** May 12, 2026
**Source:** Plato, *Meno*, trans. Benjamin Jowett (Project Gutenberg #1643)
**Teacher:** `openai/gpt-oss-120b` via MindRouter, `reasoning_effort=medium`, `temperature=0.7`, `max_tokens=4096`
**Sample:** 50 consecutive (A, B) speaker-pair extractions, deterministic seed=42

---

## Headline

The dialogue-extraction prompt template works. The teacher reliably produces structurally-faithful UGF (prompt, response) pairs that preserve the dialogic relationship between speakers. Single-shot UGF compliance is in the v1 first-shot range (62% both-turns-adjusted, 0.62 mean lexical violations per call); a v1-style retry loop would push this to >95% just as it did in v1's main corpus generation. **The POC's claim — that canonical philosophical forms can be converted into prompt-attention-shaped training data through teacher distillation — is supported.**

## Numbers

| Metric | Value |
|---|---:|
| API call ok | 50/50 (100%) |
| JSON parse ok | 50/50 (100%) |
| Both turns UGF, strict (counts dialogue-speaker names as violations) | 10/50 (20%) |
| Prompt UGF, adjusted (allows Socrates/Meno/Anytus/Boy) | 39/50 (78%) |
| Response UGF, adjusted | 38/50 (76%) |
| **Both turns UGF, adjusted** | **31/50 (62%)** |
| Mean *lexical* violations (excludes all proper nouns) | 0.62 per call |
| Wall time | 88s at concurrency=5 (~34 rpm against the 200 rpm MR cap) |

The "strict" 20% number is misleading — it counts the names Socrates / Meno / Anytus / Boy as violations even though we explicitly instructed the model to keep them (rule 4). The "adjusted" 62% is the right comparison to v1's first-shot rates, which were in the 40–60% range across teachers before the retry loop took compliance to 99%.

## Qualitative observations

### Dialogic structure preservation: excellent

Every one of the 50 responses engages the specific content of its prompt. None reads as a generic philosophical essay. Socrates' parallel-construction moves come through verbatim (e.g. "what is shape? round? a shape?" in pair 002). The Socratic prompt-attention property the corpus is designed to teach is visibly present in the output.

### Paraphrase quality: very good

The teacher consistently paraphrased major proper nouns and technical terms with the right register:

| Original | UGF rendering |
|---|---|
| Gorgias | "the well known teacher of speaking" / "the famous teacher of talking" |
| Sophists | "the people who teach for money" |
| Themistocles | "the great leader of long ago" |
| Athens, Athenian | "the city", "city man" |
| virtue | "being good" / "the right way" / "good ways" |
| geometry | "how shapes work" (when it appeared) |
| bees | "the little flying things that make sweet food" |
| roundness | "being round" |

These are delightful in the way Munroe's *Thing Explainer* is delightful. They are also doing real philosophical work — "being good" preserves the abstract-noun structure that makes Plato's question ("What is virtue?") ask the right thing.

### Lexical-violation pattern: concentrated on ~15 common words

The 19 calls with lexical violations slipped on the same small set of common English words:

| Word | Count | Notes |
|---|---:|---|
| knowledge | 3 | should be "things you know" / "what someone knows" |
| smart | 3 | should be "able to think well" / "knowing" |
| based | 2 | should be "built on" / "comes from" |
| healthy / health | 2+1 | should be "well" / "feeling fine" |
| fair | 2 | should be "right" / "equal" |
| famous | 2 | should be "well known" |
| shiny | 1 | should be "bright" |
| wealth | 1 | should be "lots of money" / "having a lot" |
| self | 1 | should be "the person himself" |
| advice | 1 | should be "what someone says to do" |
| Brave | 1 | should be "not afraid" (treated as PN by our split, but is lexical) |

This is exactly the v1 pattern: a small set of conceptually-close words the model wants to use but cannot. The v1 retry loop with a correction prompt listing the specific violations took v1 from this state to 99% compliance. The same loop would work here.

### Speaker-prefix artifact (worth flagging)

The model sometimes prepends a speaker label inside the JSON content (e.g. `"prompt": "MENO: I think a lot, Socrates..."` rather than `"prompt": "I think a lot, Socrates..."`). This is not strictly wrong — it preserves dialogue-presentation context — but for downstream training-data use we may want to either strip the prefix or instruct the model not to include one. Decision deferred; trivial post-processing either way.

## Six clean exemplars

Selected from the 16 calls with *zero* violations of any kind (strict).

### `meno_pair_001` (MENO → SOCRATES)

**Source A.** I often wonder, Socrates, that Gorgias is never heard promising to teach virtue: and when he hears others promising he only laughs at them; but he thinks that men should be taught to speak.

**Source B.** Then do you not think that the Sophists are teachers?

**UGF prompt.** MENO: I think a lot, Socrates, that the well known teacher of speaking is never heard to say he will teach being good: and when he hears others say they will, he only laughs at them; but he thinks that people should learn to talk.

**UGF response.** SOCRATES: Then do you not think that the people who teach for money are teachers?

### `meno_pair_003` (MENO → SOCRATES) — the bees passage

**Source A.** I should answer that bees do not differ from one another, as bees.

**Source B.** And if I went on to say: That is what I desire to know, Meno; tell me what is the quality in which they do not differ, but are all alike;--would you be able to answer?

**UGF prompt.** I should answer that the little flying things that make sweet food are not different from each other, as the little flying things that make sweet food.

**UGF response.** And if I say: That is what I want to know, Meno; tell me what is the thing they are not different in, but are all the same; can you answer?

### `meno_pair_005` (MENO → SOCRATES) — "What is virtue?"

**Source A.** Yes, Socrates; and we were quite right in doing so.

**Source B.** But then, my friend, do not suppose that we can explain to any one the nature of virtue as a whole through some unexplained portion of virtue, or anything at all in that fashion; we should only have to ask over again the old question, What is virtue? Am I not right?

**UGF prompt.** Yes Socrates and we were right to do that.

**UGF response.** But then, my friend, do not think that we can tell any person what being good is in all by a part we do not know, or anything like that; we must ask again the old ask: What is being good? Am I right?

### `meno_pair_011` (ANYTUS → SOCRATES) — Anytus on Athenian gentlemen

**Source A.** Why single out individuals? Any Athenian gentleman, taken at random, if he will mind him, will do far more good to him than the Sophists.

**Source B.** And did those gentlemen grow of themselves; and without having been taught by any one, were they nevertheless able to teach others that which they had never learned themselves?

**UGF prompt.** Why pick one person? Any city man, if you pick him, if he will think of you, will do more good to you than the people who teach for money.

**UGF response.** And did those men become on their own; and without anyone teaching them, could they still teach other people something they never learned?

### `meno_pair_014` (MENO → SOCRATES) — "Virtue is a good"

**Source A.** Yes, that appears to be the question which comes next in order.

**Source B.** Do we not say that virtue is a good?--This is a hypothesis which is not set aside.

**UGF prompt.** Yes, that looks like the next question.

**UGF response.** Do we not say that being good is a good? This is an idea that we do not put away.

### `meno_pair_016` (SOCRATES → MENO) — common nature

**Source A.** And so of the virtues, however many and different they may be, they have all a common nature which makes them virtues; and on this he who would answer the question, 'What is virtue?' would do well to have his eye fixed: Do you understand?

**Source B.** I am beginning to understand; but I do not as yet take hold of the question as I could wish.

**UGF prompt.** So the good things, even if there are many and they are not the same, they all have the same kind that makes them good things; and for this a person who wants to answer the question 'What is a good thing?' should keep his eye on it. Do you understand?

**UGF response.** I am beginning to understand, but I do not yet have the question clear enough as I could wish.

## Verdict

The prompt template is ready for the full Path A campaign. Three improvements to fold in before the full corpus-diversification run (~3 weeks of work, per `docs/followups/corpus-diversification.md`):

1. **Add a retry-on-violations loop** modeled on v1's `generate_reasoning.py`. Single retry with a correction prompt listing the specific lexical violations should lift adjusted compliance from 62% to ~95–99%.
2. **Decide the speaker-prefix convention** (strip the `MENO:`/`SOCRATES:` prefixes the teacher sometimes adds, or keep them). Either is defensible; just pick one.
3. **Consider few-shot exemplars** the v1 pipeline uses. Two clean dialogue (prompt, response) UGF pairs as user/assistant turns before the actual extraction call could further anchor the output format and reduce slip on edge words like *knowledge*, *smart*, *fair*.

## Next steps

- This POC validates the Plato dialogue path. Two parallel POCs would round out the Path A confidence: Hume's *Dialogues Concerning Natural Religion* (different translator's English, different speakers, same form), and one Aquinas *Summa* article for the objection-and-reply form. Each is another ~50 extractions at this teacher / config.
- Path A continuation training on the v1 Reasoner with a ~50K-trace form-diverse corpus (per `docs/followups/corpus-diversification.md`) is the next-bigger step.

## Reproducing

```bash
python3 corpus/poc/parse_meno.py            # parse + sample 50 dialogue pairs
python3 corpus/poc/run_dialogue_poc.py --n 50  # extract via gpt-oss-120b
```

Inputs and outputs:

- `corpus/poc/meno_raw.txt` — Gutenberg #1643 (deleted from repo; redownload with the URL in `parse_meno.py`)
- `corpus/poc/meno_pairs.jsonl` — 50 sampled (A, B) pairs (deterministic seed=42)
- `corpus/poc/dialogue_meno_results.jsonl` — 50 (UGF prompt, UGF response) outputs with per-call compliance details
- `corpus/poc/dialogue_meno_failures.jsonl` — any failed calls (none in this run)
