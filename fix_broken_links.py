"""
Fix broken wikilinks in the Obsidian vault wiki/ directory.

Categories handled:
1. raw/inbound/meeting-notes/SLUG -> resolve to wiki/meetings/ stem
2. raw/inbound/ideas/SLUG -> remove brackets
3. raw/inbound/clippings/SLUG -> remove brackets
4. raw/inbound/ other -> remove brackets
5. Bare meeting stems (YYYY-MM-DD-HHMM-...) -> resolve to wiki/meetings/
6. Relative paths ../../domain/... -> check existence, remove if not found
7. Other: Projects/synthesis-*, ideas/*, etc.

Safety: ONLY modifies body text (after YAML frontmatter). Never touches frontmatter.
"""

import re
import os
from pathlib import Path
from collections import defaultdict

VAULT = Path(r"i:/Work/Sutochno_ru/08 project hotels claude")
WIKI = VAULT / "wiki"

# Wikilink pattern: [[target]] or [[target|display]]
WIKILINK_RE = re.compile(r'\[\[([^\]]+)\]\]')

# Date-time prefix pattern for meetings: YYYY-MM-DD-HHMM
DATE_PREFIX_RE = re.compile(r'^(\d{4}-\d{2}-\d{2}-\d{4})')


def build_meeting_index():
    """Build indexes for wiki/meetings/*.md files."""
    meetings_dir = WIKI / "meetings"
    stems = {}          # full stem -> stem
    date_prefix = {}    # first 15 chars -> full stem (YYYY-MM-DD-HHMM)

    if not meetings_dir.exists():
        return stems, date_prefix

    for f in meetings_dir.glob("*.md"):
        stem = f.stem
        stems[stem] = stem
        # Extract date prefix (first 15 chars: YYYY-MM-DD-HHMM)
        if len(stem) >= 15:
            prefix = stem[:15]
            date_prefix[prefix] = stem

    return stems, date_prefix


def build_wiki_stem_index():
    """Build an index of all wiki .md file stems for general resolution."""
    stem_to_path = {}
    for f in WIKI.rglob("*.md"):
        stem_to_path[f.stem] = f
    return stem_to_path


def build_ideas_stem_index():
    """Build an index of idea files under wiki/domains/*/ideas/."""
    ideas = {}
    domains_dir = WIKI / "domains"
    if not domains_dir.exists():
        return ideas
    for ideas_dir in domains_dir.rglob("ideas"):
        if ideas_dir.is_dir():
            for f in ideas_dir.glob("*.md"):
                ideas[f.stem] = f
    return ideas


def split_frontmatter(text):
    """Split file into frontmatter and body.

    Returns (frontmatter, body, has_frontmatter).
    frontmatter includes the closing --- and newline.
    """
    if not text.startswith('---'):
        return '', text, False

    # Find the second ---
    # The first --- is at position 0
    second_sep = text.find('\n---', 3)
    if second_sep == -1:
        # No closing ---, treat entire file as body
        return '', text, False

    # Find the end of the --- line
    end_of_sep = text.find('\n', second_sep + 1)
    if end_of_sep == -1:
        # --- is at end of file
        frontmatter = text
        body = ''
    else:
        frontmatter = text[:end_of_sep + 1]
        body = text[end_of_sep + 1:]

    return frontmatter, body, True


