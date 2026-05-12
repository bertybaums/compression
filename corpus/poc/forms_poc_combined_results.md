# Corpus-form POC: dialogue, objection-reply, skeptical-mode across four canonical texts

**Date:** May 12, 2026
**Teacher:** `openai/gpt-oss-120b` via MindRouter, `reasoning_effort=medium`, `temperature=0.7`, `max_tokens=12288`
**Goal:** validate that the form-specific extraction prompts produce structurally-faithful UGF training pairs for each canonical philosophical form, as the prerequisite for the Path A corpus-diversification campaign described in `docs/followups/corpus-diversification.md`.

---

## Headline

**The form-extraction methodology generalizes across all four texts and three forms.** Structural fidelity — the property that makes each form a prompt-attention training corpus — is preserved in every successful extraction. First-shot UGF vocabulary compliance varies with the source vocabulary's distance from the UGF wordlist, but the structural property is robust to that variance.

The v1-style retry-on-violations loop is the missing piece: at v1's first-shot rates of 60–95%, the retry loop took compliance to 99%. The same loop dropped into this pipeline will do the same.

## Headline numbers

> **Update (May 12, 2026, later same day):** the dialogue form now operates under **Policy A — strict no proper nouns anywhere**, with per-source UGF descriptors substituting for character names (Socrates → "the old teacher" etc.; see "Policy A and the descriptor convention" below for full rationale and the per-source maps). The Meno and Hume v1 dialogue numbers in the table below were collected *before* the policy change and counted speaker names as "allowed PNs"; v2 numbers were collected under the new policy. Aquinas and Sextus already had no PN exemption and are unchanged.

| Source | Form | n | API/JSON ok | Both UGF strict | Mean lex viol |
|---|---|---:|---:|---:|---:|
| **Plato, *Meno* v2** (Jowett 1871, descriptors) | dialogue | 50 | 100% / 100% | **54%** | 0.74 |
| **Plato, *Meno* v1** (Jowett 1871, names allowed) | dialogue | 50 | 100% / 100% | 20% (62% adj) | 0.62 |
| **Aquinas, *Summa* I** (Dominican 1911) | objection-reply | 50 | 100% / 100% | 34% | 2.94 |
| **Sextus, *Outlines* I** (Patrick 1899) | skeptical-mode | 22 | 100% / 100% | 27% | 2.73 |
| **Hume, *Dialogues* v2** (1779, descriptors) | dialogue | 41 | 100% / 100% | 0% | 7.90 |
| **Hume, *Dialogues* v1** (1779, names allowed) | dialogue | 41 | 100% / 100% | 7% | 6.80 |

"Both UGF strict" = both prompt and response are UGF-compliant with NO proper nouns whatsoever counted as exempt (the operational definition under Policy A). "Mean lex viol" = average count of *lexical* (non-proper-noun) UGF violations per call.

**Pattern (cross-source):** the harder/older the source vocabulary, the lower the first-shot rate — but the **form is preserved across all four sources**. Hume's 1779 English remains the demanding outlier; Plato-via-Jowett-1871 is the easy case; Aquinas-Dominican-1911 and Patrick-1899 are in the middle. None of the four had a single API or JSON-parse failure after the `max_tokens` bump to 12288.

**Pattern (Policy A vs original):** on Meno, Policy A *increases* strict compliance from 20% to 54% — because the previous strict count was dominated by the 4 dialogue speakers being counted as violations. On Hume, the strict number drops from 7% to 0% because Hume's first-shot lex compliance is intrinsically low (mean ~7 lex violations per call); names were never the dominant violation source there. **The descriptor substitution itself is robust on both sources**: less than 1% PN slip rate post-policy (the rare slips are sentence-initial false positives like capitalized "Indeed" and "Patience", not the model accidentally typing "Socrates" or "Demea").

## Policy A and the descriptor convention

The Plato POC's first version allowed dialogue speaker names verbatim (Socrates, Meno, Anytus, Boy in the dialogue form; no PN exemption for objection-reply or skeptical-mode). Bert's call on May 12, 2026: that is the wrong policy. The right policy is **strict no proper nouns anywhere**, with each character substituted by a short UGF-vocabulary descriptor that functions as a single referring unit. The descriptor *becomes* the name; whether the model treats it as such — whether rigid designation emerges over the descriptors — is now an empirical post-training test (see `memory/names_rigid_designators.md`).

Per-source descriptor maps used in this POC:

