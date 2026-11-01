"""Convert the per-chapter PDFs into a Markdown corpus with page markers.

Each page is preceded by `<!-- page 13-1 (pdf p.616) -->`, giving the handbook's
printed page label and the page number in the original PDF.

Usage: python scripts/pdf_to_markdown.py [source.pdf] [chapters_dir] [corpus_dir]
"""
import json
import logging
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pymupdf4llm
from pypdf import PdfReader

from split_chapters import DEFAULT_INPUT, DEFAULT_OUTPUT, find_sections

logging.getLogger("pypdf").setLevel(logging.ERROR)

DEFAULT_CORPUS = Path("corpus")


def convert(args):
    pdf_path, md_path, labels, first_page = args
    pages = pymupdf4llm.to_markdown(pdf_path, page_chunks=True, show_progress=False)
    parts = []
    for i, page in enumerate(pages):
        parts.append(f"<!-- page {labels[i]} (pdf p.{first_page + i}) -->\n\n{page['text'].strip()}\n")
    Path(md_path).write_text("\n".join(parts), encoding="utf-8")
    return len(pages)


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INPUT
    chapters_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUTPUT
    corpus_dir = Path(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_CORPUS
    corpus_dir.mkdir(parents=True, exist_ok=True)

    reader = PdfReader(src)
    sections = find_sections(reader)
    jobs, manifest = [], []
    for name, first, last in sections:
        labels = reader.page_labels[first:last + 1]
        jobs.append((str(chapters_dir / f"{name}.pdf"), str(corpus_dir / f"{name}.md"), labels, first + 1))
        manifest.append({
            "id": name,
            "file": f"{name}.md",
            "source_pdf": f"{chapters_dir.as_posix()}/{name}.pdf",
            "pdf_pages": [first + 1, last + 1],
            "page_labels": [labels[0], labels[-1]],
        })

    # Skip documents already converted, so an interrupted run can resume.
    pending = [(job, entry) for job, entry in zip(jobs, manifest) if not Path(job[1]).exists()]
    print(f"{len(manifest) - len(pending)} already converted, {len(pending)} to go")
    # Leave cores free so the machine stays responsive.
    with ProcessPoolExecutor(max_workers=max(1, (os.cpu_count() or 2) // 2)) as pool:
        for (job, entry), count in zip(pending, pool.map(convert, [job for job, _ in pending])):
            size = (corpus_dir / entry["file"]).stat().st_size
            print(f"{entry['file']:62} {count:4} pages {size / 1e3:8.1f} KB", flush=True)

    (corpus_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