def resolve_link(target, display, source_file, meeting_stems, meeting_date_prefix,
                 wiki_stems, ideas_index, stats):
    """Resolve a single broken wikilink. Returns the replacement string or None if no change."""

    original_full = f'[[{target}|{display}]]' if display else f'[[{target}]]'

    # Category 1: raw/inbound/meeting-notes/SLUG
    if target.startswith('raw/inbound/meeting-notes/'):
        slug = target[len('raw/inbound/meeting-notes/'):]
        # Remove .md extension if present
        if slug.endswith('.md'):
            slug = slug[:-3]

        # Direct match
        if slug in meeting_stems:
            replacement = f'[[{slug}|{display}]]' if display else f'[[{slug}]]'
            stats['cat1_resolved'] += 1
            return replacement

        # Try date prefix match
        if len(slug) >= 15:
            prefix = slug[:15]
            if prefix in meeting_date_prefix:
                new_stem = meeting_date_prefix[prefix]
                replacement = f'[[{new_stem}|{display}]]' if display else f'[[{new_stem}]]'
                stats['cat1_date_resolved'] += 1
                return replacement

        # No match - remove brackets
        text = display if display else slug
        stats['cat1_unresolved'] += 1
        return text

    # Category 2: raw/inbound/ideas/SLUG
    if target.startswith('raw/inbound/ideas/'):
        text = display if display else target[len('raw/inbound/ideas/'):]
        if text.endswith('.md'):
            text = text[:-3]
        stats['cat2'] += 1
        return text

    # Category 3: raw/inbound/clippings/SLUG
    if target.startswith('raw/inbound/clippings/'):
        text = display if display else target[len('raw/inbound/clippings/'):]
        if text.endswith('.md'):
            text = text[:-3]
        stats['cat3'] += 1
        return text

    # Category 4: raw/inbound/ other (daily-logs, tasks, misc)
    if target.startswith('raw/inbound/'):
        text = display if display else target.split('/')[-1]
        if text.endswith('.md'):
            text = text[:-3]
        stats['cat4'] += 1
        return text

    # Also catch raw/ without inbound (just in case)
    if target.startswith('raw/'):
        text = display if display else target.split('/')[-1]
        if text.endswith('.md'):
            text = text[:-3]
        stats['cat4'] += 1
        return text

    # Category 5: Bare meeting stems (YYYY-MM-DD-HHMM-...)
    date_match = DATE_PREFIX_RE.match(target)
    if date_match:
        prefix = target[:15] if len(target) >= 15 else target
        if prefix in meeting_date_prefix:
            new_stem = meeting_date_prefix[prefix]
            if new_stem != target:  # Only fix if different
                replacement = f'[[{new_stem}|{display}]]' if display else f'[[{new_stem}]]'
                stats['cat5_resolved'] += 1
                return replacement
            else:
                # Already correct
                return None
        else:
            # No match - remove brackets
            text = display if display else target
            stats['cat5_unresolved'] += 1
            return text

    # Category 6: Relative paths ../../
    if target.startswith('../'):
        # Resolve relative to source file's directory
        source_dir = source_file.parent
        # Handle .md extension
        rel_target = target
        if not rel_target.endswith('.md'):
            rel_target += '.md'

        resolved = (source_dir / rel_target).resolve()
        # Check if it exists within wiki/
        try:
            resolved.relative_to(WIKI.resolve())
            if resolved.exists():
                # File exists in wiki - leave as-is
                return None
        except ValueError:
            pass

        # File not found - remove brackets
        text = display if display else target.split('/')[-1]
        if text.endswith('.md'):
            text = text[:-3]
        stats['cat6'] += 1
        return text

    # Category 7: Other
    # Projects/synthesis-* -> stem only
    if target.startswith('Projects/synthesis-'):
        stem = target[len('Projects/'):]
        if stem.endswith('.md'):
            stem = stem[:-3]
        # Check if synthesis file exists in wiki
        if stem in wiki_stems:
            replacement = f'[[{stem}|{display}]]' if display else f'[[{stem}]]'
            stats['cat7_synthesis_resolved'] += 1
            return replacement
        text = display if display else stem
        stats['cat7_synthesis'] += 1
        return text

    # ideas/IDEA-* or ideas/input-* or ideas/analysis-*
    if target.startswith('ideas/'):
        slug = target[len('ideas/'):]
        if slug.endswith('.md'):
            slug = slug[:-3]

        # Try matching against ideas index
        for idea_stem, idea_path in ideas_index.items():
            if slug in idea_stem or idea_stem.startswith(slug[:20]):
                replacement = f'[[{idea_stem}|{display}]]' if display else f'[[{idea_stem}]]'
                stats['cat7_ideas_resolved'] += 1
                return replacement

        # Try stem-only match in wiki
        if slug in wiki_stems:
            replacement = f'[[{slug}|{display}]]' if display else f'[[{slug}]]'
            stats['cat7_ideas_resolved'] += 1
            return replacement

        # No match - remove brackets
        text = display if display else slug
        stats['cat7_ideas'] += 1
        return text

    # Other unrecognized patterns - don't touch them (they may be valid)
    return None