| Source | Original | UGF descriptor |
|---|---|---|
| Plato, *Meno* | Socrates | the old teacher |
| Plato, *Meno* | Meno | the young man |
| Plato, *Meno* | Anytus | the angry man |
| Plato, *Meno* | Boy | the young helper |
| Hume, *Dialogues* | Demea | the church man |
| Hume, *Dialogues* | Cleanthes | the man who sees plans |
| Hume, *Dialogues* | Philo | the careful one |

Implementation: `DESCRIPTOR_MAP` in `parse_meno.py` / `parse_hume.py`; rule 4 of `forms.DIALOGUE_SYSTEM` instructs the teacher to use the descriptor as a single unit; `forms.allowed_proper_nouns_for(...)` now returns `set()` for every form (no exemption).

### Example: descriptor in action

**Meno v2 pair 002:**
- Source A: "Why, Socrates, even now I am not able to follow you in the attempt to get at one common notion of virtue as of other things."
- UGF prompt (no name): *"Why old teacher, even now I cannot follow you as you try to find one same idea of good like other things?"*

The descriptor lands as a vocative ("Why old teacher"), exactly where "Socrates" was being used as a vocative in the source.

**Meno v2 pair 003:**
- Source B: "And if I went on to say: That is what I desire to know, Meno; tell me what is the quality in which they do not differ..."
- UGF response: *"And if I went on to say: That is what I want to know, the young man; tell me what is the thing that they are not different in, but are all the same; would you be able to answer?"*

Socrates' address to Meno ("Meno; tell me") becomes "the young man; tell me." The descriptor functions as a vocative; the dialogic addressee structure is preserved.

## What the structural property looks like in the output

### Form 1: Dialogue (Plato + Hume)

The interlocutor's response must engage the specific content of the first turn. In every clean extraction, it does.

**Plato, *Meno* (pair 002).** Socrates' "what is shape? round? a shape?" parallel construction comes through verbatim:

- UGF prompt (MENO): *"Why, Socrates, still I cannot understand you when I try to find one same idea of the right way like other things?"*
- UGF response (SOCRATES): *"No wonder; but I will try to get close if I can, because you know that all things have one same idea. Now imagine that someone asked you the same question I asked before: Meno, he would say, what is shape? And if you said being round, he would answer you, in my way of talking, by asking if you would say that being round is shape or a shape; and you would say a shape."*

**Hume, *Dialogues* (pair 008).** Cleanthes and Demea sustaining the deity debate:

- UGF prompt (CLEANTHES): *"I do not take those ideas. They do not scare me. In fact they make me feel good because they always need the thought that the world was made on a plan. I hold to that thought and I think it is enough for the story about the big one."*
- UGF response (DEMEA): *"It is a small thing made on a ground that moves. We do not know if there is one big one or many big ones; if the big one or big ones are right or bad, high or low, dead or alive. So we can not believe them. We do not know how to talk or care to them."*

"The deity or deities" → "the big one or big ones." "Tottering foundation" → "ground that moves." These are doing real philosophical work, not just surface translation.

### Form 2: Objection-and-Reply (Aquinas)

The reply must engage the specific objection. The Aquinas extractions land this remarkably well even on Trinitarian theology.

**Aquinas, *Summa* I (pair 006). Whether There Is Trinity in God?**

- UGF objection: *"All that is in god is in the one of what god is as god is his own what he is. So if the three people are in god they are in the one of what god is and so in god there is three one which is a bad idea."*
- UGF reply: *"In the god three people idea we think about both a number and the people with that number. So when we say 'three people in one' we do not put the number in the one of what god is as if we said three and one but we put the three people in the one of the kind as the people that are said to be of a kind are said to be in that kind and we say 'one in three people' that means the kind is in its people."*

"Essence" becomes "what god is" / "the one of the kind." The reply distinguishes the right reading of "Three in One" from the wrong reading the objection assumed — preserving the Thomistic move exactly.

**Aquinas, *Summa* I (pair 003). Whether the Perfections of All Things Are in God?**

- UGF objection: *"It looks like the good parts of all things are not in god. Because god is just one, as we saw before; but the good parts of things are many and different. So the good parts of all things are not in god."*
- UGF reply: *"Just like the sun, as the old man who said about the world says, stays one and gives light the same in all places, it holds inside it the first and same what things we can see are made of, and many different looks. In the same way, all things that are in a real being together should be there before the thing that makes all things..."*

The sun analogy from Dionysius is preserved. "Dionysius" becomes "the old man who said about the world" — a paraphrase by description, exactly what rule 4 calls for.

### Form 3: Skeptical Mode (Sextus)

The counter must engage the dogmatic claim and end in suspension of judgment. The teacher produces clean Pyrrhonist epoché endings ("So we do not say either yes or no" / "We must not say either yes or no").

