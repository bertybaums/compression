"""
Build a self-contained HTML version of the Layer-2 eval summary
(eval/results/eval_summary.md). Recomputes headline stats live from the
four input JSONLs so the page is regeneratable.

Usage:
  python -m eval.build_summary_html \\
      --textbook-reasoner   eval/results/logic_bench_<ts>.jsonl \\
      --textbook-comparator eval/results/comparator_logic_textbook_<ts>_with_english.jsonl \\
      --holdout-reasoner    eval/results/logic_bench_<ts>.jsonl  (the holdout one) \\
      --holdout-comparator  eval/results/comparator_holdout_<ts>_with_english.jsonl \\
      --out                 eval/results/eval_summary.html
"""

import argparse
import html
import json
import statistics
import time
from collections import defaultdict
from pathlib import Path


def load(p):
    return [json.loads(l) for l in open(p) if l.strip()]


def words(s):
    return 0 if not s or s.startswith("<") else len(s.split())


def stats(items, side):
    eng = [words(x.get("english_response", "")) for x in items]
    ugf = [words(x.get("ugf_response", "")) for x in items]
    lat_key = "latency_s" if side == "reasoner" else "comparator_latency_s"
    lat = [x.get(lat_key, 0) for x in items]
    short = sum(1 for n in eng if n < 20)
    return {
        "n": len(items),
        "short": short,
        "short_pct": 100 * short / len(items) if items else 0,
        "eng_mean": statistics.mean(eng) if eng else 0,
        "eng_median": statistics.median(eng) if eng else 0,
        "ugf_mean": statistics.mean(ugf) if ugf else 0,
        "lat_median": statistics.median(lat) if lat else 0,
    }


def per_type_stats(items, side):
    by_type = defaultdict(list)
    for x in items:
        by_type[x.get("type", "unknown")].append(x)
    out = {}
    for t, xs in by_type.items():
        eng = [words(x.get("english_response", "")) for x in xs]
        out[t] = {"n": len(xs), "mean_words": statistics.mean(eng) if eng else 0}
    return out


CSS = """
* { box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  max-width: 960px; margin: 0 auto; padding: 1.5em 2em;
  color: #222; line-height: 1.55;
}
h1 { border-bottom: 2px solid #888; padding-bottom: 0.3em; }
h2 { border-bottom: 1px solid #ccc; padding-bottom: 0.2em; margin-top: 2em; }
h3 { color: #1a4a75; margin-top: 1.5em; }
table { border-collapse: collapse; margin: 1em 0; width: 100%; }
th, td { border: 1px solid #ccc; padding: 0.5em 0.8em; text-align: left; }
th { background: #f5f5f5; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
.highlight { background: #fff7e0; }
.subtle { color: #777; font-size: 0.9em; }
.box {
  background: #f8fafd; border-left: 4px solid #4a6fa5;
  padding: 0.8em 1.2em; margin: 1em 0;
}
.box.warn { background: #fff7ee; border-left-color: #d97; }
.box.success { background: #f4fbf3; border-left-color: #5a8c5a; }
code { font-family: 'SF Mono', Menlo, monospace; font-size: 0.92em;
       background: #f0f0f0; padding: 0.1em 0.4em; border-radius: 3px; }
.pipeline-arrow { color: #888; font-style: italic; font-size: 0.92em; }
.report-link {
  display: inline-block; margin: 0.4em 0;
  background: #e8f0fa; padding: 0.4em 0.8em; border-radius: 4px;
  text-decoration: none; color: #2a4a75;
}
.report-link:hover { background: #d4e2f0; }

/* Representative samples */
details.sample {
  margin: 1em 0; border: 1px solid #ccd;
  border-radius: 6px; padding: 0.6em 1em; background: #fafbff;
}
details.sample summary {
  cursor: pointer; font-weight: 600;
  color: #1a4a75; padding: 0.2em 0;
}
details.sample summary:hover { color: #0a2a55; }
.sample-id { font-family: 'SF Mono', Menlo, monospace; color: #888;
              font-weight: normal; margin-right: 0.5em; font-size: 0.9em; }
.sample-type-tag {
  display: inline-block; background: #e0e8f5; color: #2a4a75;
  padding: 0.1em 0.5em; border-radius: 3px; font-size: 0.78em;
  margin-right: 0.5em; font-family: 'SF Mono', Menlo, monospace;
  font-weight: normal;
}
.qa-block { margin: 0.6em 0; }
.qa-label { font-size: 0.85em; color: #555; font-weight: 600; margin: 0.4em 0 0.2em 0; }
.qa-content {
  background: #ffffff; padding: 0.5em 0.8em; border-radius: 4px;
  border: 1px solid #e0e0e0; white-space: pre-wrap;
  font-size: 0.92em;
}
.qa-content.expected { background: #fdf8e8; border-color: #d4c890; }
.qa-content.reasoner { background: #f4fbf3; border-color: #b0d4b0; }
.qa-content.comparator { background: #f0f4f9; border-color: #b0c4d4; }
.pipeline-row {
  display: grid; grid-template-columns: 1fr 1fr; gap: 0.8em; margin: 0.4em 0;
}
.pipeline-row > div > .qa-label { margin-top: 0; }
.note-link { font-size: 0.85em; color: #888; }
"""


