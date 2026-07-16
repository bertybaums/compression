"""
Length gate + dilation measurement for the form-controlled retrain
(docs/form-retrain-clean-design-2026-06-03.md, incl. the July 16 second amendment).

The clean design varies form while keeping length from confounding the comparison.
The May-24 pilot failed exactly here -- form responses ran ~49 words against the
essays' ~285-317 -- so "form" and "length" were confounded and the result meant
nothing. Policy (July 16): the form arm is generated NATURAL (no length
instruction -- a word target would condition on a mediator, break arm symmetry,
and leave an artifact in the stored training prompts). Length is therefore
MEASURED here, and any dilation is handled at training time by token-budget
equalization. Three jobs:

  1. PRE-FLIGHT -- describe the essay arm (its median feeds the generator's
     --reference-median monitoring flag):

         python3 -m corpus.generation.check_length_match \
             --essay corpus/processed/ugf_n_sft_400k.jsonl

  2. DILATION -- with both arms present, join records by id and report the
     within-prompt dilation ratio (form words / essay words for the SAME prompt).
     This is the empirical quantity of interest in its own right: the lexical
     restriction dilates expression (v1); does prompt-specific engagement dilate
     it further? A discourse-level instance of the Sheffer-stroke point.

  3. GATE -- decide whether the pair is trainable. Direction-aware:
       - form median SHORT of essay median by >5%  -> FAIL (May-24 failure mode:
         short-turn corpus, length confounded downward).
       - form median LONG by >50%                  -> FAIL (extreme dilation;
         stop and decide with the data in hand -- dilation may be the headline).
       - otherwise                                 -> PASS. If long by >5%, the
         token-equalization factor to apply at training time is printed
         (shrink the form arm's example count so total training tokens match).
     Spread/dispersion mismatch WARNS but never fails (decided July 16): a
     tighter-but-centered form arm does not reproduce the May-24 confound.

         python3 -m corpus.generation.check_length_match \
             --essay corpus/processed/ugf_n_sft_400k.jsonl \
             --form  corpus/processed/ugf_form_pilot.jsonl

Reads n_words when present (the form arm records it), otherwise counts words, so
it works against the older essay corpus unchanged.
"""
import argparse
import json
import statistics
import sys
from pathlib import Path


def load_lengths(path: str) -> tuple[list[int], dict[str, int]]:
    """-> (all lengths, {id: n_words}). Skips records with no usable response."""
    lengths: list[int] = []
    by_id: dict[str, int] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            n = d.get("n_words")
            if n is None:
                resp = d.get("response")
                if not resp:
                    continue
                n = len(resp.split())
            lengths.append(n)
            if d.get("id") is not None:
                by_id[d["id"]] = n
    return lengths, by_id


def describe(label: str, ns: list[int]) -> dict:
    ns = sorted(ns)
    n = len(ns)
    if n == 0:
        sys.exit(f"{label}: no usable records")
    d = {
        "n": n,
        "median": statistics.median(ns),
        "mean": round(statistics.fmean(ns), 1),
        "p10": ns[n // 10], "p25": ns[n // 4],
        "p75": ns[3 * n // 4], "p90": ns[9 * n // 10],
    }
    print(f"{label:12} n={d['n']:>7}  median={d['median']:>6}  mean={d['mean']:>7}  "
          f"p10={d['p10']:>5}  p25={d['p25']:>5}  p75={d['p75']:>5}  p90={d['p90']:>5}")
    return d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--essay", required=True, help="essay arm (control) jsonl")
    ap.add_argument("--form", help="form arm (treatment) jsonl; omit for pre-flight measurement")
    ap.add_argument("--short-tolerance", type=float, default=0.05,
                    help="FAIL if the form median falls SHORT of the essay median by more than "
                         "this fraction (default 0.05) -- the May-24 failure mode")
    ap.add_argument("--max-dilation", type=float, default=0.5,
                    help="FAIL if the form median runs LONG by more than this fraction "
                         "(default 0.5) -- stop and decide with the data in hand")
    ap.add_argument("--band", type=float, default=0.2,
                    help="dispersion report band, +/- this fraction of the essay median "
                         "(default 0.2); WARNING only, never fails the gate")
    args = ap.parse_args()

    essay, essay_by_id = load_lengths(args.essay)
    e = describe("essay arm", essay)

    if not args.form:
        print(f"\nPre-flight: essay median = {round(e['median'])}. Pass "
              f"--reference-median {round(e['median'])} to generate_form_attentive.py "
              f"(monitoring only -- the form arm is generated natural).")
        return 0

    form, form_by_id = load_lengths(args.form)
    f = describe("form arm", form)

    drift = (f["median"] - e["median"]) / e["median"]

    # Within-prompt dilation: same prompt id in both arms -> form/essay word ratio.
    shared = sorted(set(form_by_id) & set(essay_by_id))
    if shared:
        ratios = sorted(form_by_id[i] / essay_by_id[i] for i in shared if essay_by_id[i] > 0)
        n = len(ratios)
        print(f"\nwithin-prompt dilation (form/essay, {n} shared prompts):")
        print(f"  median={statistics.median(ratios):.3f}  mean={statistics.fmean(ratios):.3f}  "
              f"p10={ratios[n // 10]:.3f}  p25={ratios[n // 4]:.3f}  "
              f"p75={ratios[3 * n // 4]:.3f}  p90={ratios[9 * n // 10]:.3f}")
    else:
        print("\nno shared prompt ids between arms -- dilation not computable "
              "(aggregate medians only)")

    # Dispersion: report-only. The essay arm's own in-band rate is the reference
    # (an absolute threshold rejects perfectly matched arms -- at the real corpus
    # spread a +/-20% band is well under one sigma).
    lo, hi = (1 - args.band) * e["median"], (1 + args.band) * e["median"]
    essay_in_band = sum(1 for x in essay if lo <= x <= hi) / len(essay)
    form_in_band = sum(1 for x in form if lo <= x <= hi) / len(form)

    print(f"\nmedian drift   {drift:+.1%}  "
          f"(fail if < -{args.short_tolerance:.0%} or > +{args.max_dilation:.0%})")
    print(f"dispersion     band {lo:.0f}-{hi:.0f}w: essay {essay_in_band:.1%} vs "
          f"form {form_in_band:.1%}", end="")
    if abs(form_in_band - essay_in_band) > 0.1:
        print("  [WARNING: spread differs -- report it in the paper; does not fail the gate]")
    else:
        print()

    if drift < -args.short_tolerance:
        print("\nGATE: FAIL -- form arm is systematically SHORT of the essay arm "
              "(the May-24 confound). Do not train; inspect the pointed templates.")
        return 1
    if drift > args.max_dilation:
        print("\nGATE: FAIL -- extreme dilation. Stop and decide with the data in hand; "
              "at this size the dilation itself may be the finding.")
        return 1

    print("\nGATE: PASS.", end=" ")
    if drift > args.short_tolerance:
        factor = e["mean"] / f["mean"]
        print(f"Form arm dilates {drift:+.1%}: equalize total training tokens by "
              f"sampling ~{factor:.3f} x the form arm's example count "
              f"(~{round(factor * len(form)):,} of {len(form):,} examples), and report "
              f"the dilation as a result.")
    else:
        print("Arms are length-matched naturally; train on full example counts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
