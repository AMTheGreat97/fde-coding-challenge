"""Handbook assistant UI. Calls rag.ask when importable; MOCK=1 uses fixtures."""
from __future__ import annotations

import html
import json
import os
import re
import time
from pathlib import Path

import gradio as gr

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "specs" / "fixtures"
MAX_QUESTION = 2000
USE_MOCK = os.environ.get("MOCK") == "1"

try:
    from rag import ask as rag_ask  # type: ignore
except Exception:
    rag_ask = None


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _status(kind: str, message: str) -> str:
    palette = {
        "idle": ("#eef2ff", "#312e81", "Idle"),
        "loading": ("#fff7ed", "#9a3412", "Loading"),
        "success": ("#ecfdf5", "#065f46", "Success"),
        "error": ("#fef2f2", "#991b1b", "Error"),
        "insufficient": ("#fffbeb", "#92400e", "Insufficient evidence"),
    }
    bg, fg, label = palette.get(kind, palette["idle"])
    return (
        f'<div role="status" style="padding:10px 14px;border-radius:8px;'
        f'background:{bg};color:{fg};font-weight:600">{esc(label)} — {esc(message)}</div>'
    )


def _error_payload(code: str, message: str, mode: str) -> dict:
    return {
        "answer_markdown": "",
        "citations": [],
        "intent": None,
        "sub_questions": [],
        "coverage": None,
        "insufficient_evidence": False,
        "mode": mode,
        "latency_ms": 0,
        "error": {"code": code, "message": message},
    }


def load_fixture(mode: str) -> dict:
    name = "answer_verify.json" if mode == "verify" else "answer_fast.json"
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    payload.pop("_mock", None)
    return payload


def call_ask(question: str, history: list[dict] | None, mode: str) -> dict:
    text = (question or "").strip()
    if not text:
        return _error_payload("empty_question", "Enter a question to search the handbook.", mode)
    if len(text) > MAX_QUESTION:
        return _error_payload(
            "question_too_long",
            f"Questions must be {MAX_QUESTION} characters or fewer.",
            mode,
        )
    if USE_MOCK:
        time.sleep(0.15)
        return load_fixture(mode)
    if rag_ask is None:
        return _error_payload(
            "index_missing",
            "rag.ask is not available. Launch with MOCK=1 until the backend lands.",
            mode,
        )
    return rag_ask(text, history, mode)


def render_answer(payload: dict) -> str:
    error = payload.get("error")
    if error:
        return _status("error", error.get("message") or error.get("code") or "Request failed")
    if payload.get("insufficient_evidence"):
        banner = _status(
            "insufficient",
            "The retrieved handbook passages do not support an answer. Nothing was invented.",
        )
    else:
        banner = _status("success", f"{payload.get('mode', 'fast')} answer in {payload.get('latency_ms', 0)} ms")
    raw = esc(payload.get("answer_markdown") or "")
    marked = re.sub(r"\[(\d+)\]", r"<mark>[\1]</mark>", raw)
    return (
        f"{banner}"
        f'<div style="margin-top:10px;padding:14px;border:1px solid #d1d5db;border-radius:8px;'
        f'line-height:1.55">{marked}</div>'
    )


def render_citations(payload: dict) -> str:
    rows = payload.get("citations") or []
    if payload.get("error") or not rows:
        return '<div style="color:#6b7280">No citations.</div>'
    items = []
    for cite in rows:
        items.append(
            "<tr>"
            f"<td>[{esc(cite.get('n'))}]</td>"
            f"<td>{esc(cite.get('section_path'))}</td>"
            f"<td>{esc(cite.get('page_label'))}</td>"
            f"<td>{esc(cite.get('relevance'))}</td>"
            f"<td>{esc(cite.get('snippet'))}</td>"
            "</tr>"
        )
    return (
        "<div><b>Citations</b></div>"
        "<table style='width:100%;border-collapse:collapse;margin-top:6px'>"
        "<thead><tr><th>n</th><th>Section path</th><th>Page</th><th>Relevance</th><th>Snippet</th></tr></thead>"
        f"<tbody>{''.join(items)}</tbody></table>"
    )


def render_subquestions(payload: dict) -> str:
    rows = payload.get("sub_questions") or []
    if payload.get("error") or not rows:
        return '<div style="color:#6b7280">No sub-questions.</div>'
    items = []
    for row in rows:
        refs = ", ".join(f"[{n}]" for n in row.get("citation_ns") or [])
        items.append(f"<li>{esc(row.get('question'))} <span style='color:#6b7280'>{esc(refs)}</span></li>")
    return f"<div><b>Sub-questions</b></div><ol>{''.join(items)}</ol>"


