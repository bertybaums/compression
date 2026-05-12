# Followup: Corpus diversification — beyond essays, into philosophical forms

**Date:** May 12, 2026
**Status:** active proposal — supersedes thread B2 (now folded in)
**Anchor in main paper:** would change the Reasoner's training corpus for paper-G v2 and is a prerequisite for thread D (scaling) if we want the 2D scan to escape the v1 deficit
**Thread in memory:** B (refocused) — see `research_threads_open.md`

---

## Thesis

The compression-v1 Reasoner's prompt-attention deficit is, on inspection, a corpus-*form* issue rather than a corpus-*topic* issue. Our v1 traces are uniformly short-topic-phrase prompts ("why X matters", "how to think about Y") followed by extended UGF essays. The model has learned the form correctly — and learned it so well that the form runs even when the prompt does not warrant it. The principled fix is to retrain (or continue-train) on a corpus whose source material exhibits *form diversity*: dialogue, aphorism, objection-and-reply, letter, treatise. The history of Western philosophy contains all of these forms in canonical, public-domain texts.

The central insight, sharpened: **a Socratic dialogue is, structurally, a prompt-attention training corpus by construction.** The interlocutor must engage the specific point being made, or the dialogue collapses. You cannot insert a generic philosophical essay into *Phaedo* — Socrates would catch it on the next line. The form *enforces* what we want the model to learn. The same is true (with variations) for Berkeley's *Three Dialogues*, Hume's *Dialogues Concerning Natural Religion*, Aquinas's objection-and-reply structure, and Spinoza's correspondence.

This followup is therefore not "add diverse prompts to the existing corpus." It is "retrain on a corpus whose source material has the right structural property in the first place."

---

## Catalog of public-domain texts, by form

All texts below are either out of copyright (most pre-1928) or available under permissive licenses. Two especially useful sources:

- **Project Gutenberg** (`gutenberg.org`) — clean public-domain texts in English. Most older translations are here.
- **Early Modern Texts** (`earlymoderntexts.com`) — Jonathan Bennett's modernized early-modern philosophy. CC-BY-NC, which is fine for research. Saves enormous prep work: a Bennett *Three Dialogues* reads cleanly in modern English rather than 1713 English.

### Dialogues (the highest prompt-attention training value)

| Author | Text | Source | Why it's useful |
|---|---|---|---|
| Plato | *Apology*, *Crito*, *Meno*, *Phaedo*, *Symposium*, *Republic*, *Theaetetus*, *Sophist*, *Statesman*, *Parmenides*, *Gorgias*, *Protagoras* | Jowett (1871) on Gutenberg | Canonical Socratic dialogue; *Meno*'s slave-boy passage is Socrates *building up* an interlocutor's response step by step — the literal opposite of a generic essay. |
| Hume | *Dialogues Concerning Natural Religion* (1779) | Gutenberg + Bennett | Three speakers (Cleanthes, Demea, Philo) tracking a sustained design-argument debate. Substantive prompt-attention target. |
| Berkeley | *Three Dialogues Between Hylas and Philonous* (1713) | Gutenberg + Bennett | Hylas attacks; Philonous responds to each specific attack. Cleanest objection-and-reply-in-dialogue corpus we have. |
| Leibniz | *New Essays on Human Understanding* (1704) | Bennett | Dialogue tracking Locke's *Essay* section by section — gives us dialogue paired with a known target text. |
| Boethius | *Consolation of Philosophy* | Gutenberg | Dialogue with personified Philosophy; clear interlocutor structure. |
| Augustine | *Soliloquies* | Gutenberg | Dialogue between Augustine and Reason. Internal-dialogue training. |

### Objection-and-reply

| Author | Text | Source | Why it's useful |
|---|---|---|---|
| Aquinas | *Summa Theologica* (selected articles) | English Dominican translation (1911) on Gutenberg | Strictest objection-and-reply structure in the canon: each article is "objection 1 / objection 2 / on the contrary / I answer that / reply to obj. 1 / reply to obj. 2." Extract directly. |
| Descartes | *Meditations* + *Objections and Replies* | Bennett | Six meditations plus seven sets of objections by Arnauld, Hobbes, Gassendi, et al., each with Descartes' explicit reply. Position-tracking corpus. |
| Anselm | *Proslogion* + Gaunilo's reply | Multiple PD translations | Compact, two-step objection-reply structure. |

