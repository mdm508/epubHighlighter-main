#!/usr/bin/env python
import argparse
import os
import sys

import epub_highlighter  # this is your big script


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="EPUB highlighter + definitions + anki generator"
    )
    p.add_argument("--epub", help="Path to input EPUB", default=epub_highlighter.EPUB_PATH)
    p.add_argument("--out-dir", help="Directory for outputs (epub/*.epub, .tsv, etc.)", default=None)

    # toggles
    p.add_argument("--no-highlight", action="store_true", help="Do NOT generate highlighted book EPUB")
    p.add_argument("--no-defs", action="store_true", help="Do NOT generate definitions EPUB")
    p.add_argument("--no-anki", action="store_true", help="Do NOT generate Anki TSV")
    p.add_argument("--pdf", action="store_true", help="Also convert generated EPUBs to PDF (needs ebook-convert)")

    # auto wordlist
    p.add_argument("--auto-wordlist", action="store_true", help="Build word list from EPUB before processing")
    p.add_argument("--freq", type=float, default=None, help="Frequency threshold for auto-built list (lower = rarer)")

    # test mode
    p.add_argument("--test", action="store_true", help="Run in test mode (small number of defs)")
    p.add_argument("--test-max", type=int, default=None, help="Max defs to collect in test mode")

    return p.parse_args()


def main():
    args = parse_args()

    # 1) set EPUB path
    epub_highlighter.EPUB_PATH = args.epub

    # 2) if user gave an output dir, rewrite the output paths to that dir
    if args.out_dir:
        out_dir = args.out_dir
        os.makedirs(out_dir, exist_ok=True)
        base = os.path.splitext(os.path.basename(args.epub))[0]
        epub_highlighter.OUTPUT_EPUB_PATH = os.path.join(out_dir, f"{base}-highlighted.epub")
        epub_highlighter.OUTPUT_DEFS_EPUB_PATH = os.path.join(out_dir, f"{base}-definitions.epub")
        epub_highlighter.OUTPUT_ANKI_PATH = os.path.join(out_dir, f"{base}-defs-anki.tsv")
        epub_highlighter.OUTPUT_EPUB_PDF_PATH = os.path.join(out_dir, f"{base}-highlighted.pdf")
        epub_highlighter.OUTPUT_DEFS_PDF_PATH = os.path.join(out_dir, f"{base}-definitions.pdf")
        # also put auto-built wordlist there
        epub_highlighter.AUTO_WORDLIST_OUTPUT = os.path.join(out_dir, f"{base}-rare-words-auto.txt")

    # 3) toggles
    epub_highlighter.GENERATE_HIGHLIGHTED_EPUB = not args.no-highlight
    epub_highlighter.GENERATE_DEFS_EPUB = not args.no-defs
    epub_highlighter.GENERATE_ANKI = not args.no-anki
    epub_highlighter.CONVERT_EPUBS_TO_PDF = args.pdf

    # 4) auto wordlist
    if args.auto_wordlist:
        epub_highlighter.AUTO_BUILD_WORD_LIST = True
        if args.freq is not None:
            epub_highlighter.AUTO_WORDLIST_FREQ_THRESHOLD = args.freq
    else:
        epub_highlighter.AUTO_BUILD_WORD_LIST = False

    # 5) test mode
    if args.test:
        epub_highlighter.TEST_MODE = True
        if args.test_max is not None:
            epub_highlighter.TEST_MAX_DEFS = args.test_max
    else:
        epub_highlighter.TEST_MODE = False

    # 6) run the existing logic
    epub_highlighter.main()


if __name__ == "__main__":
    main()
