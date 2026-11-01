---
name: python-ai-backend
description: For Claude Desktop implementing a rapidly deployable Python AI backend with Portkey, typed contracts and testable behavior; use after architecture and API approval.
---
# Python AI backend builder (Claude)

Use for backend-owned paths only. Prioritize one working request in the first increment.

1. Inspect existing code and dependencies. Follow `AGENTS.md` and the accepted API contract; do not redesign UI or break frontend mocks.
2. Use Python, typed Pydantic inputs/outputs, and an Portkey-compatible SDK or supported integration. Keep model ID configurable; support timeout and model/API failures.
3. Use direct LLM calls for simple tasks. Introduce Pydantic AI only when structured tool use/agent behavior is required; LangGraph only when the workflow truly needs persistent or conditional steps.
4. Separate domain logic from transport (FastAPI only when the API boundary is useful). For Gradio, allow a Python-first implementation with a stable callable and optional FastAPI mount.
5. Never hardcode API credentials. Use `PORTKEY_API_KEY` and configured model identifiers. Keep network calls behind small testable functions; use dependency mocks in unit tests **only**, never in the live demo.
6. Implement `/health` if there is an HTTP service, a real inference path, structured error responses, bounded request size, log-friendly trace ID, and at least one functional test.
7. Run actual tests and report successes/failures, known limitations and integration instructions. Do not touch `ui/`, `evals/`, or `deploy/` except with lead approval.

Stop expanding features if the end-to-end app is not yet working. Output: committed backend increment, stable interface and concise verification evidence.