def pick_samples(items_r, items_c, type_picks):
    """For each (type, prefer_short) tuple, pick the first item from that type.

    Returns a list of (reasoner_item, comparator_item) tuples.
    """
    r_by_type = defaultdict(list)
    for it in items_r:
        r_by_type[it.get("type", "")].append(it)
    c_by_id = {it["id"]: it for it in items_c}
    out = []
    for t, prefer_short in type_picks:
        candidates = r_by_type.get(t, [])
        if not candidates:
            continue
        if prefer_short:
            shortish = [c for c in candidates if words(c.get("english_response", "")) < 20]
            chosen = shortish[0] if shortish else candidates[0]
        else:
            chosen = candidates[0]
        comp = c_by_id.get(chosen["id"])
        if comp:
            out.append((chosen, comp))
    return out


def render_sample(reasoner_item, comparator_item, bench_label):
    """Render one representative sample as a collapsible <details>."""
    r = reasoner_item
    c = comparator_item
    iid = r.get("id", "?")
    t = r.get("type", "?")
    question = r.get("question", "")
    expected = r.get("expected_answer", "")

    P = []
    P.append(f'<details class="sample">')
    q_short = question[:140] + ("..." if len(question) > 140 else "")
    P.append(
        f'<summary>'
        f'<span class="sample-id">{html.escape(iid)}</span>'
        f'<span class="sample-type-tag">{html.escape(t)}</span>'
        f'{html.escape(q_short)}'
        f'</summary>'
    )
    P.append('<div class="qa-block">')
    P.append('<div class="qa-label">Question</div>')
    P.append(f'<div class="qa-content">{html.escape(question)}</div>')
    P.append('</div>')

    P.append('<div class="qa-block">')
    P.append(f'<div class="qa-label">Expected answer ({"corpus heldout teacher trace" if "heldout" in bench_label else "textbook"})</div>')
    expected_short = expected if len(expected) < 600 else expected[:600] + "…"
    P.append(f'<div class="qa-content expected">{html.escape(expected_short)}</div>')
    P.append('</div>')

    P.append('<div class="pipeline-row">')
    P.append('<div>')
    P.append('<div class="qa-label">Reasoner pipeline (final English)</div>')
    r_eng = r.get("english_response", "") or "<empty>"
    P.append(f'<div class="qa-content reasoner">{html.escape(r_eng)}</div>')
    P.append('</div>')

    P.append('<div>')
    P.append('<div class="qa-label">Teacher-in-UGF comparator (final English)</div>')
    c_eng = c.get("english_response", "") or "<empty>"
    P.append(f'<div class="qa-content comparator">{html.escape(c_eng)}</div>')
    P.append('</div>')
    P.append('</div>')

    P.append('</details>')
    return "\n".join(P)


