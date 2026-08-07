# Developer walkthrough — build pipeline

Produces two deliverables in [`docs/walkthrough/`](../../docs/walkthrough/):

| File | Shape |
|---|---|
| `AgentOps-Developer-Walkthrough.pdf` | 46 pages, A4 — a written guide with the screenshots inline |
| `AgentOps-Developer-Walkthrough.pptx` | 47 slides, 16:9 — the same walkthrough as a deck |

Both carry **30 screenshots captured from the running application**, not mock-ups.
That is the point of this pipeline: the documents cannot show a UI the code no
longer has, because they are rebuilt from a live capture.

```bash
./run.sh                              # the app must be running on :8000
./scripts/walkthrough/build.sh        # capture → optimise → build → QA
./scripts/walkthrough/build.sh --no-capture   # rebuild from existing shots
```

## What each stage does

| File | Stage |
|---|---|
| `populate.py` | Stages the demo. Runs the fleet sweep and the procurement agents against their sample attachments, then **approves each proposal as the persona whose authority actually covers it** — the platform's own loop, not a shortcut around it. Without this, half the screens capture as empty states, because approving is what fills the business tables. |
| `capture.mjs` | Drives Chromium through all 22 screens plus three drawer states and the checkpoint's three tabs. Fails loudly on a page error rather than saving a blank frame. |
| `content.js` | The shared content — the tour commentary, the code excerpts, the tables. Both deliverables read it, so the deck and the PDF cannot disagree. |
| `deck.js` | The PPTX, via `pptxgenjs`. Code blocks size themselves to fit and throw below 8pt rather than shipping clipped code. |
| `pdf.js` + `print.mjs` | The PDF: a paginated HTML document printed by Chromium. Carries fuller prose than the deck has room for. |
| `qa.py` | Geometric QA on the deck: every shape inside the canvas, no colliding text boxes, and a font-metric estimate of text fit. |

## A note on QA

LibreOffice cannot render in every environment, so slide QA here is
**geometric rather than visual** — `qa.py` measures the shape geometry the file
actually contains and estimates text fit from font metrics, which catches what a
visual pass looks for: off-canvas shapes, colliding boxes, and text that cannot
fit its container. The PDF is verified differently: it is rasterised page by page
with `pypdfium2` and inspected.

Where LibreOffice *is* available, render the deck too:

```bash
soffice --headless --convert-to pdf docs/walkthrough/AgentOps-Developer-Walkthrough.pptx
```

## When to rebuild

After a UI change that alters any captured screen, after adding an agent (the
tour and the code sections reference the fleet), or after changing a threshold
quoted in the commentary. The commentary in `content.js` is hand-written and is
the one part that can go stale — treat it the way you treat
`scripts/agent_build_notes.py`.
