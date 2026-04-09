# Compression

**Expressive Adequacy of a Radically Constrained Vocabulary for Philosophical Reasoning**

## Core Question

Is the ~1,000-word Up Goer Five fragment of English (Munroe's *Thing Explainer*) expressively adequate for reasoning about practical philosophy -- logic, critical thinking, decision theory, game theory, and ethics?

The analogy is the Sheffer stroke: NAND gives you a smaller alphabet at the cost of longer formulas, but loses nothing in expressive power. This project asks whether ~1,000 common English words can do the same for natural-language philosophical reasoning, and what the "sentence length cost" looks like empirically.

## Approach

Two models, trained from scratch or fine-tuned, evaluated via automated round-trip fidelity:

### Translator
- Fine-tuned T5-small (60M params)
- Bidirectional: full English <-> Up Goer Five (UGF)
- Constrained decoding (logits mask) ensures English->UGF output uses only UGF vocabulary
- Purpose: bridge between the outside world and the vocabulary-constrained Reasoner

### Reasoner
- From-scratch 1.5B parameter Llama-style decoder-only transformer
- Custom word-level tokenizer with **only** ~3,643 tokens (inflected forms of the 1,000 most common English words + punctuation + special tokens)
- Both input and output constrained to UGF vocabulary
- Architecture: RMSNorm, RoPE, SwiGLU, Grouped Query Attention
- The existence proof: if this model can faithfully reason about philosophy, the UGF fragment is expressively adequate

### Evaluation
Round-trip fidelity (no humans in the loop):
1. English -> Translator -> UGF
2. UGF -> Reasoner (generates reasoning) -> UGF
3. UGF -> Translator -> English
4. Compare output to original via BERTScore, NLI entailment, cosine similarity

## Training Data

Teacher pipeline using gpt-oss-120b (via MindRouter) and Claude:

- **Parallel corpus**: ~262K English passages from two philosophy projects, each translated to UGF with vocabulary validation
- **Reasoning traces**: Pure UGF chain-of-thought, explanations, Socratic dialogues, argument analyses

Source material:
- [good-thinking-bot](https://github.com/bertybaums/good-thinking-bot): 27,252 training records across 182 taxonomy codes covering logic, decision theory, game theory, cognitive biases, Dennett's thinking tools
- Intro ethics textbook manuscript: virtue ethics (Aristotle), justice (Rawls), deontology (Kant), utilitarianism, care ethics, AI ethics, Dennett's moral first aid

## Vocabulary

The Up Goer Five word list: the 1,000 most common English lemmas, expanded to ~3,616 inflected forms (walk/walked/walking are separate tokens), plus punctuation, numerals, and 5 special tokens. Total vocabulary: **3,643 tokens**.

Source: [XKCD Simple Writer](https://xkcd.com/simplewriter/) (v0.2.1)

Notable absences from the vocabulary: *false*, *argument*, *premise*, *conclusion*, *fallacy*, *probability*, *utility*, *equilibrium*, *ethics*, *moral*, *virtue*, *rational*, *cognitive*, *bias*. The model must describe all of these using only the allowed words.

## Project Structure

```
compression/
  pyproject.toml              # Package config with optional deps
  wordlist/
    curate_wordlist.py        # Extract + curate the UGF vocabulary
    vocab_final.json          # Canonical {token: id} mapping (3,643 tokens)
    vocab_words_only.txt      # Plain text word list for inspection
  tokenizer/
    ugf_tokenizer.py          # HuggingFace PreTrainedTokenizer implementation
    test_tokenizer.py         # 18 unit tests
  corpus/
    generation/
      extract_sources.py      # Extract passages from source projects
      generate_parallel.py    # Async English->UGF translation via API
      generate_reasoning.py   # Pure UGF reasoning trace generation
      validate_ugf.py         # Vocabulary validation + unicode normalization
      config.yaml             # API endpoints, concurrency settings
    processed/                # Generated JSONL files (gitignored)
  translator/
    model.py                  # T5-small + StateMachineLogitsProcessor
    train.py                  # Fine-tuning loop
  reasoner/
    model.py                  # 1.5B Llama-style transformer (from scratch)
    data.py                   # UGF dataset + dataloader
    train.py                  # Training loop (AMP, grad checkpoint, cosine LR)
  eval/                       # Round-trip evaluation pipeline (TODO)
  configs/
    translator.yaml
    reasoner.yaml
  slurm/
    setup_env.sh              # HPC venv setup
    run_parallel_gen.sh       # Corpus generation (login node, tmux)
    run_reasoning_gen.sh      # Reasoning trace generation
    train_translator.sbatch   # GPU job: translator fine-tuning
    train_reasoner.sbatch     # GPU job: reasoner training (~3-5 days)
```

## Infrastructure

- **HPC**: fortyfive.hpc.uidaho.edu (RTX A6000, SLURM gpu-8 partition)
- **Teacher API**: MindRouter (campus HPC, OpenAI-compatible, gpt-oss-120b)
- **Compute budget**: Single A6000 (48GB) for training

## Status

- [x] Vocabulary curation (3,643 tokens from XKCD Simple Writer)
- [x] Custom word-level tokenizer with validation
- [x] Source material extraction (262K passages)
- [x] Parallel corpus generation pipeline (running on HPC)
- [x] Reasoner architecture (1.425B params, tested)
- [x] Translator architecture (T5-small + constrained decoding)
- [x] Training loops for both models
- [x] SLURM job scripts
- [ ] Parallel corpus generation (in progress, ~3K/262K)
- [ ] UGF reasoning trace generation
- [ ] Translator training
- [ ] Reasoner training
- [ ] Evaluation pipeline
- [ ] Round-trip fidelity experiments
- [ ] Paper

## License

TBD