def render_coverage(payload: dict, mode: str) -> str:
    if mode != "verify":
        return '<div style="color:#6b7280">Coverage is shown in Verify mode.</div>'
    coverage = payload.get("coverage")
    if payload.get("error") or not coverage:
        return '<div style="color:#6b7280">No coverage report.</div>'
    complete = "Complete" if coverage.get("complete") else "Incomplete — relevant sections were missed"
    cited = ", ".join(str(c) for c in coverage.get("chapters_cited") or []) or "—"
    relevant = ", ".join(str(c) for c in coverage.get("chapters_relevant") or []) or "—"
    missed = coverage.get("missed_sections") or []
    miss_rows = "".join(
        "<tr>"
        f"<td>{esc(item.get('section_path'))}</td>"
        f"<td>{esc(item.get('page_label'))}</td>"
        f"<td>{esc(item.get('reason'))}</td>"
        "</tr>"
        for item in missed
    ) or "<tr><td colspan='3'>None</td></tr>"
    return (
        f"<div><b>Coverage</b> — {esc(complete)}</div>"
        f"<div style='margin:8px 0'>Chapters cited: {esc(cited)} · Chapters relevant: {esc(relevant)}</div>"
        "<table style='width:100%;border-collapse:collapse'>"
        "<thead><tr><th>Missed section</th><th>Page</th><th>Why</th></tr></thead>"
        f"<tbody>{miss_rows}</tbody></table>"
    )


def _mode_value(mode: str | None) -> str:
    return "verify" if (mode or "").lower().startswith("verify") else "fast"


def ask_ui(question: str, mode: str, history: list[dict] | None):
    mode = _mode_value(mode)
    history = history or []
    payload = call_ask(question, history, mode)
    error = payload.get("error")
    if error:
        reply = f"Error ({error.get('code')}): {error.get('message')}"
        state = _status("error", error.get("message") or "Request failed")
    elif payload.get("insufficient_evidence"):
        reply = payload.get("answer_markdown") or "Insufficient evidence in the retrieved passages."
        state = _status("insufficient", "The handbook passages do not support an answer.")
    else:
        reply = payload.get("answer_markdown") or ""
        state = _status("success", f"{mode} answer in {payload.get('latency_ms', 0)} ms")
    chat = history + [
        {"role": "user", "content": question or ""},
        {"role": "assistant", "content": reply},
    ]
    return (
        chat,
        state,
        render_answer(payload),
        render_citations(payload),
        render_subquestions(payload),
        render_coverage(payload, mode),
        "",
    )


def build_ui() -> gr.Blocks:
    idle = _status("idle", "Ask a nested handbook question. Fast cites retrieved sections; Verify adds a coverage sweep.")
    with gr.Blocks(title="Aviation Maintenance Handbook Assistant") as demo:
        gr.Markdown("# Aviation Maintenance Handbook Assistant")
        gr.Markdown(
            "Answers come from the FAA Aviation Maintenance Technician General Handbook chapter bodies. "
            "Citations use handbook page labels. No API keys or index files are loaded in this UI."
        )
        status = gr.HTML(idle, elem_id="status-banner")
        mode = gr.Radio(["Fast", "Verify"], value="Fast", label="Mode", elem_id="mode-toggle")
        chat = gr.Chatbot(label="Conversation", height=280, elem_id="chat")
        question = gr.Textbox(
            label="Question",
            placeholder="How is aluminum corrosion identified, treated, and handled on fluid lines?",
            lines=2,
            elem_id="question",
        )
        ask_btn = gr.Button("Ask", variant="primary", elem_id="ask")
        answer = gr.HTML(elem_id="answer-panel")
        with gr.Row():
            citations = gr.HTML("<div style='color:#6b7280'>Citations appear after an answer.</div>", elem_id="citations-panel")
            subqs = gr.HTML("<div style='color:#6b7280'>Sub-questions appear after an answer.</div>", elem_id="subquestions-panel")
        coverage = gr.HTML("<div style='color:#6b7280'>Coverage is shown in Verify mode.</div>", elem_id="coverage-panel")

        def on_start(_question, _mode, _history):
            return _status("loading", "Searching the handbook…")

        ask_btn.click(on_start, [question, mode, chat], [status]).then(
            ask_ui, [question, mode, chat], [chat, status, answer, citations, subqs, coverage, question]
        )
        question.submit(on_start, [question, mode, chat], [status]).then(
            ask_ui, [question, mode, chat], [chat, status, answer, citations, subqs, coverage, question]
        )
    return demo


def main() -> None:
    build_ui().launch(server_name="127.0.0.1", server_port=7860, share=False)


if __name__ == "__main__":
    main()
