"""
Build an interactive HTML version of the Layer-2 evaluation report.

Differences from the Markdown report:
  - Each per-type section is a collapsible <details>
  - Each per-item entry is a nested <details>, collapsed by default
  - Filters at top: by type, by short-response only, free-text search
  - Aggregate tables and per-type summary stay visible at the top
  - Self-contained: one HTML file, no external dependencies, works offline

Usage:
  python -m eval.build_report_html \\
      --reasoner   eval/results/logic_bench_<ts>.jsonl \\
      --comparator eval/results/comparator_logic_textbook_<ts>_with_english.jsonl \\
      --bench      eval/sets/logic_textbook_bench.jsonl \\
      --out        eval/results/report_<ts>.html
"""

import argparse
import html
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


def esc(s):
    """HTML-escape and convert newlines to <br> for safe display in blockquotes."""
    if s is None:
        return ""
    return html.escape(str(s)).replace("\n", "<br>")


CSS = """
* { box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  max-width: 1200px; margin: 0 auto; padding: 1em 2em;
  color: #222; line-height: 1.5;
}
h1, h2, h3, h4 { color: #1a1a1a; }
h1 { border-bottom: 2px solid #888; padding-bottom: 0.3em; }
h2 { border-bottom: 1px solid #ccc; padding-bottom: 0.2em; margin-top: 2em; }
table { border-collapse: collapse; margin: 1em 0; }
th, td { border: 1px solid #ccc; padding: 0.4em 0.8em; text-align: left; }
th { background: #f5f5f5; }
code, .mono { font-family: 'SF Mono', Menlo, monospace; font-size: 0.9em; }

#filters {
  position: sticky; top: 0; background: #fffaef; padding: 0.7em 1em;
  border: 1px solid #d4c8a0; border-radius: 4px; margin-bottom: 1em;
  z-index: 10;
}
#filters label { margin-right: 1.5em; font-size: 0.92em; }
#filters select, #filters input[type=text] { font-size: 0.9em; padding: 0.2em 0.4em; }

details { margin: 0.5em 0; border-left: 3px solid #ccc; padding-left: 0.8em; }
details.type-section {
  border-left-width: 5px; border-left-color: #4a6fa5;
  background: #f8fafd; padding: 0.5em 1em;
  margin: 1.5em 0;
}
details.item {
  background: #ffffff; border-left-color: #999;
  margin: 0.5em 0; padding: 0.5em 1em;
}
details.item[data-short="true"] { border-left-color: #d97;  background: #fff7ee; }

summary { cursor: pointer; font-weight: 600; padding: 0.3em 0; }
summary:hover { background: #f0f0f0; }
details.item summary {
  font-weight: normal;
  font-family: 'SF Mono', Menlo, monospace; font-size: 0.92em;
}
.item-id { font-weight: 700; color: #4a6fa5; margin-right: 0.5em; }
.short-badge {
  display: inline-block; background: #d97; color: white;
  padding: 0.05em 0.5em; border-radius: 3px; font-size: 0.75em;
  margin-left: 0.5em;
}
.type-tag {
  display: inline-block; background: #e0e8f5; color: #2a4a75;
  padding: 0.05em 0.5em; border-radius: 3px; font-size: 0.78em;
  margin-right: 0.5em; font-family: 'SF Mono', Menlo, monospace;
}

.q-preview { color: #666; font-size: 0.92em; }

.pipeline {
  background: #fafafa; border-left: 4px solid #b0d4b0;
  padding: 0.7em 1em; margin: 1em 0;
}
.pipeline.comparator { border-left-color: #b0b0d4; }
.pipeline h4 { margin: 0 0 0.5em 0; }
.stage { margin: 0.6em 0; }
.stage-label { font-size: 0.85em; color: #555; margin-bottom: 0.2em; }
blockquote {
  margin: 0.2em 0; padding: 0.5em 0.8em; border-left: 3px solid #aaa;
  background: #f5f5f5; color: #222; font-size: 0.92em;
  white-space: pre-wrap;
}
blockquote.ugf { border-left-color: #6a8db0; background: #f0f4f9; font-style: italic; }
blockquote.english { border-left-color: #5a8c5a; }
blockquote.expected { border-left-color: #c4a050; background: #fdf8e8; }
blockquote.system { font-size: 0.82em; color: #555; }

.latency { color: #888; font-size: 0.85em; font-style: italic; }
.notes-placeholder {
  background: #fffce0; border: 1px dashed #d4c890;
  padding: 0.7em; margin: 0.8em 0;
  font-size: 0.88em; color: #885;
}
.hidden { display: none !important; }
.kbd-hint { color: #999; font-size: 0.85em; margin-left: 1em; }
"""