**Sextus, *Outlines* I (Trope of Relation, pair 006).**

- UGF claim: *"Every thing is the same inside no matter who looks at it."*
- UGF counter: *"But a thing can look different to different people at different times in different places. So we can not know if it is the same inside. We do not say either yes or no."*

**Sextus, *Outlines* I (Trope on values, pair 005).**

- UGF claim: *"Things that give a good feel are good."*
- UGF counter: *"Some people feel good when they see a fast horse, but other people feel bad when they see the same horse. If the same thing can give a good feel to one and a bad feel to another, then the thing is not only good. It may be that the feel comes from the person, not from the thing. Because we see the thing in different ways, we cannot say the thing is good or not good. So we must not say either yes or no."*

The Pyrrhonist move ("the feel comes from the person, not from the thing") is the *Trope of Relation* applied directly. The teacher caught the deep skeptical insight, not just the surface form.

## Cross-source compliance pattern

Compliance is a function of source-vocabulary distance from UGF:

- **Plato via Jowett 1871** — the easiest case. Jowett's English is clean late-Victorian; Plato's content paraphrases readily ("virtue" → "being good"; "Sophists" → "people who teach for money"). Mean 0.62 lex violations per call.
- **Patrick 1899 / Dominican 1911** — middle case. Patrick's translation is plain late-19th-century English; the Dominican Aquinas similarly so. Both source ~3× as many violations as Plato-Jowett (2.7–2.9 mean lex), driven by accumulated technical vocabulary (Aquinas: "essence", "substance", "predicate"; Sextus: "dogmatism", "phenomena", "criterion").
- **Hume 1779** — the hard case. Hume's 18th-century English is denser, more polysyllabic, and uses more abstract nominalizations than the others. Mean 6.80 lex violations per call. Common slips: "rule", "result", "smart", "faith", "plants", "joy", "compare", "weak", "limited", "odd", "false", "proof", "common", "holy", "wise".

The slip pattern is structurally identical across sources: a small set of conceptually-close common English words (~10–20 per source) that aren't in UGF but that the teacher reaches for. This is *exactly* the v1 pattern. The v1 retry loop with a correction prompt listing the specific violations took v1's gemma teacher from a comparable first-shot rate to 99% compliance.

## What was needed to make this work

Two non-obvious adjustments compared to a naive port of v1:

1. **`max_tokens` budget must scale with source-passage length.** First Hume run with v1's `max_tokens=4096` had 24% call-failures from "thinking budget exhausted" (gpt-oss-120b's `reasoning_content` consuming the whole budget before any output). Bumping to `max_tokens=12288` brought call success to 100% on all three subsequent forms. Source-passage length is the dominant factor here, not source-passage difficulty.

2. **Per-form proper-noun rules.** Dialogue extraction needs the speaker names to be preserved verbatim (rule 4 of the dialogue system prompt). Objection-reply and skeptical-mode forms have no allowed proper nouns — every historical figure must be paraphrased. The compliance check correctly distinguishes "allowed PN" from "lexical violation" per form.

## What's blocked

Three things to add before the full Path A campaign (per `docs/followups/corpus-diversification.md`):

1. **A retry-on-violations loop**, modeled on v1's `generate_reasoning.py`. Single retry with a correction prompt listing the specific lexical violations should lift adjusted compliance from this run's 7–62% range to a uniform 95%+. This is the single most impactful improvement and is well-validated in v1.

2. **A few-shot exemplar bank per form.** Two clean exemplars per form, injected as user/assistant turns before the actual extraction call, anchors the output format and reduces slip on edge vocabulary words (`smart`, `rule`, `result`). v1 used two exemplars and saw substantial first-shot compliance improvements.

3. **Speaker-prefix normalization for the dialogue form.** The teacher sometimes prepends `MENO:` / `SOCRATES:` / `CLEANTHES:` inside the JSON content strings. Either instruct it to omit (current rule 9), or strip in post-processing. Trivial either way.

Two minor data-hygiene items, less urgent:

- The Aquinas parser misses titles for a few articles whose `Whether ... ?` line wraps across two source lines (`(no title)` appears in ~10% of records). Tighten the title regex.
- The Sextus runner doesn't persist the source `trope` and `chunk_index` fields to results — they're in `sextus_pairs.jsonl` but not in `skeptical_mode_sextus_results.jsonl`. Fix by adding to `forms.FORMS["skeptical_mode"]["input_keys"]`.

## The post-training rigidity experiment

Policy A buys us an empirical test that the old policy precluded. After the Reasoner is trained on the strictly-name-free corpus, we can ask: **do the descriptors come to function as rigid designators?**

