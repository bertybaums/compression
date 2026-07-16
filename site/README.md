# Doing Philosophy in a Thousand Words — public site

Static, self-contained, no backend. Every figure is generated from the repo's data
files by `build_site_data.py`; nothing is typed by hand.

## Build + run

    python3 site/build_site_data.py     # regenerates site/data.json
    cd site && python3 -m http.server   # then open http://localhost:8000

`build_site_data.py` reads:
- `wordlist/vocab_final.json` — the word list the in-page validator uses
- `eval/corpus_stats.json` — corpus audit (generated on the cluster, where the 400K corpora live)
- `eval/judge_output_factorial*/` + manifests — blinded judge scores
- the raw generation files for real sample outputs

## The rule

**No hand-typed numbers.** This project has been bitten twice by a plausible figure
from the wrong source: the "MindRouter uses a self-signed certificate" comment (false —
it was a broken local trust store) and the design doc's "the essay arm's median ~317w"
(317 is the *English* arm's median; the essay arm is 285). A site that copies numbers by
hand is a third opportunity for the same error. Regenerate `data.json` instead.

## Validator parity

`app.js` reimplements `tokenizer/ugf_tokenizer.py`'s `validate()` in JS — same regex
(`[a-zA-Z]+(?:'[a-zA-Z]+)*|\d|\n|\S`), same rule (violation unless `raw.lower()` or
`raw` is in vocab), same unicode normalization. Verified byte-identical against the
Python implementation on 10 cases incl. smart quotes, digits, symbols, contractions.
**If you change either implementation, re-check parity** — otherwise the page starts
lying about the constraint it is teaching.

## Deploying

Static, so either works:
- into `thinking/` at `/thousand-words` (nginx sidecar pattern) — Ameliorative Move 2
- GitHub Pages, mirroring the pluto-toy precedent

## Status

Sections 1–7 are complete and use real measured results. Section 7's closing claim
(arm C — does prompt diversity fix it?) is live at time of writing; update once it lands.