### Aphoristic / numbered remarks

| Author | Text | Source | Why it's useful |
|---|---|---|---|
| Wittgenstein | *Tractatus Logico-Philosophicus* (Ogden trans. 1922) | Gutenberg | Hierarchical numbered remarks — 1, 1.1, 1.11, 1.12 — each often refines or qualifies the parent. Forces the model to attend to compact declarative statements. |
| Marcus Aurelius | *Meditations* (Long trans. 1862) | Gutenberg | Short reflective remarks, often self-addressed. |
| Pascal | *Pensées* | Gutenberg | Fragmentary remarks of varying length, many in question form. |
| Schopenhauer | *Aphorisms on the Wisdom of Life* | Gutenberg | Compact moral-psychological aphorisms. |
| Epictetus | *Enchiridion* | Gutenberg | Short prescriptive remarks; advice form. |

### Letters and reflective response

| Author | Text | Source | Why it's useful |
|---|---|---|---|
| Spinoza | *Correspondence* | Bennett | Many letters open with "You asked me X" — extractable as prompt-response. |
| Seneca | *Moral Letters to Lucilius* | Gutenberg | 124 letters, each responding to a specific situation/question of Lucilius. |
| Locke | *Letter Concerning Toleration*; *Some Thoughts Concerning Education* | Bennett / Gutenberg | Sustained argument addressed to a specific recipient/topic. |
| Augustine | *Letters* (selected); *Confessions* | Gutenberg | *Confessions* is auto-dialogic (addressed to God); each book can be framed as response to a specific question. |
| Newman | *Apologia Pro Vita Sua* (1864) | Gutenberg | Sustained reflective response to specific criticism. |

### Treatises with internal opposition

| Author | Text | Source | Why it's useful |
|---|---|---|---|
| Mill | *Utilitarianism*; *On Liberty* | Gutenberg | Mill explicitly addresses anticipated objections; extract "But it might be objected..." passages as prompts. |
| Hume | *Treatise of Human Nature* | Gutenberg / Bennett | Book I particularly has anticipated objections folded in. |
| Aristotle | *Nicomachean Ethics* (Ross trans.) | Gutenberg | Each chapter walks through aporiai (puzzles) and resolves them. |

---

## Names policy (operational, settled May 12 2026)

**Policy A: strip all proper nouns from the training corpus, including dialogue-speaker names.** Each named character is replaced by a stable UGF-vocabulary descriptor (chosen per source at curation time and applied consistently across every pair drawn from that source). The descriptor functions as a single referring unit; the Reasoner never sees a proper noun.

| Source | Original name | UGF descriptor |
|---|---|---|
| Plato, *Meno* | Socrates | the old teacher |
| Plato, *Meno* | Meno | the young man |
| Plato, *Meno* | Anytus | the angry man |
| Plato, *Meno* | Boy | the young helper |
| Hume, *Dialogues* | Demea | the church man |
| Hume, *Dialogues* | Cleanthes | the man who sees plans |
| Hume, *Dialogues* | Philo | the careful one |

Other sources get their own descriptor maps at curation time. Implementation lives in each parser (`DESCRIPTOR_MAP`) and is wired into `corpus/poc/forms.py`'s `DIALOGUE_SYSTEM` rule 4.

**Why Policy A over the alternatives:**
- Maintains a strict 1K-word claim with no asterisks.
- Methodologically consistent with the original UGF parallel corpus, which already strips names.
- Turns the question of *whether descriptors come to behave like names* (rigid designation, opaque-context substitution, cross-context identity) into an **empirical post-training test** — see `memory/names_rigid_designators.md` for the three-question framework and the name-recovery experiment.
- The descriptor — being a multi-word phrase — would technically be a "name" only if it functions as one in the model's representations. Whether it does so is what we are testing, not what we are presuming.

**What it costs:** rigid-designation behavior is no longer hard-coded; if the trained Reasoner can't track identity across long contexts, that is a finding rather than a bug. The paper can argue either way: emergent rigidity is a vindication of inferentialism; failure of rigidity is a constraint on inferentialism (see `docs/followups/inferentialism.md` for the philosophy-side argument).

