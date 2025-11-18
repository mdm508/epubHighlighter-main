"""
Preview Oxford Advanced Learner's Dictionary entries as standalone HTML.

Usage:
    python render_oald_preview.py abandon
    python render_oald_preview.py --out-dir ./anki_previews ability altruism
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from parse import render_entry_html
from parse_oald import OxfordAdvancedLearnersParser


def _safe_slug(word: str) -> str:
    slug = re.sub(r"[^0-9a-zA-Z_-]+", "-", word.strip())
    return f"oald_preview_{(slug.strip('-') or 'entry').lower()}.html"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render Oxford Advanced Learner's Dictionary entries to HTML."
    )
    parser.add_argument("word", nargs="+", help="Headwords to render.")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("anki_previews"),
        help="Directory to store generated HTML (default: ./anki_previews).",
    )
    parser.add_argument(
        "--heading-level",
        type=int,
        default=2,
        help="Heading level to use for the headword (default: h2).",
    )
    args = parser.parse_args()

    resolver = OxfordAdvancedLearnersParser()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    for word in args.word:
        try:
            entry = resolver.get_entry(word)
        except KeyError:
            print(f"[skip] '{word}' not found.")
            continue
        html = render_entry_html(entry, heading_level=args.heading_level)
        outfile = args.out_dir / _safe_slug(word)
        outfile.write_text(html, encoding="utf-8")
        print(f"[ok] Wrote {outfile}")


if __name__ == "__main__":
    main()
