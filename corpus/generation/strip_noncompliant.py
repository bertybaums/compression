"""
Pre-restart cleanup: remove non-compliant entries from the parallel corpus
and their IDs from the progress file so they get reprocessed.

Run this BEFORE restarting generate_parallel.py with updated prompts.

Usage:
    python corpus/generation/strip_noncompliant.py [--dry-run]
"""

import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
CORPUS_PATH = ROOT / "corpus" / "processed" / "parallel_corpus.jsonl"
PROGRESS_PATH = ROOT / "corpus" / "processed" / "parallel_progress.json"


def main(dry_run: bool = False):
    # Read all entries
    entries = []
    with open(CORPUS_PATH) as f:
        for line in f:
            entries.append(json.loads(line))

    compliant = [e for e in entries if e.get("compliant", True)]
    non_compliant = [e for e in entries if not e.get("compliant", True)]

    print(f"Total entries: {len(entries)}")
    print(f"Compliant (keeping): {len(compliant)}")
    print(f"Non-compliant (removing): {len(non_compliant)}")

    non_compliant_ids = {e["id"] for e in non_compliant}

    # Load progress
    with open(PROGRESS_PATH) as f:
        progress = json.load(f)

    old_count = len(progress["completed_ids"])
    new_completed = [id_ for id_ in progress["completed_ids"] if id_ not in non_compliant_ids]

    print(f"Progress IDs: {old_count} -> {len(new_completed)} (removing {old_count - len(new_completed)})")

    if dry_run:
        print("\n[DRY RUN] No files modified.")
        return

    # Backup originals
    shutil.copy2(CORPUS_PATH, CORPUS_PATH.with_suffix(".jsonl.bak"))
    shutil.copy2(PROGRESS_PATH, PROGRESS_PATH.with_suffix(".json.bak"))
    print("\nBackups created (.bak files)")

    # Write cleaned corpus
    with open(CORPUS_PATH, "w", encoding="utf-8") as f:
        for entry in compliant:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # Update progress
    progress["completed_ids"] = new_completed
    progress["stats"]["completed"] = len(new_completed)
    progress["stats"]["non_compliant"] = 0
    with open(PROGRESS_PATH, "w") as f:
        json.dump(progress, f)

    print(f"Wrote {len(compliant)} entries to {CORPUS_PATH}")
    print(f"Updated progress: {len(new_completed)} completed IDs")
    print("\nReady to restart generate_parallel.py")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Strip non-compliant entries for reprocessing")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
