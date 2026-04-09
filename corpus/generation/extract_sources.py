"""
Extract English text passages from source material for UGF translation.

Sources:
  1. good-thinking-bot corpus (27K records, structured JSONL)
  2. intro-ethics textbook manuscript (13 chapters, Markdown)

Output: corpus/processed/english_passages.jsonl
  Each record: {"id": str, "source": str, "field": str, "text": str, "metadata": {...}}
"""

import json
import re
import hashlib
from pathlib import Path

# --- Paths ---
GOOD_THINKING_CORPUS = Path(
    "/Users/bbaum/Documents/claude-projects/good-thinking-bot/"
    "corpus-tools/output/release/good-thinking-corpus-v1.0.jsonl"
)
ETHICS_MANUSCRIPT_DIR = Path(
    "/Users/bbaum/Documents/claude-projects/intro-ethics/"
    "intro-ethics-textbook/manuscript"
)
OUTPUT_PATH = Path(__file__).parent.parent / "processed" / "english_passages.jsonl"

# --- Text fields to extract from good-thinking-bot records ---
GTB_TEXT_FIELDS = [
    ("scenario.text", lambda r: r.get("scenario", {}).get("text")),
    ("scenario.context", lambda r: r.get("scenario", {}).get("context")),
    ("scenario.speaker_context", lambda r: r.get("scenario", {}).get("speaker_context")),
    ("structure.pattern_description", lambda r: r.get("structure", {}).get("pattern_description")),
    ("structure.why_wrong", lambda r: r.get("structure", {}).get("why_wrong")),
    ("structure.why_right", lambda r: r.get("structure", {}).get("why_right")),
    ("structure.counterpoint", lambda r: r.get("structure", {}).get("counterpoint")),
    ("assessment.identification_prompt", lambda r: r.get("assessment", {}).get("identification_prompt")),
    ("assessment.follow_up_if_wrong", lambda r: r.get("assessment", {}).get("follow_up_if_wrong")),
    ("assessment.follow_up_if_right", lambda r: r.get("assessment", {}).get("follow_up_if_right")),
    ("game_hooks.npc_dialogue_seed", lambda r: r.get("game_hooks", {}).get("npc_dialogue_seed")),
]


def content_hash(text: str) -> str:
    """Short hash for deduplication."""
    return hashlib.md5(text.encode()).hexdigest()[:12]


