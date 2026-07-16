"""
Length-match gate for the form-controlled retrain (docs/form-retrain-clean-design-2026-06-03.md).

The clean design varies form and holds response length fixed. The May-24 pilot failed
exactly here -- form responses ran ~49 words against the essays' ~317 -- so "form" and
"length" were confounded and the result meant nothing. This script is the gate that
keeps that from happening again. Two jobs:

  1. PRE-FLIGHT -- measure the essay arm and print the --target-words value to hand to
     generate_form_attentive.py. The design doc's "~317w median" is prose, not a
     measurement; measure it.

         python3 -m corpus.generation.check_length_match \
             --essay corpus/processed/ugf_n_sft_400k.jsonl

  2. GATE -- after the form campaign, compare the two arms and decide whether the pair
     is clean enough to train. Exits non-zero if not, and writes the offending ids so
     they can be regenerated/trimmed (the design's "verification + top-up" stage).

         python3 -m corpus.generation.check_length_match \
             --essay corpus/processed/ugf_n_sft_400k.jsonl \
             --form  corpus/processed/ugf_form_n.jsonl \
             --outliers corpus/processed/form_length_outliers.json

Reads n_words when present (the form arm records it), otherwise counts words, so it
works against the older essay corpus unchanged.
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
    ap.add_argument("--outliers", help="write ids outside the band here, for top-up")
    ap.add_argument("--tolerance", type=float, default=0.05,
                    help="max |median difference| as a fraction of the essay median (default 0.05)")
    ap.add_argument("--band", type=float, default=0.2,
                    help="a record is an outlier outside +/- this fraction of the essay median "
                         "(default 0.2)")
    ap.add_argument("--max-band-gap", type=float, default=0.1,
                    help="max gap between the form and essay arms' in-band fractions (default 0.1). "
                         "Judged against the essay arm's own in-band rate, not an absolute: the "
                         "essay arm is the thing we are matching, so it defines the target spread.")
    args = ap.parse_args()

    essay, _ = load_lengths(args.essay)
    e = describe("essay arm", essay)

    if not args.form:
        print(f"\nPre-flight: pass --target-words {round(e['median'])} to generate_form_attentive.py")
        return 0

    form, form_by_id = load_lengths(args.form)
    f = describe("form arm", form)

    lo, hi = (1 - args.band) * e["median"], (1 + args.band) * e["median"]
    form_in_band = sum(1 for n in form if lo <= n <= hi) / len(form)
    # Reference the essay arm's own in-band rate. An absolute threshold would be
    # arbitrary and can reject a perfectly matched arm: for the real corpus spread a
    # +/-20% band is only ~1 sigma, so even the essay arm scores ~70% against itself.
    essay_in_band = sum(1 for n in essay if lo <= n <= hi) / len(essay)
    band_gap = abs(form_in_band - essay_in_band)
    drift = (f["median"] - e["median"]) / e["median"]

    print(f"\nmedian drift   {drift:+.1%}  (tolerance +/-{args.tolerance:.0%})")
    print(f"band {lo:.0f}-{hi:.0f} words: essay {essay_in_band:.1%} vs form {form_in_band:.1%} "
          f"-> gap {band_gap:.1%}  (max {args.max_band_gap:.0%})")

    outliers = sorted(i for i, n in form_by_id.items() if not (lo <= n <= hi))
    if args.outliers:
        Path(args.outliers).parent.mkdir(parents=True, exist_ok=True)
        Path(args.outliers).write_text(json.dumps(outliers, indent=2))
        print(f"wrote {len(outliers)} outlier ids -> {args.outliers}")

    ok = abs(drift) <= args.tolerance and band_gap <= args.max_band_gap
    # The whole experiment turns on this: if the arms differ in length as well as form,
    # a null is uninterpretable and the ~1 week of GPU/MR spend buys nothing.
    print("\nGATE: " + ("PASS -- arms are length-matched; cleared to train."
                        if ok else
                        "FAIL -- arms are NOT length-matched. Top up the outliers and "
                        "re-run before training; training now would re-confound form with length."))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
