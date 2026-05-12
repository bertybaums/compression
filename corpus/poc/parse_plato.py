"""Generalized parser for Jowett's Plato dialogues (Project Gutenberg).

Each Jowett-Plato file follows the same convention: speaker turns begin with
SPEAKER. or SPEAKER: at line-start in ALL CAPS, content follows on the same
and subsequent lines until the next speaker marker. We extract consecutive
(A, B) pairs where the two turns are by different speakers.

The DIALOGUES registry holds per-dialogue configuration:
  - gutenberg_id: integer eBook number
  - speakers: set of canonical character labels
  - descriptor_map: per-character UGF-only descriptor that replaces the name

A shared CHARACTER_DESCRIPTORS table ensures that characters appearing in
multiple dialogues (Socrates, Glaucon, etc.) use the SAME descriptor across
the corpus. This is the rigid-designation-emergence design from
`memory/names_rigid_designators.md` — the descriptor's job is to *become* a
referring expression through repeated consistent use.

Output: one JSONL per dialogue at corpus/poc/<key>_pairs.jsonl, plus an
optional --combine output that concatenates all into a single file.

Usage:
    python3 corpus/poc/parse_plato.py --dialogue meno
    python3 corpus/poc/parse_plato.py --all
    python3 corpus/poc/parse_plato.py --all --combine corpus/poc/plato_combined.jsonl
"""

import argparse
import json
import os
import random
import re
import subprocess
from pathlib import Path

POC_DIR = Path(__file__).parent

# ---------------------------------------------------------------------------
# Cross-dialogue character descriptors
# ---------------------------------------------------------------------------
# Same character → same descriptor across every dialogue in the corpus. This
# is the operationalization of the rigid-designation-emergence experiment:
# the Reasoner sees "the old teacher" wherever Plato used SOCRATES, across
# every dialogue. Whether that descriptor comes to function as a name in the
# trained model's representations is what the post-training name-recovery
# experiment will test.

CHARACTER_DESCRIPTORS: dict[str, str] = {
    # Recurring across many dialogues
    "SOCRATES": "the old teacher",
    "GLAUCON": "the young brother",
    "ADEIMANTUS": "the older brother",
    "POLEMARCHUS": "the war fighter",
    "THRASYMACHUS": "the angry power man",
    "CEPHALUS": "the old rich man",
    "CHAEREPHON": "the close friend",

    # Meno
    "MENO": "the young man",
    "ANYTUS": "the angry man",
    "BOY": "the young helper",

    # Crito
    "CRITO": "the old friend",

    # Euthyphro
    "EUTHYPHRO": "the holy man",

    # Phaedo
    "PHAEDO": "the storyteller",
    "ECHECRATES": "the listener",
    "SIMMIAS": "the first questioner",
    "CEBES": "the second questioner",
    "APOLLODORUS": "the loud follower",

    # Gorgias
    "GORGIAS": "the famous teacher of speaking",
    "POLUS": "the hot one",
    "CALLICLES": "the strong rule man",

    # Theaetetus / Sophist / Statesman
    "THEAETETUS": "the bright young one",
    "THEODORUS": "the old number man",
    "STRANGER": "the visitor from far away",

    # Protagoras / others (room to extend without changing this file)
    "PROTAGORAS": "the great teacher",
    "HIPPOCRATES": "the eager young one",
    "HIPPIAS": "the many skill man",
    "PRODICUS": "the word careful man",

    # Charmides
    "CHARMIDES": "the young beautiful one",
    "CRITIAS": "the proud older one",
}


# ---------------------------------------------------------------------------
# Per-dialogue config: Gutenberg eBook ID + speakers list
# ---------------------------------------------------------------------------