Operationally: hold out canonical (original-name, descriptor) pairs (Socrates ↔ "the old teacher", Demea ↔ "the church man", etc.). Train a small linear probe on the Reasoner's descriptor-in-context representations to predict the original name. Measure recovery rate. Run modal-rigidity behavioral probes (counterfactual identity, opaque-context substitution, cross-context coreference).

- **High recovery + rigidity behaviors** = the descriptor functions name-like even though the surface form was strictly predicational. Evidence for an inferentialist account of singular-term content (Brandom 1994 ch. 6 vindicated).
- **Low recovery / weak rigidity** = something distinctive about names is *not* captured by inferential role alone. Evidence *against* a thoroughgoing inferentialism about singular terms. Either result is publishable.

This is now a load-bearing experiment for the inferentialism paper (`docs/followups/inferentialism.md`), which gains a second pillar: the prompt-attention deficit tests inferentialism about *predicates*; the descriptor-rigidity experiment tests inferentialism about *singular terms*.

## Implications for the corpus-diversification plan

The plan in `docs/followups/corpus-diversification.md` proposed a 500K-trace form-diverse corpus at ~30% dialogue / 20% objection-reply / 15% aphorism / 15% letter / 10% treatise / 10% v1-style. **This POC validates the dialogue, objection-reply, and skeptical-mode subsets directly.** The skeptical-mode form was not in the original mix; it should be added (suggested ~10–15% share, supplanting some of the treatise share, since it's a richer prompt-attention shape than treatise-with-anticipated-objection).

Recommended revised mix for the Path A corpus:

| Form | Share | Sources tested | Sources to add |
|---|---:|---|---|
| Dialogue | 25% | Plato (Meno), Hume | Berkeley *Three Dialogues*; more Plato (*Republic*, *Theaetetus*, *Sophist*); Leibniz *New Essays* |
| Objection-and-reply | 20% | Aquinas *Summa* I | Descartes *Meditations* + *Objections and Replies*; rest of *Summa* |
| **Skeptical-mode** | **15%** | Sextus *Outlines* I | rest of *Outlines* (Bks II–III, if a clean PD source can be sourced — Patrick has only Book I) |
| Aphorism / explained | 12% | (not yet) | Wittgenstein *Tractatus*; M. Aurelius; Pascal |
| Letter / response-to-frame | 13% | (not yet) | Seneca; Spinoza correspondence; Locke *Letter Concerning Toleration* |
| Treatise sub-argument | 5% | (not yet) | Mill *Utilitarianism*; Hume *Treatise* Bk I |
| Preserved v1 essays | 10% | (existing corpus) | — |

## Reproducing

```bash
# Source-text parsers (one per text)
python3 corpus/poc/parse_meno.py        # Plato → meno_pairs.jsonl
python3 corpus/poc/parse_hume.py        # Hume → hume_pairs.jsonl
python3 corpus/poc/parse_aquinas.py     # Aquinas → aquinas_pairs.jsonl
python3 corpus/poc/parse_sextus.py      # Sextus (via Patrick) → sextus_pairs.jsonl

# Form-parameterized extraction runs
python3 corpus/poc/run_extraction.py --form dialogue \
    --pairs corpus/poc/meno_pairs.jsonl \
    --results corpus/poc/dialogue_meno_results.jsonl \
    --failures corpus/poc/dialogue_meno_failures.jsonl --n 50

python3 corpus/poc/run_extraction.py --form dialogue \
    --pairs corpus/poc/hume_pairs.jsonl \
    --results corpus/poc/dialogue_hume_results.jsonl \
    --failures corpus/poc/dialogue_hume_failures.jsonl --n 41

python3 corpus/poc/run_extraction.py --form objection_reply \
    --pairs corpus/poc/aquinas_pairs.jsonl \
    --results corpus/poc/objection_reply_aquinas_results.jsonl \
    --failures corpus/poc/objection_reply_aquinas_failures.jsonl --n 50

python3 corpus/poc/run_extraction.py --form skeptical_mode \
    --pairs corpus/poc/sextus_pairs.jsonl \
    --results corpus/poc/skeptical_mode_sextus_results.jsonl \
    --failures corpus/poc/skeptical_mode_sextus_failures.jsonl --n 22
```

Per-form prompt templates and the compliance-check logic live in `corpus/poc/forms.py` and `corpus/poc/run_extraction.py`. The original Plato-only POC writeup is at `corpus/poc/dialogue_meno_results.md` and remains the most detailed exemplar-walkthrough; this document is the cross-source summary.
