"""
Build a fuller Layer-2 evaluation report (Markdown) from Reasoner-pipeline
and Comparator outputs on the same benchmark.

Beyond the side-by-side comparison from build_comparison_md.py, this report adds:
  - Executive summary + setup
  - Aggregate stats (counts, length distributions, latency)
  - Per-type summary tables
  - Full pipeline detail per item, including the SFT-template-wrapped
    prompt the Reasoner actually saw
  - Notes section with placeholders for human observations

Usage:
  python -m eval.build_report \\
      --reasoner   eval/results/logic_bench_<ts>.jsonl \\
      --comparator eval/results/comparator_logic_textbook_<ts>_with_english.jsonl \\
      --bench      eval/sets/logic_textbook_bench.jsonl \\
      --out        eval/results/report_<ts>.md
"""

import argparse
import json
import statistics
import time
from pathlib import Path
from collections import defaultdict


def load_jsonl(path):
    return [json.loads(l) for l in open(path) if l.strip()]


def words(s):
    if not s or s.startswith("<"):
        return 0
    return len(s.split())


def fmt_kv_table(rows):
    """rows = list of (label, value)"""
    out = ["| metric | value |", "|---|---|"]
    for label, value in rows:
        out.append(f"| {label} | {value} |")
    return "\n".join(out)