DIALOGUES: dict[str, dict] = {
    "meno": {
        "gutenberg_id": 1643,
        "speakers": ["SOCRATES", "MENO", "ANYTUS", "BOY"],
        "out_path": POC_DIR / "meno_pairs.jsonl",
        "raw_path": POC_DIR / "meno_raw.txt",
        "dialogue_begin_marker": "PERSONS OF THE DIALOGUE",
    },
    "crito": {
        "gutenberg_id": 1657,
        "speakers": ["SOCRATES", "CRITO"],
        "out_path": POC_DIR / "crito_pairs.jsonl",
        "raw_path": POC_DIR / "crito_raw.txt",
        "dialogue_begin_marker": "PERSONS OF THE DIALOGUE",
    },
    "euthyphro": {
        "gutenberg_id": 1642,
        "speakers": ["SOCRATES", "EUTHYPHRO"],
        "out_path": POC_DIR / "euthyphro_pairs.jsonl",
        "raw_path": POC_DIR / "euthyphro_raw.txt",
        "dialogue_begin_marker": "PERSONS OF THE DIALOGUE",
    },
    "phaedo": {
        "gutenberg_id": 1658,
        "speakers": ["SOCRATES", "PHAEDO", "ECHECRATES", "SIMMIAS", "CEBES", "APOLLODORUS", "CRITO"],
        "out_path": POC_DIR / "phaedo_pairs.jsonl",
        "raw_path": POC_DIR / "phaedo_raw.txt",
        "dialogue_begin_marker": "PERSONS OF THE DIALOGUE",
    },
    "gorgias": {
        "gutenberg_id": 1672,
        "speakers": ["SOCRATES", "GORGIAS", "POLUS", "CALLICLES", "CHAEREPHON"],
        "out_path": POC_DIR / "gorgias_pairs.jsonl",
        "raw_path": POC_DIR / "gorgias_raw.txt",
        "dialogue_begin_marker": "PERSONS OF THE DIALOGUE",
    },
    "theaetetus": {
        "gutenberg_id": 1726,
        "speakers": ["SOCRATES", "THEAETETUS", "THEODORUS"],
        "out_path": POC_DIR / "theaetetus_pairs.jsonl",
        "raw_path": POC_DIR / "theaetetus_raw.txt",
        "dialogue_begin_marker": "PERSONS OF THE DIALOGUE",
    },
    # NOTE: Charmides (Gutenberg #1580) is narrated by Socrates rather than
    # presented as direct script, so it produces 0 pairs under our line-start
    # SPEAKER: parser. Skipping. Phaedo (narrated by Phaedo to Echecrates)
    # similarly only yields the brief framing exchange (~17 pairs); the main
    # body would need a Hume-style mid-paragraph "said X" parser.
    "protagoras": {
        "gutenberg_id": 1591,
        "speakers": ["SOCRATES", "PROTAGORAS", "HIPPOCRATES", "HIPPIAS", "PRODICUS",
                     "ALCIBIADES", "CALLIAS", "COMPANION"],
        "out_path": POC_DIR / "protagoras_pairs.jsonl",
        "raw_path": POC_DIR / "protagoras_raw.txt",
        "dialogue_begin_marker": "PERSONS OF THE DIALOGUE",
    },
}

# Add CHARACTER_DESCRIPTORS for dialogue-specific speakers not in the global table
CHARACTER_DESCRIPTORS.setdefault("ALCIBIADES", "the proud young noble")
CHARACTER_DESCRIPTORS.setdefault("CALLIAS", "the rich host")
CHARACTER_DESCRIPTORS.setdefault("COMPANION", "the friend who listens")


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

START = "*** START OF THE PROJECT GUTENBERG EBOOK"
END = "*** END OF THE PROJECT GUTENBERG EBOOK"
MIN_LEN = 20
MAX_LEN = 800
SEED = 42


def speaker_regex(speakers: list[str]) -> re.Pattern:
    """Build a line-start regex matching any of the dialogue's speakers.
    Accepts both 'SOCRATES.' and 'SOCRATES:' as separators (Jowett varies)."""
    alts = "|".join(re.escape(s) for s in speakers)
    return re.compile(rf"^({alts})[\.:]\s*(.*)$")


