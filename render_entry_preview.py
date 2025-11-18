"""
Utility script to preview the Anki-ready HTML for parsed dictionary entries.

Usage:
    python tests/render_entry_preview.py abandon
    python tests/render_entry_preview.py --out-dir ./tmp_html abandon able
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from parse import ConciseOxfordParser, render_entry_html


def _safe_filename(word: str) -> str:
    slug = re.sub(r"[^0-9a-zA-Z_-]+", "-", word.strip())
    slug = slug.strip("-").lower() or "entry"
    return f"anki_preview_{slug}.html"


def main() -> None:
    parser = argparse.ArgumentParser(description="Render preview HTML for Anki cards.")
    parser.add_argument("word", nargs="+", help="Headwords to render.")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("anki_previews"),
        help="Directory to place the HTML previews (default: ./anki_previews).",
    )
    parser.add_argument(
        "--heading-level",
        type=int,
        default=2,
        help="Heading level to use for the headword (default: h2).",
    )
    args = parser.parse_args()

    resolver = ConciseOxfordParser()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    for word in args.word:
        try:
            entry = resolver.get_entry(word)
        except KeyError:
            print(f"[skip] '{word}' not found in dictionary.")
            continue

        html = render_entry_html(entry, heading_level=args.heading_level)
        outfile = args.out_dir / _safe_filename(word)
        outfile.write_text(html, encoding="utf-8")
        print(f"[ok] Wrote {outfile}")


if __name__ == "__main__":
    main()
