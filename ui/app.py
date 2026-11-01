"""Handbook assistant UI. Calls rag.ask when importable; MOCK=1 uses fixtures.

Shows a live trace of every pipeline step (tool, model, timing, cost), and source
cards that link each [n] citation to its passage, its retrieval provenance and the
handbook PDF page (contract v1.1, docs/decisions/CHANGE_REQUEST.md).

Run: python -m ui.app            (local, http://127.0.0.1:7860)
     GRADIO_SHARE=1 PORT=7861 python -m ui.app   (adds a public share link)
"""
from __future__ import annotations

import html
import json
import os
import queue
import re
import threading
import time
from pathlib import Path
from urllib.parse import quote

import gradio as gr

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "specs" / "fixtures"
PDF_DIR = ROOT / "DATA" / "chapters"
MAX_QUESTION = 2000
USE_MOCK = os.environ.get("MOCK") == "1"

try:
    from rag import ask as rag_ask  # the contract-B function
except Exception:
    rag_ask = None

CSS = """
.src-card {border:1px solid var(--border-color-primary);border-radius:8px;padding:10px 12px;margin:8px 0}
.src-card:target {outline:2px solid #f97316}
.src-head {display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
.src-n {font-weight:700}
.badge {display:inline-block;padding:1px 7px;border-radius:999px;font-size:12px;background:var(--background-fill-secondary)}
.rel-3 {background:#dcfce7;color:#14532d}.rel-2 {background:#fef9c3;color:#713f12}
.src-meta {font-size:12px;color:var(--body-text-color-subdued);margin-top:4px}
.src-card pre {white-space:pre-wrap;font-size:12px;max-height:260px;overflow:auto}
.trace td, .trace th {font-size:12px;padding:3px 6px;text-align:left;vertical-align:top}
.trace .err {color:#b91c1c}.trace .skip {color:#6b7280}
"""


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _status(kind: str, message: str) -> str:
    palette = {
        "idle": ("#eef2ff", "#312e81", "Idle"),
        "loading": ("#fff7ed", "#9a3412", "Working"),
        "success": ("#ecfdf5", "#065f46", "Success"),
        "error": ("#fef2f2", "#991b1b", "Error"),
        "insufficient": ("#fffbeb", "#92400e", "Insufficient evidence"),
    }
    bg, fg, label = palette.get(kind, palette["idle"])
    return (f'<div role="status" style="padding:10px 14px;border-radius:8px;background:{bg};'
            f'color:{fg};font-weight:600">{esc(label)} — {esc(message)}</div>')


def _error_payload(code: str, message: str, mode: str) -> dict:
    return {"answer_markdown": "", "citations": [], "intent": None, "sub_questions": [], "coverage": None,
            "insufficient_evidence": False, "mode": mode, "latency_ms": 0,
            "error": {"code": code, "message": message}, "trace": [], "request_id": "", "cost_usd": 0.0}


def load_fixture(mode: str) -> dict:
    name = "answer_verify.json" if mode == "verify" else "answer_fast.json"
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    payload.pop("_mock", None)
    return payload


def call_ask(question: str, history: list[dict] | None, mode: str, on_step=None) -> dict:
    text = (question or "").strip()
    if not text:
        return _error_payload("empty_question", "Enter a question to search the handbook.", mode)
    if len(text) > MAX_QUESTION:
        return _error_payload("question_too_long", f"Questions must be {MAX_QUESTION} characters or fewer.", mode)
    if USE_MOCK:
        time.sleep(0.15)
        return load_fixture(mode)
    if rag_ask is None:
        return _error_payload("index_missing", "rag.ask is not available. Launch with MOCK=1 until the backend lands.", mode)
    return rag_ask(text, history, mode, on_step=on_step)


# ---------- source links ----------

def pdf_url(source: dict | None) -> str | None:
    """Display link to the chapter PDF page (served by Gradio from DATA/chapters only)."""
    if not source or not source.get("pdf_file"):
        return None
    path = Path(source["pdf_file"])
    if path.parent.as_posix() != "DATA/chapters":
        return None
    return f"/gradio_api/file={quote(path.as_posix())}#page={int(source.get('pdf_file_page') or 1)}"


def link_citations(markdown: str) -> str:
    """Turn [n] markers into links that jump to the matching source card."""
    return re.sub(r"\[(\d+)\](?!\()", r"[[\1]](#src-\1)", markdown or "")


# ---------- renderers ----------