def download_if_missing(gid: int, raw_path: Path) -> None:
    if raw_path.exists() and raw_path.stat().st_size > 1000:
        return
    url = f"https://www.gutenberg.org/cache/epub/{gid}/pg{gid}.txt"
    print(f"  downloading {url} -> {raw_path}")
    # System Python's urllib can have SSL trust issues with Gutenberg's chain;
    # shell out to curl which uses the OS cert store.
    subprocess.run(
        ["curl", "-sSL", "-o", str(raw_path), url],
        check=True,
    )


def extract_turns(raw: str, speaker_re: re.Pattern, dialogue_begin: str | None) -> list[tuple[str, str]]:
    if START in raw and END in raw:
        raw = raw[raw.index(START):raw.index(END)]
    if dialogue_begin and dialogue_begin in raw:
        raw = raw[raw.index(dialogue_begin):]
    lines = raw.splitlines()
    turns: list[tuple[str, str]] = []
    cur_speaker: str | None = None
    cur_buf: list[str] = []

    def flush():
        if cur_speaker and cur_buf:
            content = " ".join(s.strip() for s in cur_buf).strip()
            content = re.sub(r"\s+", " ", content)
            turns.append((cur_speaker, content))

    for line in lines:
        m = speaker_re.match(line)
        if m:
            flush()
            cur_speaker, first = m.group(1), m.group(2)
            cur_buf = [first] if first else []
        else:
            if cur_speaker is not None and line.strip():
                cur_buf.append(line)
    flush()
    return turns


def parse_one(key: str) -> Path:
    cfg = DIALOGUES[key]
    download_if_missing(cfg["gutenberg_id"], cfg["raw_path"])

    raw = cfg["raw_path"].read_text(encoding="utf-8")
    speaker_re = speaker_regex(cfg["speakers"])
    turns = extract_turns(raw, speaker_re, cfg.get("dialogue_begin_marker"))
    print(f"  {key}: {len(turns)} total turns parsed.")

    # Verify descriptors exist for every named speaker in the dialogue
    missing = [s for s in cfg["speakers"] if s not in CHARACTER_DESCRIPTORS]
    if missing:
        raise SystemExit(f"  ERROR: no CHARACTER_DESCRIPTORS for {missing} in {key}")

    pairs: list[tuple[str, str, str, str]] = []
    for i in range(len(turns) - 1):
        a_spk, a_text = turns[i]
        b_spk, b_text = turns[i + 1]
        if a_spk == b_spk:
            continue
        if not (MIN_LEN <= len(a_text) <= MAX_LEN):
            continue
        if not (MIN_LEN <= len(b_text) <= MAX_LEN):
            continue
        pairs.append((a_spk, b_spk, a_text, b_text))
    print(f"  {key}: {len(pairs)} consecutive (A,B) pairs in [{MIN_LEN},{MAX_LEN}] chars.")

    with cfg["out_path"].open("w", encoding="utf-8") as f:
        for idx, (a_spk, b_spk, a_text, b_text) in enumerate(pairs, 1):
            rec = {
                "id": f"{key}_pair_{idx:03d}",
                "speaker_a": a_spk,
                "speaker_b": b_spk,
                "descriptor_a": CHARACTER_DESCRIPTORS[a_spk],
                "descriptor_b": CHARACTER_DESCRIPTORS[b_spk],
                "turn_a": a_text,
                "turn_b": b_text,
            }
            f.write(json.dumps(rec) + "\n")
    return cfg["out_path"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dialogue", help="single dialogue key (e.g. meno, crito)")
    ap.add_argument("--all", action="store_true", help="parse every configured dialogue")
    ap.add_argument("--limit", type=int, default=None, help="ignored — parse_plato emits all pairs")
    args = ap.parse_args()

    if not (args.dialogue or args.all):
        print("Available dialogues:", ", ".join(DIALOGUES.keys()))
        return

    if args.all:
        keys = list(DIALOGUES.keys())
    else:
        if args.dialogue not in DIALOGUES:
            raise SystemExit(f"Unknown dialogue '{args.dialogue}'. Available: {list(DIALOGUES.keys())}")
        keys = [args.dialogue]

    for k in keys:
        print(f"== {k} ==")
        parse_one(k)


if __name__ == "__main__":
    main()
