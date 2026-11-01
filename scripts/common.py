"""Shared helpers: .env loading, OpenRouter calls, and Markdown chunking."""
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

OPENROUTER_URL = "https://openrouter.ai/api/v1"
ROOT = Path(__file__).resolve().parent.parent
CHROMA_DIR = ROOT / "chroma_db"


def load_env(path=ROOT / ".env"):
    """Load KEY=VALUE lines from .env into os.environ (existing vars win)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def openrouter(path, body=None):
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        raise SystemExit("OPENROUTER_API_KEY is empty. Put your key in .env and re-run.")
    request = urllib.request.Request(
        f"{OPENROUTER_URL}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST" if body is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"OpenRouter {path} failed: HTTP {e.code} {e.read().decode(errors='replace')[:500]}")


def embed(texts, model=None):
    model = model or os.environ.get("EMBEDDING_MODEL", "openai/text-embedding-3-small")
    result = openrouter("/embeddings", {"model": model, "input": texts})
    data = sorted(result["data"], key=lambda d: d["index"])
    return [d["embedding"] for d in data], result


PAGE_MARKER = re.compile(r"<!-- page (\S+) \(pdf p\.(\d+)\) -->")


def chunk_markdown(text, max_chars=2000):
    """Split corpus Markdown into chunks of whole paragraphs, tagged with their page."""
    chunks = []
    pieces = PAGE_MARKER.split(text)
    # split() yields [preamble, label, pdf_page, body, label, pdf_page, body, ...]
    for label, pdf_page, body in zip(pieces[1::3], pieces[2::3], pieces[3::3]):
        current = ""
        for para in re.split(r"\n\s*\n", body.strip()):
            if current and len(current) + len(para) > max_chars:
                chunks.append({"text": current.strip(), "page_label": label, "pdf_page": int(pdf_page)})
                current = ""
            current += para + "\n\n"
        if current.strip():
            chunks.append({"text": current.strip(), "page_label": label, "pdf_page": int(pdf_page)})
    return chunks