def render_trace(steps: list[dict], payload: dict | None) -> str:
    if not steps:
        return '<div style="color:#6b7280">The pipeline trace appears here while a question runs.</div>'
    rows = []
    for s in steps:
        cls = {"error": "err", "skipped": "skip"}.get(s.get("status"), "")
        cost = f"${s['cost_usd']:.4f}" if s.get("cost_usd") else ""
        rows.append(f"<tr class='{cls}'><td>{esc(s.get('step'))}</td><td><code>{esc(s.get('tool'))}</code></td>"
                    f"<td>{esc(s.get('model') or '')}</td><td>{esc(s.get('ms'))} ms</td><td>{cost}</td>"
                    f"<td>{esc(s.get('detail'))}</td></tr>")
    head = ""
    if payload and payload.get("request_id"):
        head = (f"<div class='src-meta'>request <code>{esc(payload['request_id'])}</code> · "
                f"{esc(payload.get('latency_ms'))} ms · ${payload.get('cost_usd') or 0:.4f} · "
                f"logged to <code>logs/queries.jsonl</code></div>")
    return (f"<div><b>Pipeline trace</b> ({len(steps)} steps)</div>{head}<table class='trace'>"
            "<thead><tr><th>Step</th><th>Tool</th><th>Model</th><th>Time</th><th>Cost</th><th>Result</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>")


def _ranks(r: dict) -> str:
    parts = [f"{label} #{r[key]}" for key, label in
             (("dense_rank", "dense"), ("section_rank", "section"), ("bm25_rank", "BM25")) if r.get(key)]
    if r.get("rrf_score") is not None:
        parts.append(f"RRF {r['rrf_score']}")
    return " · ".join(parts) or "—"


def render_sources(payload: dict) -> str:
    rows = payload.get("citations") or []
    if payload.get("error") and not rows:
        return '<div style="color:#6b7280">No sources.</div>'
    if not rows:
        return '<div style="color:#6b7280">No sources cited.</div>'
    cards = []
    for c in rows:
        n, rel = c.get("n"), c.get("relevance")
        url = pdf_url(c.get("source"))
        link = (f"<a href='{esc(url)}' target='_blank' rel='noopener'>Open PDF p. {esc(c.get('page_label'))} ↗</a>"
                if url else f"p. {esc(c.get('page_label'))}")
        r = c.get("retrieval") or {}
        passage = c.get("passage") or c.get("snippet") or ""
        cards.append(
            f"<div class='src-card' id='src-{esc(n)}'>"
            f"<div class='src-head'><span class='src-n'>[{esc(n)}]</span><span>{esc(c.get('section_path'))}</span>"
            f"<span class='badge rel-{esc(rel)}'>relevance {esc(rel)}/3</span>{link}</div>"
            f"<div class='src-meta'>Ch {esc(c.get('chapter'))} · section <code>{esc(c.get('section_id'))}</code>"
            f" · chunk <code>{esc(c.get('chunk_id') or '')}</code> · handbook PDF p. {esc(c.get('pdf_page') or '')}</div>"
            + (f"<div class='src-meta'>Found for: <i>{esc(r.get('sub_question'))}</i></div>"
               f"<div class='src-meta'>Retrieval: {esc(_ranks(r))}</div>"
               f"<div class='src-meta'>Why relevant: {esc(r.get('relevance_reason'))}</div>" if r else "")
            + f"<details><summary>Passage sent to the answer model</summary><pre>{esc(passage)}</pre></details>"
            "</div>")
    return f"<div><b>Sources</b> ({len(rows)})</div>{''.join(cards)}"


def render_subquestions(payload: dict) -> str:
    rows = payload.get("sub_questions") or []
    if payload.get("error") and not rows or not rows:
        return '<div style="color:#6b7280">No sub-questions.</div>'
    items = []
    for row in rows:
        refs = " ".join(f"<a href='#src-{esc(n)}'>[{esc(n)}]</a>" for n in row.get("citation_ns") or []) or "—"
        items.append(f"<li>{esc(row.get('question'))} <span style='color:#6b7280'>{refs}</span></li>")
    intent = payload.get("intent") or {}
    head = ""
    if intent:
        head = (f"<div class='src-meta'>Intent: <b>{esc(intent.get('primary'))}</b> · topics: "
                f"{esc(', '.join(intent.get('topics') or []) or '—')}</div>")
    return f"<div><b>Sub-questions</b></div>{head}<ol>{''.join(items)}</ol>"


def render_coverage(payload: dict, mode: str) -> str:
    if mode != "verify":
        return '<div style="color:#6b7280">Switch to Verify to sweep the whole corpus for missed sections.</div>'
    coverage = payload.get("coverage")
    if not coverage:
        return '<div style="color:#6b7280">No coverage report.</div>'
    complete = "Complete" if coverage.get("complete") else "Incomplete — relevant sections were missed"
    cited = ", ".join(str(c) for c in coverage.get("chapters_cited") or []) or "—"
    relevant = ", ".join(str(c) for c in coverage.get("chapters_relevant") or []) or "—"
    rows = []
    for m in coverage.get("missed_sections") or []:
        url = pdf_url(m.get("source"))
        page = (f"<a href='{esc(url)}' target='_blank' rel='noopener'>p. {esc(m.get('page_label'))} ↗</a>"
                if url else esc(m.get("page_label")))
        rows.append(f"<tr><td>{esc(m.get('section_path'))}</td><td>{page}</td><td>{esc(m.get('reason'))}</td></tr>")
    body = "".join(rows) or "<tr><td colspan='3'>None</td></tr>"
    return (f"<div><b>Coverage</b> — {esc(complete)}</div>"
            f"<div style='margin:8px 0'>Chapters cited: {esc(cited)} · Chapters relevant: {esc(relevant)}</div>"
            "<table class='trace'><thead><tr><th>Missed section</th><th>Page</th><th>Why</th></tr></thead>"
            f"<tbody>{body}</tbody></table>")


