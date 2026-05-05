"""
Build a side-by-side comparison Markdown file from Reasoner-pipeline and
Comparator outputs on the same benchmark.

For each benchmark item, shows:
  - The original English question + expected answer
  - The Reasoner pipeline path: ugf_query, ugf_response, english_response
  - The Comparator path: ugf_response, english_response

Items are grouped by `type` for easy navigation. Includes a TOC at the top.

Usage:
  python -m eval.build_comparison_md \\
      --reasoner   eval/results/logic_bench_<ts>.jsonl \\
      --comparator eval/results/comparator_logic_textbook_<ts>_with_english.jsonl \\
      --out        eval/results/comparison_<ts>.md
"""

import argparse
import json
import time
from pathlib import Path
from collections import defaultdict


def load_jsonl(path):
    items = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def render_md(reasoner_items, comparator_items, out_path):
    r_by_id = {x["id"]: x for x in reasoner_items}
    c_by_id = {x["id"]: x for x in comparator_items}
    common_ids = sorted(set(r_by_id.keys()) & set(c_by_id.keys()))

    # Group ids by type (using reasoner side's type)
    by_type = defaultdict(list)
    for iid in common_ids:
        t = r_by_id[iid].get("type", "unknown")
        by_type[t].append(iid)

    lines = []
    lines.append("# Reasoner pipeline vs. teacher-in-UGF comparator")
    lines.append("")
    lines.append(f"_Generated {time.strftime('%Y-%m-%d %H:%M:%S')}_")
    lines.append("")
    lines.append(f"- **Benchmark:** logic_textbook_bench (Van Cleave, *Intro to Logic and Critical Thinking v2.0*, CC-BY 4.0)")
    lines.append(f"- **Items shown:** {len(common_ids)} of 115")
    lines.append(f"- **Reasoner side:** English query → Translator → UGF query → wrap in CONTENT_TYPES → SFT Reasoner → UGF response → Translator → English response")
    lines.append(f"- **Comparator side:** English query → gpt-oss-120b on MindRouter (UGF system prompt + 2 few-shot exemplars) → UGF response → Translator → English response")
    lines.append("")
    lines.append("## Table of contents")
    lines.append("")
    for t in sorted(by_type.keys()):
        anchor = t.replace("_", "-")
        lines.append(f"- [{t} ({len(by_type[t])})](#{anchor})")
    lines.append("")
    lines.append("---")
    lines.append("")

    for t in sorted(by_type.keys()):
        anchor = t.replace("_", "-")
        lines.append(f'## <a id="{anchor}"></a>{t} ({len(by_type[t])} items)')
        lines.append("")
        for iid in by_type[t]:
            r = r_by_id[iid]
            c = c_by_id[iid]
            lines.append(f"### `{iid}`")
            lines.append("")
            lines.append(f"**Question:** {r['question']}")
            lines.append("")
            lines.append(f"**Expected answer (textbook):** {r['expected_answer']}")
            lines.append("")
            lines.append("#### Reasoner pipeline")
            lines.append("")
            ugf_q = r.get("ugf_query", "<missing>")
            ugf_r = r.get("ugf_response", "<missing>")
            eng_r = r.get("english_response", "<missing>")
            lines.append("**Translator (English → UGF):**")
            lines.append("")
            lines.append("> " + ugf_q.replace("\n", "\n> "))
            lines.append("")
            lines.append("**SFT Reasoner (UGF response):**")
            lines.append("")
            lines.append("> " + ugf_r.replace("\n", "\n> "))
            lines.append("")
            lines.append("**Translator (UGF → English):**")
            lines.append("")
            lines.append("> " + eng_r.replace("\n", "\n> "))
            lines.append("")
            lines.append("#### Teacher-in-UGF comparator (gpt-oss-120b)")
            lines.append("")
            c_ugf = c.get("ugf_response", "<missing>")
            c_eng = c.get("english_response", "<missing>")
            lines.append("**UGF response:**")
            lines.append("")
            lines.append("> " + c_ugf.replace("\n", "\n> "))
            lines.append("")
            lines.append("**Translator (UGF → English):**")
            lines.append("")
            lines.append("> " + c_eng.replace("\n", "\n> "))
            lines.append("")
            lines.append("---")
            lines.append("")

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return out_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reasoner", required=True)
    parser.add_argument("--comparator", required=True)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    if args.out is None:
        ts = time.strftime("%Y%m%d_%H%M%S")
        args.out = f"eval/results/comparison_{ts}.md"

    reasoner = load_jsonl(args.reasoner)
    comparator = load_jsonl(args.comparator)
    print(f"Reasoner items: {len(reasoner)}")
    print(f"Comparator items: {len(comparator)}")

    out = render_md(reasoner, comparator, args.out)
    size = Path(out).stat().st_size
    print(f"Wrote {out} ({size:,} bytes)")


if __name__ == "__main__":
    main()
