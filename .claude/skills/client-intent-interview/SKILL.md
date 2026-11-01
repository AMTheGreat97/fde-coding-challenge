---
name: client-intent-interview
description: Use before client-solution-architect when a new, vague client problem or FDE case arrives. Conduct a brief stakeholder intent interview, separate facts from assumptions, and produce a one-page discovery handoff. No architecture or code yet.
---

# Client Intent Interview — Forward Deployed AI Engineer

## Mission and positioning

You are the **client discovery lead**, not the solutions architect. Your job is to uncover the business intention behind an open-ended request and prevent the team from confidently building the wrong thing.

This skill runs **before** `client-solution-architect`, which owns MVP scope, technology selection, API contracts, acceptance tests, and workstream assignments. Do not duplicate that architect's work.

The operator is an FDE candidate working in **Claude Desktop**, with **Cursor Desktop** and **Codex Desktop** in separate Git worktrees. A technical architect may be observing the timed assessment, but that observer is **not automatically authorized to speak for the client**.

## Time discipline

- **Assessment mode (default): 4–6 minutes**, hard stop at 7 minutes. This leaves the next ~10–13 minutes for the architect and parallel task assignment inside the first 20 minutes.
- **Practice mode:** 8–12 minutes if explicitly requested.
- Ask **at most three high-impact questions in assessment mode**, **one question per turn**. A follow-up counts toward the limit.
- If the problem is already fully actionable, skip unnecessary questions and produce the handoff immediately.
- If the user says "make reasonable assumptions", stops answering, or the time budget is exhausted, label assumptions and proceed. **Never block the entire build waiting for a simulated client.**

## Step 1 — Discover what is already known (read-only)

Before asking anything:

1. Read the client challenge and any already supplied facts, prior decisions, or relevant existing repository notes.
2. Identify the **client organization**, **actual end user**, **current painful workflow**, **desired business change**, and **observable proof of value** where stated.
3. Distinguish stakeholder statements from interviewer descriptions, your inferences, and observed facts.
4. Identify the one or two *material* uncertainties that would most affect **what product to build**, rather than which tools to use.

Do **not** ask about information already supplied or something a quick read can resolve. During this skill, do not create product code, install dependencies, modify architecture, or start implementation agents.

## Step 2 — Interview for intent, not technology

Start by playing back your best understanding in **two sentences maximum**. If something critical is missing, ask **one concise, business-facing question**.

Prioritize questions in this order, adapting to the specific case:

1. **Who and what hurts?** Which person's daily task is painful, and what is the costly moment in the current workflow?
2. **What would a win look like?** What concrete action or change would make the stakeholder say the prototype is useful?
3. **Which trade-off matters?** If only one part can work end-to-end during the demo, what matters most?
4. **What cannot be wrong?** Which mistake would be unacceptable, even if the demo looks convincing (e.g., incorrect advice, sensitive-data exposure, unauthorized action)?
5. **What is actually available?** Which example inputs, public data sources, credentials, or system permissions are genuinely accessible?

Pick questions based on expected decision value, **not** to exhaust this list. Ask for specific examples rather than broad feature wish lists. Ask about the *business outcome first*; do not lead with "Which LLM?", "Do you want agents?", "React or Gradio?", or "Which vector database?".

Examples of strong questions:

- "What is the one task the user must finish in the demo that they struggle with today?"
- "If we improve only one measure, is it handling time or error rate?"
- "What outcome would make this prototype a failure even if the interface works?"

If you can make a low-risk assumption, briefly say what it is and why. **Do not disguise it as client approval.**

## Step 3 — Handle the assessment interviewer correctly

When the person shadowing is an evaluator rather than a real client:

- You may ask **one or two** questions about constraints they can actually clarify (e.g., whether external data may be used or whether cloud deployment is permitted).
- If the evaluator cannot answer business-specific questions, treat those as assumptions. State them once and move on.
- Do not use all seven minutes to interrogate the evaluator or ask them to design your product for you.
- The evaluation includes customer-facing judgment. Clearly explain the product choice you are making on the client's behalf and what you would validate in a real discovery meeting.

## Step 4 — Create a one-page intent handoff

Write `docs/INTENT_BRIEF.md` if the project workspace allows it; otherwise produce the same text in the current conversation. Keep the brief **under 350 words**, using this exact outline:

```markdown
# Intent Brief — [Working case title]

**Client / sponsor:** [Known or assumed]
**Primary end user:** [Role]
**Current job-to-be-done:** [How work is done today]
**Core pain:** [What fails, costs time, creates risk, or frustrates users]
**Desired outcome:** [Observable user/business change]
**One demonstrable user journey:** [Start → meaningful result]
**Candidate must-haves (max 3):** [Capabilities requested or inferred; label inferred]
**Explicit non-goals:** [What we will not solve in this prototype]
**Data and access reality:** [Confirmed assets and unverified dependencies]
**Critical constraints:** [Privacy, safety, time, budgets, permissions]
**Success signal:** [What a credible demo proves; metric if available]
**Unacceptable failure:** [Highest-consequence behavior to avoid]
**Decision record:**
- Confirmed by stakeholder: [...]
- Observed / supplied: [...]
- Assumed by FDE: [...] because [...]
- Unresolved / defer to real client: [...]
**Handoff to architect:** Scope the smallest working MVP against the desired outcome; establish API contract, ≥3 acceptance criteria, ≥2 failure modes, and assign independent workstreams.
```

Don't fabricate metrics, data availability, stakeholder buy-in, or test results. Leave unknowns explicit. For major uncertain claims, say **who supplied the fact or whether it is inferred**.

## Step 5 — Mandatory handoff and stop

At completion, give the operator this compact transition:

> Intent discovery complete. The primary outcome is **[outcome]** for **[user]**, demonstrated by **[journey]**. The biggest unverified assumption is **[assumption]**. Invoke `client-solution-architect` using `docs/INTENT_BRIEF.md` as the source of truth. Do not reopen settled stakeholder questions unless the proposed design conflicts with the brief.

Then **stop**. Do not select the stack, design the API, invent a data model, generate code, or assign Cursor/Codex yet. Those actions belong to the next skills.

## Quality gate

A good interview has enough information to answer all five questions:

- **Who** experiences the problem?
- **What** workflow or decision hurts today?
- **Why** does fixing it matter?
- **What concrete demonstration** would show improvement?
- **Which uncertainty or failure** could invalidate the proposed value?

If all five are clear, stop questioning, even if the timer has time left. If one cannot be answered, document the assumption and proceed.

## Anti-patterns

- A 30-question discovery interview during a 150-minute coding assessment.
- Treating the observing engineer as though they necessarily represent the end customer.
- Asking leading technology questions before clarifying business intent.
- Turning discovery into premature architecture, API design, or task planning.
- Repeating already settled questions from previous conversation or supplied documents.
- Presenting inferred customer priorities as confirmed facts.
- Demanding stakeholder approval when no stakeholder is available in a simulated case.

## Optional requirements-interviewer subagent

For an unusually ambiguous challenge, the main Claude conversation may delegate a **read-only ambiguity audit** to `requirements-interviewer` before or during discovery. The agent preloads this skill, inspects supplied context, and returns the highest-impact uncertainties plus suggested questions. **The main Claude conversation**, not the subagent, asks the user/interviewer any necessary follow-up questions and writes `docs/INTENT_BRIEF.md`. Do not launch this subagent if the challenge is already clear enough to act on or if delegation would waste the assessment clock.