# ---------- event handler ----------

def _mode_value(mode: str | None) -> str:
    return "verify" if (mode or "").lower().startswith("verify") else "fast"


def ask_ui(question: str, mode: str, history: list[dict] | None):
    mode = _mode_value(mode)
    history = history or []
    events: queue.Queue = queue.Queue()
    holder: dict = {}

    def run():
        try:
            holder["payload"] = call_ask(question, history, mode, on_step=events.put)
        except Exception as e:  # rag.ask never raises; this guards the mock path
            holder["payload"] = _error_payload("provider_unavailable", str(e), mode)
        events.put(None)

    threading.Thread(target=run, daemon=True).start()
    steps: list[dict] = []
    pending = history + [{"role": "user", "content": question or ""},
                         {"role": "assistant", "content": "_Searching the handbook…_"}]
    loading = _status("loading", f"Running {mode} mode…")
    yield pending, loading, render_trace(steps, None), gr.skip(), gr.skip(), gr.skip(), ""
    while True:
        item = events.get()
        if item is None:
            break
        steps.append(item)
        yield gr.skip(), _status("loading", f"{item.get('step')} · {item.get('tool')}"), render_trace(steps, None), \
            gr.skip(), gr.skip(), gr.skip(), gr.skip()

    payload = holder["payload"]
    steps = payload.get("trace") or steps
    error = payload.get("error")
    if error:
        reply = f"**Error ({error.get('code')})**: {error.get('message')}"
        if payload.get("answer_markdown"):
            reply += "\n\n" + link_citations(payload["answer_markdown"])
        state = _status("error", error.get("message") or "Request failed")
    elif payload.get("insufficient_evidence"):
        reply = link_citations(payload.get("answer_markdown") or "Insufficient evidence in the retrieved passages.")
        state = _status("insufficient", "The handbook passages do not support an answer. Nothing was invented.")
    else:
        reply = link_citations(payload.get("answer_markdown") or "")
        state = _status("success", f"{mode} answer in {payload.get('latency_ms', 0)} ms · "
                                   f"{len(payload.get('citations') or [])} sources · ${payload.get('cost_usd') or 0:.4f}")
    chat = history + [{"role": "user", "content": question or ""}, {"role": "assistant", "content": reply}]
    yield (chat, state, render_trace(steps, payload), render_sources(payload),
           render_subquestions(payload), render_coverage(payload, mode), "")


def build_ui() -> gr.Blocks:
    idle = _status("idle", "Ask a nested handbook question. Fast cites retrieved sections; Verify adds a corpus-wide coverage sweep.")
    with gr.Blocks(title="Aviation Maintenance Handbook Assistant") as demo:
        gr.Markdown("# Aviation Maintenance Handbook Assistant")
        gr.Markdown("Answers come only from the FAA Aviation Maintenance Technician General Handbook chapters. "
                    "Click any [n] to jump to its source card; each card links to the handbook PDF page.")
        status = gr.HTML(idle, elem_id="status-banner")
        with gr.Row():
            with gr.Column(scale=5):
                mode = gr.Radio(["Fast", "Verify"], value="Fast", label="Mode", elem_id="mode-toggle")
                chat = gr.Chatbot(label="Conversation", height=460, elem_id="chat")
                question = gr.Textbox(label="Question", lines=1, max_lines=4, elem_id="question",
                                      placeholder="How is aluminum corrosion identified and treated, and how is hidden corrosion found?")
                ask_btn = gr.Button("Ask", variant="primary", elem_id="ask")
                subqs = gr.HTML("<div style='color:#6b7280'>Sub-questions appear after an answer.</div>", elem_id="subquestions-panel")
                coverage = gr.HTML("<div style='color:#6b7280'>Switch to Verify to sweep the whole corpus for missed sections.</div>", elem_id="coverage-panel")
            with gr.Column(scale=4):
                trace = gr.HTML(render_trace([], None), elem_id="trace-panel")
                sources = gr.HTML("<div style='color:#6b7280'>Source cards appear after an answer.</div>", elem_id="sources-panel")

        outputs = [chat, status, trace, sources, subqs, coverage, question]
        ask_btn.click(ask_ui, [question, mode, chat], outputs)
        question.submit(ask_ui, [question, mode, chat], outputs)
    return demo


def main() -> None:
    os.chdir(ROOT)  # PDF links are served relative to the repo root
    build_ui().queue().launch(
        server_name="127.0.0.1",
        server_port=int(os.environ.get("PORT", "7860")),
        share=os.environ.get("GRADIO_SHARE") == "1",
        allowed_paths=[str(PDF_DIR)],
        css=CSS,
    )


if __name__ == "__main__":
    main()