def extract_good_thinking_bot() -> list[dict]:
    """Extract text passages from good-thinking-bot corpus records."""
    passages = []
    seen_hashes = set()

    with open(GOOD_THINKING_CORPUS, "r", encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            record_id = record["id"]
            taxonomy = record.get("taxonomy_code", "")
            track = record.get("track", "")
            tier = record.get("difficulty_tier", "")

            for field_name, extractor in GTB_TEXT_FIELDS:
                text = extractor(record)
                if not text or not text.strip():
                    continue

                text = text.strip()

                # Skip very short passages (< 20 chars) -- not useful for translation
                if len(text) < 20:
                    continue

                # Deduplicate by content hash
                h = content_hash(text)
                if h in seen_hashes:
                    continue
                seen_hashes.add(h)

                passages.append({
                    "id": f"gtb-{record_id}-{field_name.replace('.', '_')}",
                    "source": "good-thinking-bot",
                    "field": field_name,
                    "text": text,
                    "metadata": {
                        "taxonomy_code": taxonomy,
                        "track": track,
                        "difficulty_tier": tier,
                    },
                })

    return passages


def chunk_markdown(text: str, max_words: int = 500, overlap_words: int = 50) -> list[str]:
    """Split markdown text into overlapping chunks by paragraph boundaries.

    Tries to split at paragraph breaks (double newlines). If a paragraph
    exceeds max_words, splits at sentence boundaries within it.
    """
    # Remove markdown headers, keeping content
    # But preserve paragraph structure
    paragraphs = re.split(r"\n\n+", text)

    chunks = []
    current_chunk_words = []
    current_word_count = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # Skip pure markdown artifacts (images, horizontal rules, etc.)
        if re.match(r"^(!?\[|---+|===+|\*\*\*+|#{1,6}\s*$)", para):
            continue

        # Strip markdown formatting but keep text
        para = re.sub(r"#{1,6}\s+", "", para)  # headers
        para = re.sub(r"\*\*([^*]+)\*\*", r"\1", para)  # bold
        para = re.sub(r"\*([^*]+)\*", r"\1", para)  # italic
        para = re.sub(r"`([^`]+)`", r"\1", para)  # inline code
        para = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", para)  # links

        para_words = para.split()
        para_word_count = len(para_words)

        if current_word_count + para_word_count > max_words and current_chunk_words:
            # Flush current chunk
            chunks.append(" ".join(current_chunk_words))
            # Keep overlap
            if overlap_words > 0 and len(current_chunk_words) > overlap_words:
                current_chunk_words = current_chunk_words[-overlap_words:]
                current_word_count = len(current_chunk_words)
            else:
                current_chunk_words = []
                current_word_count = 0

        current_chunk_words.extend(para_words)
        current_word_count += para_word_count

    # Flush remaining
    if current_chunk_words:
        chunks.append(" ".join(current_chunk_words))

    return chunks


def extract_ethics_textbook() -> list[dict]:
    """Extract text passages from intro-ethics textbook manuscript."""
    passages = []
    seen_hashes = set()

    chapter_files = sorted(ETHICS_MANUSCRIPT_DIR.rglob("*.md"))

    for chapter_path in chapter_files:
        # Skip back-matter files that aren't content (bibliography, about-authors)
        rel = chapter_path.relative_to(ETHICS_MANUSCRIPT_DIR)
        if any(skip in str(rel) for skip in ["bibliography", "about-authors", "appendix-b"]):
            continue

        text = chapter_path.read_text(encoding="utf-8")

        # Extract chapter name from filename
        chapter_name = chapter_path.stem

        chunks = chunk_markdown(text, max_words=500, overlap_words=50)

        for i, chunk in enumerate(chunks):
            if len(chunk.split()) < 15:  # skip tiny chunks
                continue

            h = content_hash(chunk)
            if h in seen_hashes:
                continue
            seen_hashes.add(h)

            passages.append({
                "id": f"ethics-{chapter_name}-{i:04d}",
                "source": "intro-ethics",
                "field": "textbook",
                "text": chunk,
                "metadata": {
                    "chapter": chapter_name,
                    "chunk_index": i,
                },
            })

    return passages


def main():
    print("Extracting from good-thinking-bot corpus...")
    gtb_passages = extract_good_thinking_bot()
    print(f"  Extracted {len(gtb_passages)} passages")

    print("Extracting from intro-ethics textbook...")
    ethics_passages = extract_ethics_textbook()
    print(f"  Extracted {len(ethics_passages)} passages")

    all_passages = gtb_passages + ethics_passages
    print(f"\nTotal passages: {len(all_passages)}")

    # Stats
    total_words = sum(len(p["text"].split()) for p in all_passages)
    avg_words = total_words / len(all_passages) if all_passages else 0
    print(f"Total words: {total_words:,}")
    print(f"Average words per passage: {avg_words:.1f}")

    # By source
    for source in ["good-thinking-bot", "intro-ethics"]:
        src_passages = [p for p in all_passages if p["source"] == source]
        src_words = sum(len(p["text"].split()) for p in src_passages)
        print(f"  {source}: {len(src_passages)} passages, {src_words:,} words")

    # By field (for good-thinking-bot)
    print("\nGood-thinking-bot passages by field:")
    field_counts = {}
    for p in gtb_passages:
        field_counts[p["field"]] = field_counts.get(p["field"], 0) + 1
    for field, count in sorted(field_counts.items(), key=lambda x: -x[1]):
        print(f"  {field}: {count}")

    # Write output
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for passage in all_passages:
            f.write(json.dumps(passage, ensure_ascii=False) + "\n")

    print(f"\nWrote {len(all_passages)} passages to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
