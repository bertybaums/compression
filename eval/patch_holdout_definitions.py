"""
Repair the truncated `question` field in counterexample_analysis items in
holdout_bench.jsonl, using the original cx-bot definitions.

The bug was in `corpus/generation/cxbot_ugf_to_reasoning.py:57`, which
truncated definitions to 80 chars. The fix has been applied; this script
rebuilds the holdout entries that were affected.

Lookup logic:
  Holdout id format: cxbot-{cx_type}-{orig_id_with_dashes}-reasoning
  Example: cxbot-defcx-defcx-logic-consistency-4772-reasoning
  Strip: cxbot-{cx_type}- prefix, -reasoning suffix
  Replace '-' with '_': defcx_logic_consistency_4772
  Look up in the cx-bot JSONL files under the corresponding domain.
"""

import argparse
import json
from pathlib import Path


def build_lookup(cxbot_root: Path) -> dict[str, dict]:
    """Build {original_id: record} lookup across all cx-bot data files."""
    lookup = {}
    for cx_type in ("defcx", "abdcx"):
        dir_ = cxbot_root / "data" / cx_type
        for path in sorted(dir_.glob("*.jsonl")):
            with open(path) as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    r = json.loads(line)
                    if "id" in r:
                        lookup[r["id"]] = r
    return lookup


def parse_holdout_id(item_id: str) -> str | None:
    """Convert holdout id to cx-bot original id, or None if not a cxbot item.

    Holdout ids look like: cxbot-{cx_type}-{orig_id_with_dashes}-{passage|reasoning}
    The orig_id already starts with `{cx_type}_` (e.g., defcx_logic_consistency_0001),
    so after stripping the cxbot- prefix and the cx_type- segment, the remainder
    is the orig_id with dashes-for-underscores.
    """
    if not item_id.startswith("cxbot-"):
        return None
    rest = item_id[len("cxbot-"):]
    if rest.endswith("-reasoning"):
        rest = rest[: -len("-reasoning")]
    elif rest.endswith("-passage"):
        rest = rest[: -len("-passage")]
    if rest.startswith("defcx-"):
        body = rest[len("defcx-"):]
    elif rest.startswith("abdcx-"):
        body = rest[len("abdcx-"):]
    else:
        return None
    return body.replace("-", "_")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="eval/sets/holdout_bench.jsonl")
    p.add_argument("--output", default="eval/sets/holdout_bench_patched.jsonl")
    p.add_argument("--cxbot-root", default="/Users/bbaum/Documents/_RCDS/_external/cx-bot")
    args = p.parse_args()

    lookup = build_lookup(Path(args.cxbot_root))
    print(f"Loaded {len(lookup)} cx-bot records")

    n_total = 0
    n_cx = 0
    n_patched = 0
    n_missing = 0
    out_lines = []
    with open(args.input) as fh:
        for line in fh:
            n_total += 1
            r = json.loads(line)
            if r.get("type") != "counterexample_analysis":
                out_lines.append(json.dumps(r, ensure_ascii=False))
                continue
            n_cx += 1
            orig_id = parse_holdout_id(r["id"])
            if orig_id is None:
                out_lines.append(json.dumps(r, ensure_ascii=False))
                continue
            cx_record = lookup.get(orig_id)
            if cx_record is None:
                n_missing += 1
                print(f"  MISS: {r['id']} -> {orig_id}")
                out_lines.append(json.dumps(r, ensure_ascii=False))
                continue
            full_definition = cx_record.get("definition", "")
            if not full_definition:
                n_missing += 1
                out_lines.append(json.dumps(r, ensure_ascii=False))
                continue
            r["question"] = f"counterexample to: {full_definition}"
            r["definition"] = full_definition
            r["counterexample"] = cx_record.get("counterexample", "")
            r["missing_condition"] = cx_record.get("missing_condition", "")
            n_patched += 1
            out_lines.append(json.dumps(r, ensure_ascii=False))

    with open(args.output, "w") as fh:
        fh.write("\n".join(out_lines) + "\n")

    print(f"Total items: {n_total}")
    print(f"  counterexample_analysis: {n_cx}")
    print(f"  patched: {n_patched}")
    print(f"  could not patch: {n_missing}")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
