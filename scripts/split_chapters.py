"""Split the handbook PDF into one PDF per chapter, using its bookmarks.

Usage: python scripts/split_chapters.py [input.pdf] [output_dir]
"""
import logging
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from pypdf import PdfReader, PdfWriter

logging.getLogger("pypdf").setLevel(logging.ERROR)

DEFAULT_INPUT = Path("DATA/amtg_handbook.pdf")
DEFAULT_OUTPUT = Path("DATA/chapters")


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def find_sections(reader):
    """Return (filename, first_page, last_page) tuples, 0-based and inclusive."""
    outline = []
    for item in reader.outline:
        if not isinstance(item, list):
            outline.append((item.title.strip(), reader.get_destination_page_number(item)))

    starts = []
    for i, (title, page) in enumerate(outline):
        chapter = re.fullmatch(r"Chapter (\d+)", title)
        if chapter:
            # The chapter's name is the bookmark right after "Chapter N".
            name = outline[i + 1][0] if i + 1 < len(outline) else ""
            starts.append((f"ch{int(chapter.group(1)):02d}_{slugify(name)}", page))
        elif title in ("Glossary", "Index"):
            starts.append((slugify(title), page))

    sections = [("00_front-matter", 0, starts[0][1] - 1)] if starts[0][1] > 0 else []
    for i, (name, start) in enumerate(starts):
        end = starts[i + 1][1] - 1 if i + 1 < len(starts) else len(reader.pages) - 1
        sections.append((name, start, end))
    return sections


def write_section(args):
    src, out_dir, name, first, last = args
    reader = PdfReader(src)
    writer = PdfWriter()
    for page in range(first, last + 1):
        writer.add_page(reader.pages[page])
    out = Path(out_dir) / f"{name}.pdf"
    with open(out, "wb") as f:
        writer.write(f)
    return name, first + 1, last + 1


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INPUT
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUTPUT
    out_dir.mkdir(parents=True, exist_ok=True)

    sections = find_sections(PdfReader(src))
    jobs = [(str(src), str(out_dir), name, first, last) for name, first, last in sections]
    with ProcessPoolExecutor() as pool:
        for name, first, last in pool.map(write_section, jobs):
            print(f"{name}.pdf  pages {first}-{last} ({last - first + 1})")


if __name__ == "__main__":
    main()