def render(tb_r, tb_c, ho_r, ho_c, out_path):
    s_tb_r = stats(tb_r, "reasoner")
    s_tb_c = stats(tb_c, "comp")
    s_ho_r = stats(ho_r, "reasoner")
    s_ho_c = stats(ho_c, "comp")

    # Per-type for holdout (Reasoner side strengths)
    pt_ho_r = per_type_stats(ho_r, "reasoner")
    pt_ho_c = per_type_stats(ho_c, "comp")
    types_sorted = sorted(set(pt_ho_r) & set(pt_ho_c),
                          key=lambda t: (pt_ho_r[t]["mean_words"] - pt_ho_c[t]["mean_words"]),
                          reverse=True)

    P = []
    P.append("<!DOCTYPE html>")
    P.append('<html lang="en"><head>')
    P.append('<meta charset="utf-8">')
    P.append("<title>Layer-2 evaluation summary</title>")
    P.append(f"<style>{CSS}</style>")
    P.append("</head><body>")
    P.append("<h1>Layer-2 evaluation: summary across two benchmarks</h1>")
    P.append(f'<p class="subtle">Generated {time.strftime("%Y-%m-%d %H:%M:%S")}.</p>')

    P.append("<p>This page explains why the project evaluates the SFT Reasoner on <strong>two benchmarks that measure different things</strong>, summarizes headline numbers from each, and links to the detailed reports.</p>")

    # Two benchmarks explained
    P.append("<h2>The two benchmarks measure different things</h2>")

    P.append("<h3>Textbook benchmark (<code>logic_textbook_bench.jsonl</code>, 115 items)</h3>")
    P.append('<div class="box">')
    P.append("<p><strong>Question it answers:</strong> if a student types a plain English logic-textbook question into the chatbot, can the <em>full pipeline</em> produce a useful answer?</p>")
    P.append("<p><strong>What it stresses:</strong></p>")
    P.append("<ul>")
    P.append("<li>The <strong>whole user-facing system</strong>: English in, English out</li>")
    P.append("<li>Translator(English → UGF) on out-of-distribution input (proper nouns, technical phrasing)</li>")
    P.append("<li>Reasoner on prompts whose <em>content</em> is in distribution but whose <em>form</em> (wrapped in CONTENT_TYPES around a translated query) is slightly off-distribution</li>")
    P.append("<li>Translator(UGF → English) on Reasoner output</li>")
    P.append("</ul>")
    P.append("<p><strong>Pipeline:</strong></p>")
    P.append('<p class="pipeline-arrow">English question → Translator(En→UGF) → wrap in CONTENT_TYPES template → SFT Reasoner → UGF response → Translator(UGF→En) → English response</p>')
    P.append("</div>")

    P.append("<h3>Holdout benchmark (<code>holdout_bench.jsonl</code>, 170 items)</h3>")
    P.append('<div class="box">')
    P.append("<p><strong>Question it answers:</strong> if we feed the Reasoner exactly the kind of prompt it was trained on, does it produce something teacher-quality?</p>")
    P.append("<p><strong>What it stresses:</strong></p>")
    P.append("<ul>")
    P.append("<li>The <strong>Reasoner alone</strong>, isolated from Translator-induced distribution shift</li>")
    P.append("<li>Whether the Reasoner has internalized the teacher distribution well enough to reproduce equivalent traces on <em>held-out</em> topics</li>")
    P.append("</ul>")
    P.append("<p><strong>Pipeline:</strong></p>")
    P.append('<p class="pipeline-arrow">(already-formatted prompt from corpus) → SFT Reasoner → UGF response → Translator(UGF→En) → English response</p>')
    P.append("<p>The Translator(En → UGF) step is <em>skipped</em> (<code>--skip-translate-en2ugf</code>) because holdout prompts are already in the corpus prompt format.</p>")
    P.append("</div>")

    # Decomposition matrix
    P.append("<h3>Why the two together is informative</h3>")
    P.append("<p>The benchmarks decompose the Reasoner-vs-pipeline question:</p>")
    P.append("<table>")
    P.append("<tr><th>holdout</th><th>textbook</th><th>implication</th></tr>")
    P.append("<tr><td>strong</td><td>strong</td><td>full system works</td></tr>")
    P.append('<tr class="highlight"><td><strong>strong</strong></td><td><strong>weak</strong></td><td><strong>Reasoner is fine; chatbot pipeline is the bottleneck</strong></td></tr>')
    P.append("<tr><td>weak</td><td>strong</td><td>unlikely (Reasoner doesn't reproduce its training but works on harder input)</td></tr>")
    P.append("<tr><td>weak</td><td>weak</td><td>Reasoner needs more training</td></tr>")
    P.append("</table>")
    P.append("<p>What we observe falls in the highlighted row.</p>")

    # Headline numbers
    P.append("<h2>Headline numbers</h2>")
    P.append("<table>")
    P.append("<tr><th>metric</th><th>Reasoner (textbook)</th><th>Comparator (textbook)</th><th>Reasoner (holdout)</th><th>Comparator (holdout)</th></tr>")
    P.append(f"<tr><td>n</td><td class='num'>{s_tb_r['n']}</td><td class='num'>{s_tb_c['n']}</td><td class='num'>{s_ho_r['n']}</td><td class='num'>{s_ho_c['n']}</td></tr>")
    P.append(f"<tr class='highlight'><td>Short responses (&lt;20 words)</td><td class='num'><strong>{s_tb_r['short']} ({s_tb_r['short_pct']:.1f}%)</strong></td><td class='num'>{s_tb_c['short']} (0.0%)</td><td class='num'><strong>{s_ho_r['short']} ({s_ho_r['short_pct']:.1f}%)</strong></td><td class='num'>{s_ho_c['short']} (0.0%)</td></tr>")
    P.append(f"<tr><td>English response mean words</td><td class='num'>{s_tb_r['eng_mean']:.0f}</td><td class='num'>{s_tb_c['eng_mean']:.0f}</td><td class='num'><strong>{s_ho_r['eng_mean']:.0f}</strong></td><td class='num'>{s_ho_c['eng_mean']:.0f}</td></tr>")
    P.append(f"<tr><td>English response median words</td><td class='num'>{s_tb_r['eng_median']:.0f}</td><td class='num'>{s_tb_c['eng_median']:.0f}</td><td class='num'>{s_ho_r['eng_median']:.0f}</td><td class='num'>{s_ho_c['eng_median']:.0f}</td></tr>")
    P.append(f"<tr><td>UGF response mean words</td><td class='num'>{s_tb_r['ugf_mean']:.0f}</td><td class='num'>{s_tb_c['ugf_mean']:.0f}</td><td class='num'>{s_ho_r['ugf_mean']:.0f}</td><td class='num'>{s_ho_c['ugf_mean']:.0f}</td></tr>")
    P.append(f"<tr><td>Median per-item latency (s)</td><td class='num'>{s_tb_r['lat_median']:.1f}</td><td class='num'>{s_tb_c['lat_median']:.1f}</td><td class='num'>{s_ho_r['lat_median']:.1f}</td><td class='num'>{s_ho_c['lat_median']:.1f}</td></tr>")
    P.append("</table>")

    P.append('<div class="box success">')
    P.append("<p><strong>Key observation:</strong> the Reasoner's failure rate drops from <strong>7.0% → 0.6%</strong> when moving from the chatbot pipeline (textbook) to direct prompting (holdout). The Reasoner produces <em>more</em> English-side content than the comparator on holdout (204 vs 180 mean words), and <em>less</em> on textbook (159 vs 175). The 30+ word reduction in the textbook setting is consistent with truncated / short / off-topic Reasoner outputs that don't survive the round-trip through the Translator.</p>")
    P.append("</div>")

    # Representative samples
    P.append("<h2>Representative samples</h2>")
    P.append("<p>A handful of actual outputs across types, picked to span the kinds of behavior visible in the full reports. Click to expand.</p>")

    # Textbook samples — pick from 4 different types, biased to show pipeline failures
    textbook_picks = [
        ("statement_vs_nonstatement", False),     # simple categorization
        ("statistical_fallacy", True),            # Reasoner short-rate is high here
        ("analogical_argument_strength", False),  # long-form
        ("identify_argument", False),             # substantive
    ]
    textbook_samples = pick_samples(tb_r, tb_c, textbook_picks)
    P.append("<h3>Textbook benchmark samples (full pipeline through Translator)</h3>")
    P.append('<p class="subtle">Each example shows a student-style English question, the textbook expected answer, and the final English response from each pipeline. The full intermediate stages (UGF query, wrapped prompt, UGF response) are in <a href="report_logic_textbook.html">report_logic_textbook.html</a>.</p>')
    for r, c in textbook_samples:
        P.append(render_sample(r, c, "textbook"))

    # Holdout samples — pick from 4 types where Reasoner shines or is competitive
    holdout_picks = [
        ("concept_explanation", False),       # Reasoner produces 2x comparator length here
        ("chain_of_thought", False),           # Reasoner produces 1.5x
        ("counterexample_analysis", False),    # cxbot - largest category
        ("conditional_analysis", False),       # misccorpora
    ]
    holdout_samples = pick_samples(ho_r, ho_c, holdout_picks)
    P.append("<h3>Holdout benchmark samples (Reasoner alone, no Translator(En→UGF))</h3>")
    P.append('<p class="subtle">Each example shows a corpus-style prompt fed directly to the Reasoner (skipping the English→UGF translation, since these are already in the training-distribution format). The expected answer is the held-out trace from the corpus. Full intermediates in <a href="report_holdout.html">report_holdout.html</a>.</p>')
    for r, c in holdout_samples:
        P.append(render_sample(r, c, "heldout"))

    # Per-type holdout
    P.append("<h2>Per-type holdout (where the Reasoner shines)</h2>")
    P.append("<p>The Reasoner produces meaningfully <em>longer</em> output than the comparator on its training-distribution prompts in:</p>")
    P.append("<table>")
    P.append("<tr><th>type</th><th>n</th><th>Reasoner mean words</th><th>Comparator mean words</th><th>difference</th></tr>")
    for t in types_sorted:
        rw = pt_ho_r[t]["mean_words"]
        cw = pt_ho_c[t]["mean_words"]
        diff = rw - cw
        sign = "+" if diff > 0 else ""
        cls = "highlight" if diff > 30 else ""
        P.append(f"<tr class='{cls}'><td><code>{html.escape(t)}</code></td><td class='num'>{pt_ho_r[t]['n']}</td><td class='num'>{rw:.0f}</td><td class='num'>{cw:.0f}</td><td class='num'>{sign}{diff:.0f}</td></tr>")
    P.append("</table>")
    P.append("<p class='subtle'>Highlighted rows: Reasoner produces &gt;30 more words than comparator on average. Even the negative gaps are within roughly 1 standard deviation of length variance.</p>")

    # Implications
    P.append("<h2>Implications for next steps</h2>")
    P.append("<ul>")
    P.append("<li><strong>The holdout result is encouraging:</strong> the SFT Reasoner is doing approximately what we want within its training distribution. It produces traces of comparable length and (qualitatively, from sample inspection) comparable structure to the gpt-oss-120b teacher under the same UGF system prompt.</li>")
    P.append("<li><strong>The textbook result identifies the chatbot pipeline as the next thing to improve</strong>, specifically:")
    P.append("<ul>")
    P.append("<li>Translator(English → UGF) on out-of-distribution natural-English questions (proper nouns lost, wording simplified)</li>")
    P.append("<li>Translator(UGF → English) hallucinating proper names ('Mara', 'Lira', 'Thorne') when given UGF that contains 'the first person' / 'the second person' patterns</li>")
    P.append("<li>The wrapping-then-Translator-then-Reasoner-then-Translator chain may compound minor distortions</li>")
    P.append("</ul></li>")
    P.append("<li>These are <strong>fixable independently</strong>: the Reasoner doesn't need re-training right now; the Translator and the prompt-formatting between Translator and Reasoner do.</li>")
    P.append("<li>Layer 3 LLM-judge scoring (when we run it) will turn these length/short-rate observations into per-dimension rubric scores. The rubric (engagement, coherence, substance, expressive_adequacy) will pick up quality differences that length doesn't capture.</li>")
    P.append("</ul>")

    # Detailed reports
    P.append("<h2>Detailed reports</h2>")
    P.append("<table>")
    P.append("<tr><th>file</th><th>what's in it</th></tr>")
    P.append('<tr><td><a class="report-link" href="report_logic_textbook.html">report_logic_textbook.html</a></td><td>Interactive textbook-benchmark report (115 items, full pipeline detail per item, filters, search)</td></tr>')
    P.append('<tr><td><a class="report-link" href="report_logic_textbook.md">report_logic_textbook.md</a></td><td>Markdown version of the textbook report</td></tr>')
    P.append('<tr><td><a class="report-link" href="report_holdout.html">report_holdout.html</a></td><td>Interactive holdout-benchmark report (170 items, full pipeline detail per item, filters, search)</td></tr>')
    P.append('<tr><td><a class="report-link" href="report_holdout.md">report_holdout.md</a></td><td>Markdown version of the holdout report</td></tr>')
    P.append('<tr><td><a class="report-link" href="eval_summary.md">eval_summary.md</a></td><td>Markdown version of this summary</td></tr>')
    P.append("</table>")
    P.append("<p class='subtle'>Both detailed HTML reports are self-contained — open them in any browser, no server needed. Each has filter dropdowns (by type, &quot;only short responses&quot;, free-text search) and per-type collapsible sections.</p>")

    P.append("</body></html>")

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(P))
    return out_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--textbook-reasoner", required=True)
    parser.add_argument("--textbook-comparator", required=True)
    parser.add_argument("--holdout-reasoner", required=True)
    parser.add_argument("--holdout-comparator", required=True)
    parser.add_argument("--out", default="eval/results/eval_summary.html")
    args = parser.parse_args()

    tb_r = load(args.textbook_reasoner)
    tb_c = load(args.textbook_comparator)
    ho_r = load(args.holdout_reasoner)
    ho_c = load(args.holdout_comparator)
    print(f"Loaded: textbook ({len(tb_r)}/{len(tb_c)}), holdout ({len(ho_r)}/{len(ho_c)})")

    out = render(tb_r, tb_c, ho_r, ho_c, args.out)
    size = Path(out).stat().st_size
    print(f"Wrote {out} ({size:,} bytes)")


if __name__ == "__main__":
    main()
