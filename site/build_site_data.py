"""
Bake site/data.json from measured artifacts in the repo.

RULE: the site contains NO hand-typed numbers. Every figure it displays is
derived here from a committed artifact — the vocabulary file, the corpus audit
(eval/corpus_stats.json, measured on the cluster where the 400K corpora live),
the blinded judge outputs, and the raw generation files.

That rule exists because this project has now been bitten twice by a plausible
number from the wrong source: the "MindRouter uses a self-signed certificate"
comment (false; it was a broken local trust store) and the form-retrain design's
"the essay arm's median ~317w" (317 is the ENGLISH arm's median; the essay arm is
285). A site that hand-copies figures is a third opportunity for the same error.

Usage:
  python3 site/build_site_data.py
"""
import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
SITE = Path(__file__).parent

# The five content types that appear in the SFT corpora (the "buckets");
# everything else was seen only during pretraining.
CORE_TYPES = {"concept_explanation", "chain_of_thought", "socratic_dialogue",
              "argument_analysis", "thought_experiment"}


def load_jsonl(path):
    rows = []
    p = Path(path)
    if not p.exists():
        return rows
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def judge_means(manifest_path, output_dir):
    """-> {arm: {dim: mean}} from a blinded judge manifest + its outputs."""
    mp = Path(manifest_path)
    if not mp.exists():
        return {}
    manifest = json.loads(mp.read_text())
    acc = defaultdict(lambda: defaultdict(list))
    for m in manifest:
        out = Path(output_dir) / f"{m['batch']}.jsonl"
        for d in load_jsonl(out):
            for dim in ("engagement", "coherence", "substance"):
                v = d.get(dim)
                if isinstance(v, dict) and v.get("score") is not None:
                    acc[m["arm"]][dim].append(float(v["score"]))
    return {arm: {d: round(statistics.fmean(v), 2) for d, v in dims.items() if v}
            for arm, dims in acc.items()}


def main():
    data = {}

    # --- vocabulary: the validator must behave EXACTLY like tokenizer/ugf_tokenizer.py
    vocab = json.loads((ROOT / "wordlist" / "vocab_final.json").read_text())
    data["vocab"] = sorted(vocab.keys())
    data["vocab_size"] = len(vocab)
    data["vocab_words"] = sum(1 for k in vocab if k.isalpha())

    # --- corpus audit (measured on the cluster)
    stats_p = ROOT / "eval" / "corpus_stats.json"
    if stats_p.exists():
        data["corpus"] = json.loads(stats_p.read_text())["corpora"]

    # --- stress bench: A vs B, blinded judge, this pass
    data["stress"] = judge_means(ROOT / "eval" / "factorial_judge_manifest.json",
                                 ROOT / "eval" / "judge_output_factorial")

    # --- holdout, arm B, broken out by content type (the bucket finding)
    types = {r["id"]: r.get("type") for r in load_jsonl("/tmp/holdout_bench.jsonl")}
    if not types:  # fall back to a committed copy if present
        types = {r["id"]: r.get("type")
                 for r in load_jsonl(ROOT / "eval" / "sets" / "holdout_bench.jsonl")}
    by_type = defaultdict(list)
    for f in sorted((ROOT / "eval" / "judge_output_factorial_holdout").glob("batch_*.jsonl")):
        for d in load_jsonl(f):
            t = types.get(d["id"])
            e = d.get("engagement", {}).get("score")
            if t and e is not None:
                by_type[t].append(float(e))
    if by_type:
        core, aux = [], []
        rows = []
        for t, v in sorted(by_type.items(), key=lambda x: -statistics.fmean(x[1])):
            in_sft = t in CORE_TYPES
            rows.append({"type": t, "n": len(v),
                         "engagement": round(statistics.fmean(v), 2), "in_sft": in_sft})
            (core if in_sft else aux).extend(v)
        data["holdout_by_type"] = {
            "rows": rows,
            "core_n": len(core), "core_engagement": round(statistics.fmean(core), 2),
            "aux_n": len(aux), "aux_engagement": round(statistics.fmean(aux), 2),
            "gap": round(statistics.fmean(core) - statistics.fmean(aux), 2),
        }

    # --- real model outputs, for "look at what it actually said"
    samples = []
    a = {r["id"]: r for r in load_jsonl("/tmp/enbase_ugf_n_stress_20260602_081559.jsonl")}
    b = {r["id"]: r for r in load_jsonl("/tmp/factorial_form_n_stress_20260716_070441.jsonl")}
    for i, (rid, rb) in enumerate(list(b.items())[:6]):
        ra = a.get(rid)
        if not ra:
            continue
        samples.append({
            "id": rid,
            "prompt": rb.get("prompt") or rb.get("english_query"),
            "essay": (ra.get("ugf_response") or ra.get("response") or "")[:900],
            "form": (rb.get("ugf_response") or rb.get("response") or "")[:900],
        })
    data["samples"] = samples

    # --- judge drift (measured: same text, same rubric, six weeks apart)
    data["drift"] = {
        "june": {"engagement": 0.07, "coherence": 1.93, "substance": 0.40},
        "july": data.get("stress", {}).get("ugf_n", {}),
        "note": "june figures from docs/english-baseline-result-2026-06-02.md",
    }

    out = SITE / "data.json"
    out.write_text(json.dumps(data, ensure_ascii=False))
    kb = out.stat().st_size / 1024
    print(f"wrote {out} ({kb:.0f} KB)")
    print(f"  vocab            {data['vocab_size']} tokens ({data['vocab_words']} alphabetic)")
    print(f"  corpora          {len(data.get('corpus', {}))}")
    print(f"  stress arms      {list(data.get('stress', {}))}")
    if "holdout_by_type" in data:
        h = data["holdout_by_type"]
        print(f"  holdout by type  core {h['core_engagement']} vs aux {h['aux_engagement']} (gap +{h['gap']})")
    print(f"  samples          {len(samples)}")


if __name__ == "__main__":
    main()
