"""One-shot script: process a single transcript file and save to Meetings/."""
import sys
from pathlib import Path
from knowledge_engine.claude_client import process_meeting_transcript

vault = Path("/vault")
raw_file = vault / "raw" / "meetings" / "2026-04-27 0935 (MSK) R6  Daily.txt"

if not raw_file.exists():
    print(f"ERROR: file not found: {raw_file}")
    sys.exit(1)

text = raw_file.read_text(encoding="utf-8")
print(f"Read {len(text)} chars from {raw_file.name}")

result = process_meeting_transcript(text)
print(f"Claude returned {len(result)} chars")

meetings = vault / "Meetings"
meetings.mkdir(parents=True, exist_ok=True)
out = meetings / "2026-04-27-R6-Daily.md"
out.write_text(result, encoding="utf-8")
print(f"Saved to {out}")
