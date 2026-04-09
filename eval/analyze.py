"""
Analyze evaluation results and produce summary reports.

Reads JSON results from round_trip.py and produces:
  - Aggregate statistics across all metrics
  - Breakdowns by domain / taxonomy code (if metadata available)
  - Identification of best/worst cases
  - Comparison between tests (A vs B vs C)

Usage:
  python eval/analyze.py eval/results/test_A_*.json
  python eval/analyze.py eval/results/test_all_*.json --report eval/reports/summary.md
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


def load_results(path: str | Path) -> dict:
    with open(path) as f:
        return json.load(f)


def format_table(headers: list[str], rows: list[list[str]], col_widths: list[int] | None = None) -> str:
    """Format a markdown table."""
    if col_widths is None:
        col_widths = [max(len(h), max((len(str(r[i])) for r in rows), default=0)) for i, h in enumerate(headers)]

    lines = []
    header = "| " + " | ".join(h.ljust(w) for h, w in zip(headers, col_widths)) + " |"
    sep = "| " + " | ".join("-" * w for w in col_widths) + " |"
    lines.append(header)
    lines.append(sep)
    for row in rows:
        line = "| " + " | ".join(str(v).ljust(w) for v, w in zip(row, col_widths)) + " |"
        lines.append(line)
    return "\n".join(lines)


def analyze_test(test_name: str, test_results: dict) -> str:
    """Produce a markdown analysis for a single test."""
    lines = []
    lines.append(f"### Test {test_name}: {test_results.get('description', '')}")
    lines.append(f"")
    lines.append(f"**Samples evaluated:** {test_results.get('n_samples', 0)}")
    lines.append(f"")

    # Metrics summary table
    metrics = test_results.get("metrics", {})
    if metrics:
        headers = ["Metric", "Mean", "Median", "Std", "Min", "Max"]
        rows = []
        for name, summary in metrics.items():
            rows.append([
                summary["name"],
                f"{summary['mean']:.4f}",
                f"{summary['median']:.4f}",
                f"{summary['std']:.4f}",
                f"{summary['min']:.4f}",
                f"{summary['max']:.4f}",
            ])
        lines.append(format_table(headers, rows))
        lines.append("")

    # Sample inspection
    samples = test_results.get("samples", [])
    if samples:
        lines.append(f"#### Sample translations (first 5)")
        lines.append("")
        for i, sample in enumerate(samples[:5]):
            lines.append(f"**Example {i+1}:**")
            if "original" in sample:
                lines.append(f"- **Original:** {sample['original'][:200]}...")
            if "ugf" in sample:
                lines.append(f"- **UGF:** {sample['ugf'][:200]}...")
            if "reconstructed" in sample:
                lines.append(f"- **Reconstructed:** {sample['reconstructed'][:200]}...")
            if "question" in sample:
                lines.append(f"- **Question:** {sample['question'][:200]}...")
            if "english_response" in sample:
                lines.append(f"- **Response:** {sample['english_response'][:200]}...")
            scores = sample.get("scores", {})
            if scores:
                score_str = ", ".join(f"{k}={v:.3f}" for k, v in scores.items())
                lines.append(f"- **Scores:** {score_str}")
            lines.append("")

    # Identify worst cases (lowest BERTScore or cosine)
    if samples and len(samples) > 5:
        key_metric = "bertscore_f1" if "bertscore_f1" in (samples[0].get("scores", {})) else None
        if key_metric is None:
            for k in samples[0].get("scores", {}):
                if "cosine" in k or "bertscore" in k:
                    key_metric = k
                    break

        if key_metric:
            sorted_samples = sorted(samples, key=lambda s: s.get("scores", {}).get(key_metric, 0))
            lines.append(f"#### Worst cases (lowest {key_metric})")
            lines.append("")
            for sample in sorted_samples[:3]:
                score = sample.get("scores", {}).get(key_metric, 0)
                orig = sample.get("original", sample.get("question", ""))[:150]
                recon = sample.get("reconstructed", sample.get("english_response", ""))[:150]
                lines.append(f"- [{key_metric}={score:.3f}] Original: {orig}...")
                lines.append(f"  Reconstructed: {recon}...")
                lines.append("")

    return "\n".join(lines)


def compare_tests(all_results: dict) -> str:
    """Produce a comparison across tests A, B, C."""
    lines = []
    lines.append("### Cross-test comparison")
    lines.append("")

    # Collect metrics that appear in all tests
    all_metrics = set()
    for test_results in all_results.values():
        all_metrics.update(test_results.get("metrics", {}).keys())

    if not all_metrics:
        return ""

    headers = ["Metric"] + [f"Test {t}" for t in sorted(all_results.keys())]
    rows = []
    for metric in sorted(all_metrics):
        row = [metric]
        for test in sorted(all_results.keys()):
            summary = all_results[test].get("metrics", {}).get(metric, {})
            mean = summary.get("mean", "-")
            if isinstance(mean, float):
                row.append(f"{mean:.4f}")
            else:
                row.append(str(mean))
        rows.append(row)

    lines.append(format_table(headers, rows))
    lines.append("")

    return "\n".join(lines)


def generate_report(all_results: dict, output_path: str | Path | None = None) -> str:
    """Generate a full markdown evaluation report."""
    lines = []
    lines.append("# Evaluation Report")
    lines.append("")
    lines.append(f"## Summary")
    lines.append("")

    # Per-test analysis
    for test_name in sorted(all_results.keys()):
        lines.append(analyze_test(test_name, all_results[test_name]))
        lines.append("")

    # Cross-test comparison (if multiple tests)
    if len(all_results) > 1:
        lines.append(compare_tests(all_results))

    report = "\n".join(lines)

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            f.write(report)
        print(f"Report saved to {output_path}")

    return report


def main():
    parser = argparse.ArgumentParser(description="Analyze evaluation results")
    parser.add_argument("results", nargs="+", help="Path(s) to result JSON files")
    parser.add_argument("--report", type=str, default=None,
                        help="Path to save markdown report")
    args = parser.parse_args()

    # Load and merge all results
    all_results = {}
    for path in args.results:
        data = load_results(path)
        # Results may be keyed by test name ("A", "B", "C") or be a single test
        if "test" in data:
            all_results[data["test"]] = data
        else:
            all_results.update(data)

    if not all_results:
        print("No results found.")
        return

    # Generate and print report
    report = generate_report(all_results, args.report)
    print(report)


if __name__ == "__main__":
    main()