POC validation (Meno v2, May 12, 50 pairs): 27/50 strict-compliant (no PNs at all), 0.74 mean lexical violations, descriptor substitution robust (<1% PN slip, only sentence-initial false-positives like capitalized "Indeed").

## Teacher prompting strategy, per form

The pipeline is the same as compression-v1's `generate_reasoning.py` (teacher distillation via MindRouter ensemble, token-bucket-limited at 200 rpm), with a new per-form prompt template that *preserves* the source structure rather than collapsing it to a single essay.

### Dialogue extraction

**Input:** A passage of dialogue. Identify consecutive speaker turns.

**Output target:** `(prompt = speaker_A_turn_in_UGF, response = speaker_B_turn_in_UGF)`. Both translated by the teacher in a single call, preserving the dialogic relationship.

**Teacher prompt template (sketch):**

> The text below is a turn in a philosophical dialogue followed by the next speaker's response. Rewrite both turns using only the 1,000 most common English words ([Up Goer Five vocabulary]). Preserve the dialogic relationship: the first speaker's turn must remain a specific question, claim, or move; the second speaker's response must engage the *specific* content of the first turn, not the general topic. Output JSON: `{"prompt": "...", "response": "..."}`. First turn: ⟨A⟩. Second turn: ⟨B⟩.

**Variants:** for `Meno`-style step-by-step questioning, generate multi-turn (A → B → A → B) chains as longer training items.

### Aphorism explanation / consecutive-pair

**Input:** A numbered remark, or a pair of consecutive remarks.

**Output target:** `(prompt = "what does this mean? ⟨remark⟩" or `prompt = remark_N`, `response = remark_N+1`)`.

**Teacher prompt template:**

> Below is a short philosophical remark. Rewrite it in Up Goer Five vocabulary. Then write an Up Goer Five explanation of what the remark says, what kind of question it raises, and how a careful reader should engage it. Output JSON: `{"prompt": "⟨remark in UGF⟩", "response": "⟨engaged UGF explanation⟩"}`.

### Objection-and-reply extraction

**Input:** A passage with explicit objection + reply structure (Aquinas, Descartes-replies).

**Output target:** `(prompt = objection_in_UGF, response = reply_in_UGF)`.

**Teacher prompt template:**

> Here is an objection followed by a reply. Rewrite both in Up Goer Five. The objection must remain a specific objection — not a general topic — and the reply must engage the objection's specific claims, not just the surrounding subject matter. Output JSON: `{"prompt": "⟨objection in UGF⟩", "response": "⟨engaged reply in UGF⟩"}`. Objection: ⟨text⟩. Reply: ⟨text⟩.

### Letter / response-to-frame

**Input:** A letter (or letter-like passage) with an identifiable triggering question.

**Output target:** `(prompt = paraphrased_recipient_situation, response = letter_content_in_UGF)`.

**Teacher prompt template:**

> The text below is a letter from a philosopher responding to a specific question or situation from the recipient. First, write the recipient's question or situation in Up Goer Five, phrased as a question. Second, rewrite the philosopher's response in Up Goer Five, preserving the way it engages the recipient's specific question. Output JSON: `{"prompt": "...", "response": "..."}`. Recipient context: ⟨derived⟩. Letter: ⟨text⟩.

### Treatise sub-argument with anticipated objection

**Input:** A passage from a treatise where the author addresses an anticipated objection ("It might be said...", "Some will argue...").

**Output target:** `(prompt = anticipated_objection_in_UGF, response = author_response_in_UGF)`.

---

## Target form mix

| Form | Share | Rationale |
|---|---:|---|
| Dialogue | 30% | Highest prompt-attention training value; closest to the deficit's failure mode. |
| Objection-and-reply | 20% | Explicit position-tracking; complements dialogue. |
| Aphorism / explained | 15% | Trains response to compact declarative seeds (not just topic phrases). |
| Letter / response-to-frame | 15% | Trains response to a specific interlocutor's specific question. |
| Treatise sub-argument | 10% | Inherits some v1-style essay shape while still embedded in opposition. |
| Preserved v1 essays | 10% | Keeps continuity with the v1 distribution; lets us measure what shifts. |