JS = """
function applyFilters() {
  const tFilter = document.getElementById('f-type').value;
  const onlyShort = document.getElementById('f-short').checked;
  const text = document.getElementById('f-text').value.toLowerCase().trim();

  const items = document.querySelectorAll('details.item');
  let visibleCount = 0;
  const sectionVisible = {};

  items.forEach(it => {
    const itemType = it.dataset.type;
    const isShort = it.dataset.short === 'true';
    const haystack = it.dataset.q || '';
    let show = true;
    if (tFilter && itemType !== tFilter) show = false;
    if (onlyShort && !isShort) show = false;
    if (text && !haystack.toLowerCase().includes(text)) show = false;
    it.classList.toggle('hidden', !show);
    if (show) {
      visibleCount += 1;
      sectionVisible[itemType] = (sectionVisible[itemType] || 0) + 1;
    }
  });

  // Hide empty type sections
  document.querySelectorAll('details.type-section').forEach(sec => {
    const t = sec.dataset.type;
    sec.classList.toggle('hidden', !sectionVisible[t]);
  });

  document.getElementById('visible-count').textContent = visibleCount;
}

function expandAll() {
  document.querySelectorAll('details').forEach(d => d.open = true);
}
function collapseAll() {
  document.querySelectorAll('details').forEach(d => d.open = false);
}

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('f-type').addEventListener('change', applyFilters);
  document.getElementById('f-short').addEventListener('change', applyFilters);
  document.getElementById('f-text').addEventListener('input', applyFilters);
  document.getElementById('btn-expand').addEventListener('click', expandAll);
  document.getElementById('btn-collapse').addEventListener('click', collapseAll);
  applyFilters();
});
"""


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
    r_lat = [r_by_id[i].get("latency_s", 0.0) for i in common_ids]
    c_lat = [c_by_id[i].get("comparator_latency_s", 0.0) for i in common_ids]
    r_short = sum(1 for n in r_eng_lens if n < 20)
    c_short = sum(1 for n in c_eng_lens if n < 20)

    def stats_str(xs):
        if not xs:
            return "n/a"
        return (f"min={min(xs):.0f}  median={statistics.median(xs):.0f}  "
                f"mean={statistics.mean(xs):.0f}  p90={sorted(xs)[int(0.9*len(xs))]:.0f}  "
                f"max={max(xs):.0f}")

    parts = []
    parts.append("<!DOCTYPE html>")
    parts.append('<html lang="en"><head>')
    parts.append('<meta charset="utf-8">')
    parts.append("<title>Reasoner vs comparator — Layer-2 eval</title>")
    parts.append(f"<style>{CSS}</style>")
    parts.append("</head><body>")

    parts.append("<h1>Layer-2 evaluation report: Reasoner pipeline vs. teacher-in-UGF comparator</h1>")
    parts.append(f'<p><em>Generated {time.strftime("%Y-%m-%d %H:%M:%S")}</em></p>')

    parts.append("<h2>Setup</h2>")
    parts.append("""<ul>
<li><strong>Reasoner pipeline:</strong> English question → Translator(English→UGF) → wrap in CONTENT_TYPES template → 200M from-scratch SFT Reasoner → UGF response → Translator(UGF→English) → English response</li>
<li><strong>Teacher-in-UGF comparator:</strong> English question → <code>gpt-oss-120b</code> on MindRouter (UGF system prompt + 2 few-shot exemplars) → UGF response → Translator(UGF→English) → English response</li>
<li><strong>Benchmark:</strong> Van Cleave, <em>Introduction to Logic and Critical Thinking v2.0</em> (CC-BY 4.0). 9 categories.</li>
</ul>""")

    parts.append("<h2>Aggregate statistics</h2>")
    parts.append("<table>")
    parts.append("<tr><th>metric</th><th>Reasoner pipeline</th><th>Comparator</th></tr>")
    parts.append(f"<tr><td>items</td><td>{len(common_ids)}</td><td>{len(common_ids)}</td></tr>")
    parts.append(f"<tr><td>short responses (&lt;20 words)</td><td>{r_short} ({100*r_short/len(common_ids):.0f}%)</td><td>{c_short} ({100*c_short/len(common_ids):.0f}%)</td></tr>")
    parts.append(f"<tr><td>English response length (words)</td><td class='mono'>{stats_str(r_eng_lens)}</td><td class='mono'>{stats_str(c_eng_lens)}</td></tr>")
    parts.append(f"<tr><td>UGF response length (words)</td><td class='mono'>{stats_str(r_ugf_lens)}</td><td class='mono'>{stats_str(c_ugf_lens)}</td></tr>")
    parts.append(f"<tr><td>Per-item latency (s)</td><td class='mono'>{stats_str(r_lat)}</td><td class='mono'>{stats_str(c_lat)}</td></tr>")
    parts.append("</table>")

    parts.append("<h2>Per-type summary</h2>")
    parts.append("<table>")
    parts.append("<tr><th>type</th><th>n</th><th>Reasoner mean words</th><th>Comparator mean words</th><th>Reasoner short rate</th><th>Comparator short rate</th></tr>")
    for t in sorted_types:
        ids = by_type[t]
        r_w = [words(r_by_id[i].get("english_response", "")) for i in ids]
        c_w = [words(c_by_id[i].get("english_response", "")) for i in ids]
        r_s = sum(1 for n in r_w if n < 20)
        c_s = sum(1 for n in c_w if n < 20)
        parts.append(f"<tr><td><code>{esc(t)}</code></td><td>{len(ids)}</td><td>{statistics.mean(r_w):.0f}</td><td>{statistics.mean(c_w):.0f}</td><td>{r_s}/{len(ids)}</td><td>{c_s}/{len(ids)}</td></tr>")
    parts.append("</table>")

    parts.append("<h2>Pipeline failure modes worth watching for</h2>")
    parts.append("""<p><strong>Translator English→UGF:</strong> reasonable. Notable artifact: per the corpus-generation system prompt, proper nouns get mapped to ordinal descriptions (<code>Katie</code> → <em>the person we talk about</em>, <code>Rembrandt</code> → <em>the first person</em>). Loses specificity.</p>

<p><strong>SFT Reasoner:</strong> the primary failure point. Common failure modes:</p>
<ul>
<li><em>Off-topic continuation</em> — generates coherent UGF on a different topic.</li>
<li><em>Repetition loops</em> — short repetitive UGF when uncertain.</li>
<li><em>Premature EOS</em> — occasionally produces 1–2 sentences then stops.</li>
</ul>

<p><strong>Translator UGF→English:</strong> mostly faithful, but <strong>hallucinates proper names</strong> when given UGF containing 'the first person' / 'the second person'. The Translator's English head invents specific names (<code>Mara</code>, <code>Lira</code>, <code>Thorne</code>, <code>Red</code>). Most visible on Reasoner-side outputs.</p>""")

    # Filters
    parts.append('<h2>Per-item details</h2>')
    parts.append('<div id="filters">')
    parts.append('<label>Type: <select id="f-type"><option value="">(all)</option>')
    for t in sorted_types:
        parts.append(f'<option value="{esc(t)}">{esc(t)}</option>')
    parts.append('</select></label>')
    parts.append('<label><input type="checkbox" id="f-short"> Only short Reasoner responses</label>')
    parts.append('<label>Search question: <input type="text" id="f-text" placeholder="substring..."></label>')
    parts.append('<button id="btn-expand">expand all</button> ')
    parts.append('<button id="btn-collapse">collapse all</button>')
    parts.append(f'<span class="kbd-hint">Showing <span id="visible-count">{len(common_ids)}</span> of {len(common_ids)} items</span>')
    parts.append('</div>')

    # Per-type sections
    for t in sorted_types:
        parts.append(f'<details class="type-section" data-type="{esc(t)}" open>')
        parts.append(f'<summary>{esc(t)} <span class="kbd-hint">({len(by_type[t])} items)</span></summary>')
        parts.append(f'<p><em>Type instruction:</em> {esc(b_by_id[by_type[t][0]].get("instruction", ""))}</p>')

        for iid in by_type[t]:
            r = r_by_id[iid]
            c = c_by_id[iid]
            b = b_by_id[iid]
            r_short_flag = words(r.get("english_response", "")) < 20
            short_attr = "true" if r_short_flag else "false"
            q_short = b["question"][:120] + ("..." if len(b["question"]) > 120 else "")
            short_badge = '<span class="short-badge">short</span>' if r_short_flag else ''

            # Build item summary line
            parts.append(f'<details class="item" data-type="{esc(t)}" data-short="{short_attr}" data-q="{esc(b["question"])}">')
            parts.append(
                f'<summary>'
                f'<span class="item-id">{esc(iid)}</span>'
                f'<span class="type-tag">{esc(t)}</span>'
                f'<span class="q-preview">{esc(q_short)}</span>'
                f'{short_badge}'
                f'</summary>'
            )

            # Question + expected
            parts.append(f"<div class='stage'><div class='stage-label'>Question</div><blockquote>{esc(b['question'])}</blockquote></div>")
            parts.append(f"<div class='stage'><div class='stage-label'>Expected answer (textbook)</div><blockquote class='expected'>{esc(b['expected_answer'])}</blockquote></div>")

            # Reasoner pipeline
            parts.append('<div class="pipeline">')
            parts.append('<h4>Reasoner pipeline</h4>')
            parts.append(f"<div class='stage'><div class='stage-label'>1. English query</div><blockquote>{esc(r.get('english_query', ''))}</blockquote></div>")
            parts.append(f"<div class='stage'><div class='stage-label'>2. Translator (English → UGF)</div><blockquote class='ugf'>{esc(r.get('ugf_query', ''))}</blockquote></div>")
            parts.append(f"<div class='stage'><div class='stage-label'>3. Wrapped CONTENT_TYPES template ({esc(r.get('template', '?'))}) — what the Reasoner actually saw</div><blockquote class='system'>{esc(r.get('wrapped_prompt', ''))}</blockquote></div>")
            parts.append(f"<div class='stage'><div class='stage-label'>4. SFT Reasoner UGF response</div><blockquote class='ugf'>{esc(r.get('ugf_response', ''))}</blockquote></div>")
            parts.append(f"<div class='stage'><div class='stage-label'>5. Translator (UGF → English)</div><blockquote class='english'>{esc(r.get('english_response', ''))}</blockquote></div>")
            parts.append(f"<div class='latency'>Pipeline latency: {r.get('latency_s', '?')} s</div>")
            parts.append('</div>')

            # Comparator
            parts.append('<div class="pipeline comparator">')
            parts.append(f"<h4>Teacher-in-UGF comparator (gpt-oss-120b, template={esc(c.get('template', '?'))})</h4>")
            parts.append(f"<div class='stage'><div class='stage-label'>1. UGF response</div><blockquote class='ugf'>{esc(c.get('ugf_response', ''))}</blockquote></div>")
            parts.append(f"<div class='stage'><div class='stage-label'>2. Translator (UGF → English)</div><blockquote class='english'>{esc(c.get('english_response', ''))}</blockquote></div>")
            parts.append(f"<div class='latency'>Comparator MR call latency: {c.get('comparator_latency_s', '?')} s</div>")
            parts.append('</div>')

            # Notes placeholder
            parts.append('<div class="notes-placeholder">Your notes: _click to focus and type observations here. (HTML scratch — refresh discards. Use the markdown export for persistence.)_</div>')

            parts.append('</details>')  # close item

        parts.append('</details>')  # close type-section

    # Final notes
    parts.append("<h2>Notes / observations</h2>")
    parts.append("""<ul>
<li><strong>Patterns in Reasoner failures</strong> — ?</li>
<li><strong>Patterns in Translator artifacts</strong> — ?</li>
<li><strong>Surprises</strong> — ?</li>
<li><strong>Implications for next steps</strong> — Phase 3 RL? Translator improvements? Different SFT data?</li>
</ul>""")

    parts.append(f"<script>{JS}</script>")
    parts.append("</body></html>")

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))
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
        args.out = f"eval/results/report_{ts}.html"

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