def render(reasoner_items, comparator_items, bench_items, out_path):
    r_by_id = {x["id"]: x for x in reasoner_items}
    c_by_id = {x["id"]: x for x in comparator_items}
    b_by_id = {x["id"]: x for x in bench_items}
    common_ids = sorted(set(r_by_id) & set(c_by_id) & set(b_by_id))

    by_type = defaultdict(list)
    for iid in common_ids:
        by_type[r_by_id[iid].get("type", "unknown")].append(iid)
    sorted_types = sorted(by_type.keys())

    # Aggregate stats
    r_eng_lens = [words(r_by_id[i].get("english_response", "")) for i in common_ids]
    c_eng_lens = [words(c_by_id[i].get("english_response", "")) for i in common_ids]
    r_ugf_lens = [words(r_by_id[i].get("ugf_response", "")) for i in common_ids]
    c_ugf_lens = [words(c_by_id[i].get("ugf_response", "")) for i in common_ids]
    r_latencies = [r_by_id[i].get("latency_s", 0.0) for i in common_ids]
    c_latencies = [c_by_id[i].get("comparator_latency_s", 0.0) for i in common_ids]

    # "Empty/short response" indicator (under 20 words English)
    r_short = sum(1 for n in r_eng_lens if n < 20)
    c_short = sum(1 for n in c_eng_lens if n < 20)

    def stats(xs):
        if not xs:
            return "n/a"
        return f"min={min(xs):.0f}  median={statistics.median(xs):.0f}  mean={statistics.mean(xs):.0f}  p90={sorted(xs)[int(0.9*len(xs))]:.0f}  max={max(xs):.0f}"

    L = []
    L.append("# Layer-2 evaluation report: Reasoner pipeline vs. teacher-in-UGF comparator")
    L.append("")
    L.append(f"_Generated {time.strftime('%Y-%m-%d %H:%M:%S')}_")
    L.append("")

    L.append("## Executive summary")
    L.append("")
    L.append("This report compares two pipelines on the same 115-item logic textbook benchmark:")
    L.append("")
    L.append("- **Reasoner pipeline**: English question → Translator(English→UGF) → wrap in CONTENT_TYPES template → 200M from-scratch SFT Reasoner → UGF response → Translator(UGF→English) → English response")
    L.append("- **Teacher-in-UGF comparator**: English question → `gpt-oss-120b` on MindRouter (UGF system prompt + 2 few-shot exemplars) → UGF response → Translator(UGF→English) → English response")
    L.append("")
    L.append("The benchmark is drawn from Van Cleave, *Introduction to Logic and Critical Thinking v2.0* (CC-BY 4.0). 9 categories, 10–15 items each, all in plain English. Per-item textbook expected answers are provided.")
    L.append("")

    L.append("## Setup")
    L.append("")
    L.append(fmt_kv_table([
        ("benchmark items", str(len(common_ids))),
        ("benchmark types", str(len(sorted_types))),
        ("Reasoner checkpoint", "checkpoints/reasoner_sft_v1/final.pt (step 30000, post-SFT)"),
        ("Comparator model", "openai/gpt-oss-120b on MindRouter (reasoning_effort=medium, temperature=0.7)"),
        ("Translator", "checkpoints/translator/best (T5-small fine-tuned, val_loss 0.88)"),
        ("Reasoner generation params", "max_new_tokens=300, temperature=0.8, top_k=50, top_p=0.9"),
    ]))
    L.append("")

    L.append("## Aggregate statistics")
    L.append("")
    L.append("### Counts")
    L.append("")
    L.append(fmt_kv_table([
        ("items in both pipelines", str(len(common_ids))),
        ("Reasoner short responses (<20 words)", f"{r_short} of {len(common_ids)} ({100*r_short/len(common_ids):.0f}%)"),
        ("Comparator short responses (<20 words)", f"{c_short} of {len(common_ids)} ({100*c_short/len(common_ids):.0f}%)"),
    ]))
    L.append("")
    L.append("### English response length (words)")
    L.append("")
    L.append(fmt_kv_table([
        ("Reasoner pipeline", stats(r_eng_lens)),
        ("Comparator pipeline", stats(c_eng_lens)),
    ]))
    L.append("")
    L.append("### UGF response length (words, pre-Translator)")
    L.append("")
    L.append(fmt_kv_table([
        ("Reasoner UGF", stats(r_ugf_lens)),
        ("Comparator UGF", stats(c_ugf_lens)),
    ]))
    L.append("")
    L.append("### Per-item latency (seconds)")
    L.append("")
    L.append(fmt_kv_table([
        ("Reasoner pipeline (Translator + SFT Reasoner + Translator)", stats(r_latencies)),
        ("Comparator (single MR call to gpt-oss-120b)", stats(c_latencies)),
    ]))
    L.append("")

    L.append("## Per-type summary")
    L.append("")
    rows = ["| type | n | Reasoner mean words | Comparator mean words | Reasoner short rate | Comparator short rate |",
            "|---|---|---|---|---|---|"]
    for t in sorted_types:
        ids = by_type[t]
        r_w = [words(r_by_id[i].get("english_response", "")) for i in ids]
        c_w = [words(c_by_id[i].get("english_response", "")) for i in ids]
        r_s = sum(1 for n in r_w if n < 20)
        c_s = sum(1 for n in c_w if n < 20)
        rows.append(f"| {t} | {len(ids)} | {statistics.mean(r_w):.0f} | {statistics.mean(c_w):.0f} | {r_s}/{len(ids)} | {c_s}/{len(ids)} |")
    L.append("\n".join(rows))
    L.append("")

    L.append("## Pipeline failure modes worth watching for")
    L.append("")
    L.append("From eyeballed samples (formal scoring pending — Layer 3 LLM judge):")
    L.append("")
    L.append("**Translator English→UGF:** working reasonably. Notable artifact: per the corpus-generation system prompt, proper nouns are mapped to ordinal descriptions (`Katie` → `the person we talk about`, `Rembrandt` → `the first person`). This loses specificity in the UGF prompt the Reasoner sees.")
    L.append("")
    L.append("**SFT Reasoner:** the primary failure point. Common failure modes:")
    L.append("- *Off-topic continuation* — generates a coherent UGF reasoning trace but on a different topic than the prompt asked. Suggests SFT didn't fully condition the response on the prompt content.")
    L.append("- *Repetition loops* — short repetitive UGF when uncertain (most visible at temp=0.5; less common at temp=0.8 used here).")
    L.append("- *Premature EOS* — occasionally produces 1–2 sentences then stops.")
    L.append("")
    L.append("**Translator UGF→English:** mostly faithful, but **hallucinates proper names** when given UGF containing 'the first person' / 'the second person'. The Translator's English head invents specific names (`Mara`, `Lira`, `Thorne`, `Red`) since the training distribution included parallel pairs where named entities round-tripped through ordinals. This artifact is most visible on Reasoner-side outputs because Reasoner sometimes uses ordinal phrasing in its responses.")
    L.append("")

    L.append("## Table of contents")
    L.append("")
    for t in sorted_types:
        anchor = t.replace("_", "-")
        L.append(f"- [{t} ({len(by_type[t])})](#{anchor})")
    L.append("- [Notes / observations](#notes-observations)")
    L.append("")
    L.append("---")
    L.append("")

    # Per-type sections with full pipeline detail
    for t in sorted_types:
        anchor = t.replace("_", "-")
        L.append(f'## <a id="{anchor}"></a>{t} ({len(by_type[t])} items)')
        L.append("")
        L.append(f"_Type instruction:_ **{b_by_id[by_type[t][0]].get('instruction', '')}**")
        L.append("")
        for iid in by_type[t]:
            r = r_by_id[iid]
            c = c_by_id[iid]
            b = b_by_id[iid]

            L.append(f"### `{iid}`")
            L.append("")
            L.append(f"**Question:** {b['question']}")
            L.append("")
            L.append(f"**Expected answer (textbook):** {b['expected_answer']}")
            L.append("")

            # Reasoner pipeline (full)
            L.append("#### Reasoner pipeline")
            L.append("")
            L.append("**1. English query (built from instruction + question):**")
            L.append("")
            L.append("> " + r.get("english_query", "<missing>").replace("\n", "\n> "))
            L.append("")
            L.append("**2. Translator output (English → UGF):**")
            L.append("")
            L.append("> " + r.get("ugf_query", "<missing>").replace("\n", "\n> "))
            L.append("")
            L.append(f"**3. Wrapped in CONTENT_TYPES template (`{r.get('template', '?')}`) — what the Reasoner actually saw:**")
            L.append("")
            L.append("> " + r.get("wrapped_prompt", "<missing>").replace("\n", "\n> "))
            L.append("")
            L.append("**4. SFT Reasoner UGF response:**")
            L.append("")
            L.append("> " + r.get("ugf_response", "<missing>").replace("\n", "\n> "))
            L.append("")
            L.append("**5. Translator output (UGF → English):**")
            L.append("")
            L.append("> " + r.get("english_response", "<missing>").replace("\n", "\n> "))
            L.append("")
            L.append(f"_Latency: {r.get('latency_s', '?')}s_")
            L.append("")

            # Comparator (full)
            L.append("#### Teacher-in-UGF comparator (gpt-oss-120b)")
            L.append("")
            L.append(f"**1. Same English query, wrapped in `{c.get('template', '?')}` template, sent with UGF system prompt + 2 few-shot exemplars to gpt-oss-120b.**")
            L.append("")
            L.append("**2. Comparator UGF response:**")
            L.append("")
            L.append("> " + c.get("ugf_response", "<missing>").replace("\n", "\n> "))
            L.append("")
            L.append("**3. Translator output (UGF → English):**")
            L.append("")
            L.append("> " + c.get("english_response", "<missing>").replace("\n", "\n> "))
            L.append("")
            L.append(f"_Latency: {c.get('comparator_latency_s', '?')}s_")
            L.append("")

            L.append("**Your notes:** _(your read on which is closer to expected, what the failure modes are, etc.)_")
            L.append("")
            L.append("---")
            L.append("")

    # Notes / observations
    L.append('## <a id="notes-observations"></a>Notes / observations')
    L.append("")
    L.append("_Add overall observations here as you read through. Suggested headings:_")
    L.append("")
    L.append("- **Patterns in Reasoner failures** (off-topic? specific types worse?)")
    L.append("- **Patterns in Translator artifacts** (UGF→English hallucinations, proper-noun substitutions)")
    L.append("- **Surprises** (anything that worked well unexpectedly)")
    L.append("- **Where SFT clearly helped vs hurt** (compared to pretrain alone, if memory of that)")
    L.append("- **Implications for next steps** (Phase 3 RL? Translator improvements? Different SFT data?)")
    L.append("")

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    return out_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reasoner", required=True)
    parser.add_argument("--comparator", required=True)
    parser.add_argument("--bench", required=True)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    if args.out is None:
        ts = time.strftime("%Y%m%d_%H%M%S")
        args.out = f"eval/results/report_{ts}.md"

    reasoner = load_jsonl(args.reasoner)
    comparator = load_jsonl(args.comparator)
    bench = load_jsonl(args.bench)
    print(f"Reasoner items: {len(reasoner)}")
    print(f"Comparator items: {len(comparator)}")
    print(f"Bench items: {len(bench)}")

    out = render(reasoner, comparator, bench, args.out)
    size = Path(out).stat().st_size
    print(f"Wrote {out} ({size:,} bytes)")


if __name__ == "__main__":
    main()
