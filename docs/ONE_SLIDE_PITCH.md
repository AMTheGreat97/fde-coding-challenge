# One-Slide Pitch — Maintenance Handbook Assistant

**Audience:** the business owner who runs maintenance operations (non-technical).
**Source of truth:** `specs/MASTER_SPEC.md`, `docs/INTENT_BRIEF.md`, `index/report.json`, and a live run of the working assistant on 2026-11-01.
**Editable slide:** `docs/ONE_SLIDE_PITCH.pptx` (one slide, 90-second talk track in the speaker notes).
**Case note:** the demo uses the public FAA Aviation Maintenance Technician General Handbook as a stand-in for the client's own documents.

---

## The slide

**Title:** Ask a maintenance question in plain English. Get a cited answer from every chapter that matters.

| The problem today | What we built | What you see |
|---|---|---|
| Technicians ask questions that touch several chapters. A single search finds one piece and misses the rest. | A chat assistant that has read all 14 handbook chapters (633 pages). | A plain-English answer, with each statement tagged to its chapter, section and page. |

**Live example (real output, not a mock):**
> *"How do I recognize corrosion on aluminum aircraft parts, how is it treated, and what must be recorded afterward?"*
> The assistant split this into three questions and answered all three. It cited Chapter 8 (corrosion signs and treatment, pages 8-17 to 8-22) and Chapter 2 (maintenance record entries, page 2-39). That is two chapters from one question, in about 18 seconds.

**Why it makes life easier**
- One question instead of hunting through chapters.
- Every answer shows where it came from, so a technician or inspector can check the page.
- If the handbook does not cover something, the assistant says so instead of guessing.

**Completeness check ("Verify"):** after the quick answer, a second pass sweeps every section of the handbook and lists anything relevant that the answer left out. *It is built but not yet reliable; see "Not yet proven".*

**What a pilot would prove (the success measures):**
1. Do answers include every relevant section? We measure this against a question set your own experts write.
2. Do technicians spend less time finding answers than they do today?
3. Do your experts trust the citations when they spot-check them?

**Not yet proven (said out loud, not hidden):**
- We have **no measured accuracy or recall number yet**. The test set that would produce one has not been run.
- The completeness check returned an error on every test question today. It needs a fix before it is shown as working.
- Answer time was about 15–25 seconds per question. Your acceptable wait time is still an open question.

---

## 90-second talk track

**(0:00)** "Your technicians already have the answers. They are in the handbooks. The problem is that real questions don't live in one place. Ask how to deal with corrosion on an aluminum part, and the answer is in one chapter, the paperwork rule is in another, and a search finds only one of them."

**(0:20)** "So we built an assistant that has read the whole handbook, all 14 chapters and 633 pages. A technician types the question the way they would say it out loud."

**(0:35)** *Show the corrosion question.* "Watch what it does. It breaks the question into three parts: how to spot it, how to treat it, and what to record. It answers each part, and every statement has a number that links to a chapter, a section and a page. Here it pulled from Chapter 8 for the corrosion work and Chapter 2 for the record-keeping rule. One question, two chapters."

**(1:00)** "Two things matter for trust. First, nothing is unsourced: if a technician or an inspector doubts an answer, the page is right there. Second, if the handbook doesn't cover it, the assistant says so rather than inventing a number."

**(1:15)** "What we are not claiming: we haven't measured accuracy yet, and the 'did it miss anything' check isn't ready. What we'd like to do is a short pilot on your real documents, with questions your own experts write, and measure whether it finds everything and saves your people time."

**(1:30)** "That's the ask: agree on ten to fifteen real questions, and we'll show you the results."

---

## Q&A prep (20-minute live session)

| Likely question | Honest answer |
|---|---|
| How accurate is it? | Not measured yet. The pilot measures it against questions your experts write. |
| Will it miss things? | Possibly. The completeness check is meant to catch that, but it is not working reliably yet. Citations let a person check any answer. |
| Can it use our own manuals, not just the FAA handbook? | The approach is designed for that. This build covers the FAA handbook only; your documents would be a pilot step. |
| What if it's wrong? | Every claim carries a page reference, and it declines when the text doesn't support an answer. A person still makes the maintenance decision. |
| How long does it take? | About 15–25 seconds per question in today's runs. |
| What does it cost to set up and run? | Reading the 14-chapter handbook into the system cost about $3.31 in AI usage. Per-question cost has not been measured. |
| Who can see our data? | This case uses a public handbook. Handling of your private documents would be agreed before any pilot. |

---

## Evidence behind this page

| Claim on the slide | Where it comes from |
|---|---|
| 14 chapters, 633 pages, all covered | `index/report.json` (documents 14, pages covered 633 of 633) |
| About $3.31 to read the handbook in | `index/report.json` (`llm_cost_usd` 3.3099) |
| Corrosion question: Ch 8 and Ch 2 cited, ~18 s | Live run of `rag.ask(mode="fast")`, 2026-11-01 |
| Completeness check errors | Live runs of `rag.ask(mode="verify")`, 3 of 3 returned `provider_unavailable` |
| No accuracy number | `evals/` does not exist yet; the recall run (acceptance criterion 5) has not been done |

## Before the live session
- Use a **real screenshot** of a fast-mode answer. `ui/screenshots/*.png` show the mock fixtures (the Verify one is partly cropped), so do not present them as real results.
- Run the corrosion question once beforehand so the demo is warm, and keep the local app as the fallback. There is no cloud URL to claim.
- Fix or hide the Verify toggle before the demo, or present it as "coming next".
