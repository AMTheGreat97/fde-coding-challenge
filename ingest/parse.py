"""Parse chapter Markdown into documents, sections and chunks.

Only the 14 chapter bodies (corpus/chNN_*.md) are read. The section tree comes
from Markdown heading lines alone; the converter's `#` counts are unreliable,
so the heading's emphasis style decides its level. Page markers are kept only
to label citations and never enter model or search text.
"""
import re
from pathlib import Path

from rag.text import strip_tags

CHAPTER_GLOB = "ch[0-9][0-9]_*.md"
PAGE_MARKER = re.compile(r"^<!-- page (\S+) \(pdf p\.(\d+)\) -->$")
HEADING = re.compile(r"^#{1,6}\s+(.*\S)\s*$")
PAGE_FOOTER = re.compile(r"^\d{1,2}-\d{1,3}$")
LIST_ITEM = re.compile(r"^\s*(?:[-*•]|\d+[.)]|[a-z][.)])\s+")
CROSS_REF = re.compile(r"\bChapter (\d{1,2})\b")

MIN_SECTION_CHARS = 600      # ~150 tokens; smaller sections merge into the previous one
MAX_CHUNK_CHARS = 2000       # ~500 tokens
MIN_TAIL_CHARS = 400
SPLIT_BLOCK_CHARS = 3000


def chapter_files(corpus_dir):
    files = sorted(Path(corpus_dir).glob(CHAPTER_GLOB))
    if not files:
        raise FileNotFoundError(f"no {CHAPTER_GLOB} files in {corpus_dir}")
    return files


def heading_level(text):
    """1 = chapter title, 2 = section (bold), 3 = subsection (bold-italic or italic).
    Plain-text headings are body text the converter mislabelled, so they return None."""
    if "<mark>" in text:
        return 1
    if text.startswith(("**_", "_**", "***")):
        return 3
    if text.startswith("**"):
        return 2
    if text.startswith("_") and text.endswith("_"):
        return 3
    return None


def clean_title(text):
    text = strip_tags(text).replace("**", " ").replace("_", " ")
    return re.sub(r"\s+", " ", text).strip(" :")


def _blocks(lines):
    """Group (page_label, pdf_page, line) entries into paragraph, table and list blocks."""
    blocks, current, kind = [], [], None
    for entry in lines + [(None, None, "")]:
        line = entry[2]
        if not line.strip():
            if current:
                blocks.append((kind, current))
                current, kind = [], None
            continue
        line_kind = "table" if line.lstrip().startswith("|") else "list" if LIST_ITEM.match(line) else "para"
        if current and line_kind != kind and not (kind == "list" and line_kind == "para"):
            blocks.append((kind, current))
            current = []
        kind = line_kind if not current else kind
        current.append(entry)
    # Consecutive list blocks (separated by blank lines) belong together.
    merged = []
    for kind, entries in blocks:
        if merged and kind == "list" and merged[-1][0] == "list":
            merged[-1][1].extend(entries)
        else:
            merged.append((kind, list(entries)))
    return merged


def _block_text(entries):
    return "\n".join(e[2] for e in entries)


def _split_long(entries):
    """Split an over-long paragraph block into sentence-bounded pieces."""
    text = _block_text(entries)
    page = entries[0][:2]
    pieces, current = [], ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if current and len(current) + len(sentence) > MAX_CHUNK_CHARS:
            pieces.append([(*page, current.strip())])
            current = ""
        current += sentence + " "
    if current.strip():
        pieces.append([(*page, current.strip())])
    return pieces


def chunk_section(lines):
    """Pack blocks into chunks of up to MAX_CHUNK_CHARS; tables and lists stay whole."""
    units = []
    for kind, entries in _blocks(lines):
        if kind == "para" and len(_block_text(entries)) > SPLIT_BLOCK_CHARS:
            units.extend(_split_long(entries))
        else:
            units.append(entries)
    chunks, current = [], []
    for unit in units:
        size = sum(len(e[2]) for e in current)
        if current and size + len(_block_text(unit)) > MAX_CHUNK_CHARS:
            chunks.append(current)
            current = []
        current = current + unit
    if current:
        if chunks and sum(len(e[2]) for e in current) < MIN_TAIL_CHARS:
            chunks[-1] = chunks[-1] + current
        else:
            chunks.append(current)
    return [{
        "text": "\n\n".join(_block_text([e]) for e in c) if False else _join(c),
        "page_label": c[0][0], "pdf_page": c[0][1],
        "pages": sorted({e[0] for e in c}),
    } for c in chunks]