A 500K-trace corpus at this mix gives ~150K dialogue, ~100K objection-reply, ~75K each aphorism and letter, ~50K each treatise and v1-style. Each well-populated; none degenerate.

---

## Two paths to use the new corpus

### Path A — Continue-train v1 (cheap, fast experiment)

Take the existing `reasoner_sft_v1/final.pt` checkpoint. SFT for ~10K additional steps on the new form-diverse corpus. Test on stress bench and patched-cx. Measures directly whether form diversity closes the prompt-attention deficit. **Cost:** ~2 days on `fortyfive`. **Risk:** mixed prior — the model still bears its v1 form-prior; may need more steps.

### Path B — Train fresh from scratch (clean experiment for paper)

Generate 500K form-diverse traces. Train a fresh 200M model end-to-end. Compare against compression-v1 directly. **Cost:** ~3 weeks of compute. **Payoff:** clean comparison; either confirms form diversity as the cure or rules it out.

Path A first as a one-day proof of concept; Path B if the proof of concept lands.

---

## Production pipeline (built May 12 2026)

The campaign pipeline is now live in the repo. Five components:

| Component | Location | Purpose |
|---|---|---|
| Per-form prompts + few-shot + correction | `corpus/generation/forms.py` | Prompt registry — `FORMS["dialogue"]`, `FORMS["objection_reply"]`, `FORMS["skeptical_mode"]`. Each has a system prompt, user template, 2 few-shot exemplars, and a correction template for retries. |
| Source-text parsers | `corpus/poc/parse_{meno,hume,aquinas,sextus}.py` | Each parses a Project Gutenberg source into pair JSONL. `--all` for full extraction; `--limit N` for testing. Descriptor maps for proper-noun stripping live here. |
| Source registry | `corpus/generation/forms_sources.yaml` | Lists each parsed JSONL with its label and form. |
| Production runner | `corpus/generation/generate_forms.py` | Multi-teacher dispatch, token-bucket-limited, retry-on-violations, JSON-discipline retry, progress tracking, resumable. Output schema: `{id, form, source, prompt, response, teacher, compliant, remaining_violations, metadata}`. |
| SLURM submission | `slurm/generate_forms_corpus.sbatch` | CPU-only (all compute is at MR). Default 2-day wall time. Regenerates source JSONLs if missing. |

### Available pairs (as of May 12)

| Source | Form | Pairs available |
|---|---|---:|
| Plato, *Meno* | dialogue | 195 |
| Hume, *Dialogues* | dialogue | 41 |
| Aquinas, *Summa* I | objection_reply | 1,678 |
| Sextus, *Outlines* I (via Patrick) | skeptical_mode | 22 |
| **Total** | | **1,936** |

This is enough for a Phase 1 Path A run. Scaling toward 50K (full Path A) or 500K (Path B) requires additional source-text parsers. Highest-value next additions: rest of Plato's dialogues (Apology, Crito, Phaedo, Symposium, Republic, Theaetetus, Sophist — all Jowett-PD), Berkeley's *Three Dialogues*, Descartes' *Meditations* + *Objections and Replies*, rest of Aquinas' *Summa* (II, II-II, III).

### Local validation (May 12)

A 25-pairs-per-source dry run (~97 total) was used to verify the production pipeline end-to-end. The runner correctly:
- Loads multiple source JSONLs and tags each pair with its form
- Routes each pair to a teacher per the weighted ensemble
- Applies form-specific system prompt + few-shot + user message
- Retries on JSON-parse failure with a clarifying message
- Retries on UGF-violation with form-specific correction prompt (up to 3 retries)
- Writes progress incrementally; resumes from `forms_progress.json` on restart
- Outputs UGF (prompt, response) pairs to `ugf_forms_corpus.jsonl` with full provenance

### Run commands