def process_file(filepath, meeting_stems, meeting_date_prefix, wiki_stems, ideas_index, stats):
    """Process a single .md file, fixing broken wikilinks in the body only."""
    try:
        text = filepath.read_text(encoding='utf-8')
    except (UnicodeDecodeError, OSError) as e:
        print(f"  SKIP (read error): {filepath} - {e}")
        return False, []

    frontmatter, body, has_fm = split_frontmatter(text)

    if not body.strip():
        return False, []

    changes = []

    def replace_link(match):
        full_match = match.group(0)
        inner = match.group(1)

        # Parse target and display
        # Handle escaped pipe in Obsidian: \|
        if '\\|' in inner:
            parts = inner.split('\\|', 1)
        elif '|' in inner:
            parts = inner.split('|', 1)
        else:
            parts = [inner]

        target = parts[0].strip()
        display = parts[1].strip() if len(parts) > 1 else None

        # Skip links that don't look broken (no path separators, not raw/, not date-prefixed)
        is_broken_candidate = (
            target.startswith('raw/') or
            target.startswith('../') or
            target.startswith('Projects/') or
            target.startswith('ideas/') or
            bool(DATE_PREFIX_RE.match(target))
        )

        if not is_broken_candidate:
            return full_match

        result = resolve_link(target, display, filepath, meeting_stems,
                             meeting_date_prefix, wiki_stems, ideas_index, stats)

        if result is None:
            return full_match

        changes.append((full_match, result))
        return result

    new_body = WIKILINK_RE.sub(replace_link, body)

    if new_body == body:
        return False, []

    # Write back
    new_text = frontmatter + new_body
    filepath.write_text(new_text, encoding='utf-8')

    return True, changes


def main():
    print("Building indexes...")
    meeting_stems, meeting_date_prefix = build_meeting_index()
    print(f"  Meetings: {len(meeting_stems)} files, {len(meeting_date_prefix)} date prefixes")

    wiki_stems = build_wiki_stem_index()
    print(f"  Wiki stems: {len(wiki_stems)} files")

    ideas_index = build_ideas_stem_index()
    print(f"  Ideas: {len(ideas_index)} files")

    print(f"\nScanning wiki files (excluding raw/)...")

    stats = defaultdict(int)
    files_scanned = 0
    files_modified = 0
    total_links_fixed = 0

    # Collect all wiki .md files, excluding raw/
    wiki_files = []
    for f in WIKI.rglob("*.md"):
        # Skip any files under raw/ directory
        try:
            rel = f.relative_to(WIKI)
            parts = rel.parts
            if parts and parts[0] == 'raw':
                continue
        except ValueError:
            continue
        wiki_files.append(f)

    wiki_files.sort()
    print(f"  Found {len(wiki_files)} wiki files to scan\n")

    for filepath in wiki_files:
        files_scanned += 1
        modified, changes = process_file(filepath, meeting_stems, meeting_date_prefix,
                                          wiki_stems, ideas_index, stats)

        if modified:
            files_modified += 1
            total_links_fixed += len(changes)
            rel_path = filepath.relative_to(VAULT)
            print(f"FIXED: {rel_path}")
            for old, new in changes:
                print(f"  {old} -> {new}")
            print()

    # Summary
    print("=" * 70)
    print("SUMMARY:")
    print(f"  Files scanned: {files_scanned}")
    print(f"  Files modified: {files_modified}")
    print(f"  Links fixed: {total_links_fixed}")
    print()
    print("  By category:")
    print(f"    Cat 1 (raw/meeting-notes -> wiki match):     {stats['cat1_resolved']}")
    print(f"    Cat 1 (raw/meeting-notes -> date match):     {stats['cat1_date_resolved']}")
    print(f"    Cat 1 (raw/meeting-notes -> unresolved):     {stats['cat1_unresolved']}")
    print(f"    Cat 2 (raw/ideas -> brackets removed):       {stats['cat2']}")
    print(f"    Cat 3 (raw/clippings -> brackets removed):   {stats['cat3']}")
    print(f"    Cat 4 (raw/other -> brackets removed):       {stats['cat4']}")
    print(f"    Cat 5 (bare meeting stem -> resolved):       {stats['cat5_resolved']}")
    print(f"    Cat 5 (bare meeting stem -> unresolved):     {stats['cat5_unresolved']}")
    print(f"    Cat 6 (relative paths -> removed):           {stats['cat6']}")
    print(f"    Cat 7 (synthesis -> resolved):               {stats['cat7_synthesis_resolved']}")
    print(f"    Cat 7 (synthesis -> unresolved):             {stats['cat7_synthesis']}")
    print(f"    Cat 7 (ideas -> resolved):                   {stats['cat7_ideas_resolved']}")
    print(f"    Cat 7 (ideas -> unresolved):                 {stats['cat7_ideas']}")


if __name__ == '__main__':
    main()