def _join(entries):
    """Rebuild chunk text, keeping blank lines between blocks."""
    out, prev_kind = [], None
    for kind, block in _blocks(entries):
        out.append(_block_text(block))
    return strip_tags("\n\n".join(out)).strip()


def parse_chapter(path):
    """Return (document, sections) for one chapter file. Sections carry their lines."""
    doc_id = Path(path).stem
    page_label, pdf_page = None, None
    chapter_num, chapter_title = None, None
    pages_with_text = set()
    raw_sections = []
    current = {"title": "Introduction", "level": 2, "lines": []}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        marker = PAGE_MARKER.match(stripped)
        if marker:
            page_label, pdf_page = marker.group(1), int(marker.group(2))
            continue
        if PAGE_FOOTER.match(stripped):
            continue
        heading = HEADING.match(stripped)
        level = heading_level(heading.group(1)) if heading else None
        if level == 1:
            title = clean_title(heading.group(1))
            m = re.match(r"Chapter\s+(\d+)\s*(.*)", title)
            if m:
                chapter_num, chapter_title = int(m.group(1)), m.group(2).strip()
            continue
        if level in (2, 3):
            raw_sections.append(current)
            current = {"title": clean_title(heading.group(1)), "level": level, "lines": []}
            continue
        text = stripped[stripped.find(" ") + 1:] if heading else line.rstrip()
        if text.strip():
            pages_with_text.add(page_label)
        current["lines"].append((page_label, pdf_page, text))
    raw_sections.append(current)

    expected_num = int(doc_id[2:4])
    if chapter_num != expected_num:
        raise ValueError(f"{doc_id}: H1 chapter number {chapter_num} does not match file name")

    # Merge tiny sections into the previous one, unless they introduce subsections.
    sections = []
    for i, s in enumerate(raw_sections):
        size = sum(len(t.strip()) for _, _, t in s["lines"])
        has_children = s["level"] == 2 and i + 1 < len(raw_sections) and raw_sections[i + 1]["level"] == 3
        if size == 0:
            if has_children:
                s["empty_parent"] = True
                sections.append(s)
            continue
        if size < MIN_SECTION_CHARS and sections and not has_children:
            prev = sections[-1]
            if not prev.get("empty_parent"):
                page = s["lines"][0][:2]
                prev["lines"] += [(*page, ""), (*page, f"**{s['title']}**"), (*page, "")] + s["lines"]
                continue
        sections.append(s)

    out, parent = [], None
    for s in sections:
        if s["level"] == 2:
            parent = s
        s["parent"] = parent if s["level"] == 3 else None
        if s.get("empty_parent"):
            continue
        out.append(s)

    records = []
    for n, s in enumerate(out):
        section_id = f"ch{expected_num:02d}.s{n:03d}"
        s["section_id"] = section_id
        path_titles = [chapter_title] + ([s["parent"]["title"]] if s["parent"] else []) + [s["title"]]
        lines = [l for l in s["lines"] if l[0] is not None]
        chunks = chunk_section(lines)
        body = "\n\n".join(c["text"] for c in chunks)
        refs = sorted({int(m) for m in CROSS_REF.findall(body)} - {expected_num})
        records.append({
            "section_id": section_id, "doc_id": doc_id, "chapter": expected_num,
            "title": s["title"], "path": path_titles,
            "parent_id": s["parent"].get("section_id") if s["parent"] else None,
            "level": 3 if s["parent"] else 2, "heading_source": "markdown",
            "page_start_label": chunks[0]["page_label"] if chunks else None,
            "page_end_label": chunks[-1]["pages"][-1] if chunks else None,
            "pdf_pages": [lines[0][1], lines[-1][1]] if lines else [None, None],
            "text_chars": len(body), "cross_refs": refs,
            "_text": body, "_chunks": chunks,
        })
    document = {"doc_id": doc_id, "chapter": expected_num, "title": chapter_title,
                "_pages_with_text": pages_with_text}
    return document, [r for r in records if r["_chunks"]]