```bash
# 1. Generate source-pair JSONLs (full extraction)
python3 corpus/poc/parse_meno.py --all
python3 corpus/poc/parse_hume.py --all
python3 corpus/poc/parse_aquinas.py --all
python3 corpus/poc/parse_sextus.py --all

# 2. Smoke test (small subset; fast feedback)
python3 corpus/generation/generate_forms.py \
    --sources corpus/generation/forms_sources.yaml \
    --output corpus/processed/ugf_forms_corpus.jsonl \
    --progress corpus/processed/forms_progress.json \
    --limit-per-source 25

# 3. Full Phase 1 run (all ~1,936 pairs through teacher)
python3 corpus/generation/generate_forms.py \
    --sources corpus/generation/forms_sources.yaml \
    --output corpus/processed/ugf_forms_corpus.jsonl \
    --progress corpus/processed/forms_progress.json

# 4. On fortyfive (long-running, resumable)
sbatch slurm/generate_forms_corpus.sbatch
```

The progress file's `completed_ids` makes the run resume-safe — kill-and-restart skips already-completed pairs.

### Output schema

Each line of `corpus/processed/ugf_forms_corpus.jsonl`:

```json
{
  "id": "meno_pair_001",
  "form": "dialogue",
  "source": "plato_meno",
  "prompt": "...",
  "response": "...",
  "teacher": "openai/gpt-oss-120b",
  "compliant": true,
  "remaining_violations": [],
  "metadata": {
    "speaker_a": "MENO", "speaker_b": "SOCRATES",
    "descriptor_a": "the young man", "descriptor_b": "the old teacher",
    "turn_a": "...", "turn_b": "..."
  }
}
```

This schema is forward-compatible with the existing Reasoner data loader's `{prompt, response}` expectation. The `metadata` field carries provenance for audit / form-balance analyses without affecting training.

---

## Effort estimate (Path A)

| Phase | Effort |
|---|---|
| Text curation (download, clean, segment by form) | 1 week |
| Per-form teacher prompt templates + extraction scripts | 2–3 days |
| Corpus generation (~500K traces at 200 rpm) | ~1 week |
| QA + form-balance audit | 2 days |
| SFT continuation run | 2 days |
| Eval on stress + patched-cx | 1 day |
| **Total** | **~3–4 weeks** |

---

## Dependencies

- Existing `corpus/generation/generate_reasoning.py` pipeline (teacher distillation, token bucket, retry logic). Works as-is; needs only a new per-form prompt template module.
- Thread A (calibration) ideally landed before the SFT-continuation eval, so the comparison numbers are ratified.
- Compute access to `fortyfive` and MindRouter capacity at the 200 rpm cap.

## How this changes the broader plan

- **Thread B2** ("second SFT pass with diverse prompt forms") is now this. The diversification target is *philosophical form*, not just prompt-form templates.
- **Thread D** (2D scaling) should run on this corpus, not the v1 corpus. Otherwise every cell of the (params × vocab) grid inherits the v1 deficit, and the substitutability claim becomes contestable.
- **Thread H** (inferentialism) gains a stronger empirical anchor: a Plato-trained Reasoner is *literally* inferentialism caught in the act — the Socratic interlocutor's whole job is to track inferential commitments. See `inferentialism.md` for the connection.
- **Thread I** (multi-domain) inherits the methodology: each new cognitive domain wants its own form-diverse source-text catalog.

## Why this is the right next move

Highest leverage among the open threads:

1. It potentially fixes the prompt-attention deficit — the biggest known weakness of compression-v1.
2. It strengthens the inferentialist reading (Socratic dialogue as test apparatus).
3. It improves any subsequent scaling work — the 2D scan deserves a corpus that isn't crippled at the start.
4. It's cheap relative to D (one corpus generation vs. nine training runs).
5. The infrastructure is in place (teacher distillation, rate limiter, subagent eval).
6. The intellectual payoff is unusually clean: it turns the prompt-attention deficit from a "to-be-debugged limitation" into a "diagnosed and addressed by training-corpus design" — a much better paper.

## What to write into paper G's Future Work

> **Form-diverse retraining.** The prompt-attention deficit appears to be a function of training-corpus form rather than vocabulary or model size. A continuation pass on a corpus drawn from canonical philosophical forms — Platonic dialogue, Aquinas-style objection-and-reply, aphorism, philosophical correspondence — would address the deficit directly. The full plan is in `docs/followups/corpus-diversification.md`.
