const pptxgen = require('pptxgenjs')
const { IMG, P, F, TOUR, CODE, TREE, RUNLOOP, ROLES, GATES } = require('./content.js')

const pres = new pptxgen()
pres.layout = 'LAYOUT_WIDE'          // 13.3 x 7.5 — must be set before any slide
pres.author = 'AgentOps'
pres.title = 'AgentOps — Developer Walkthrough'

const W = 13.3, H = 7.5

// --------------------------------------------------------------------------
// Primitives. Every call builds fresh option objects — pptxgenjs mutates them.
// --------------------------------------------------------------------------
const newSlide = (bg = P.bg) => {
  const s = pres.addSlide()
  s.background = { color: bg }
  return s
}

const card = (s, x, y, w, h, opts = {}) =>
  s.addShape(pres.ShapeType.roundRect, {
    x, y, w, h, rectRadius: opts.radius ?? 0.08,
    fill: { color: opts.fill ?? P.card },
    line: { color: opts.line ?? P.line, width: opts.lw ?? 1 },
  })

const kicker = (s, text, x = 0.62, y = 0.34) =>
  s.addText(text.toUpperCase(), {
    x, y, w: 9, h: 0.26, margin: 0, fontFace: F.body, fontSize: 11,
    bold: true, color: P.accent, charSpacing: 2.4,
  })

const title = (s, text, x = 0.62, y = 0.62, w = 12.1, size = 30) =>
  s.addText(text, {
    x, y, w, h: 0.62, margin: 0, fontFace: F.head, fontSize: size,
    bold: true, color: P.text,
  })

const lede = (s, text, x = 0.62, y = 1.24, w = 12.1) =>
  s.addText(text, {
    x, y, w, h: 0.4, margin: 0, fontFace: F.body, fontSize: 14.5,
    color: P.muted, lineSpacing: 20,
  })

const pageNo = (s, n) =>
  s.addText(String(n), {
    x: W - 1.05, y: H - 0.52, w: 0.5, h: 0.3, margin: 0, align: 'right',
    fontFace: F.body, fontSize: 10.5, color: P.faint,
  })

const footer = (s, text) =>
  s.addText(text, {
    x: 0.62, y: H - 0.52, w: 9, h: 0.3, margin: 0,
    fontFace: F.body, fontSize: 10.5, color: P.faint,
  })

/** A numbered disc — the deck's one repeating motif. */
const disc = (s, n, x, y, d = 0.36, color = P.accent) => {
  s.addShape(pres.ShapeType.ellipse, {
    x, y, w: d, h: d, fill: { color: color + '' }, line: { color: color, width: 0 },
  })
  s.addText(String(n), {
    x, y, w: d, h: d, margin: 0, align: 'center', valign: 'middle',
    fontFace: F.body, fontSize: 13, bold: true, color: P.bg,
  })
}

/** Inline `code` spans rendered in mono. */
const rich = (text, base) => {
  const parts = []
  text.split(/(`[^`]+`|\*[^*]+\*)/).filter(Boolean).forEach((chunk) => {
    if (chunk.startsWith('`') && chunk.endsWith('`'))
      parts.push({ text: chunk.slice(1, -1), options: { ...base, fontFace: F.mono, fontSize: base.fontSize - 1.5, color: P.accent } })
    else if (chunk.startsWith('*') && chunk.endsWith('*'))
      parts.push({ text: chunk.slice(1, -1), options: { ...base, italic: true } })
    else parts.push({ text: chunk, options: { ...base } })
  })
  return parts
}

const codeBlock = (s, code, x, y, w, h, size = 10.5) => {
  // Clipped code is the defect this deck is most prone to, so the block sizes
  // itself down to fit rather than silently spilling. Below 8pt it is
  // unreadable, and the right fix is less code — so that throws instead.
  const lines = code.split('\n').length
  const longest = Math.max(...code.split('\n').map((l) => l.length))
  const PAD = 0.36
  let pt = Math.min(size, ((h - PAD) * 72) / (lines * 1.5))
  // Courier New is ~0.6em wide; keep the longest line inside the box too.
  pt = Math.min(pt, ((w - 0.44) * 72) / (longest * 0.605))
  pt = Math.floor(pt * 2) / 2
  if (pt < 8)
    throw new Error(`code block cannot fit: ${lines} lines x ${longest} cols ` +
                    `in ${w.toFixed(2)}x${h.toFixed(2)}" would need ${pt}pt`)
  card(s, x, y, w, h, { fill: '080D1A', line: '243250' })
  s.addText(code, {
    x: x + 0.22, y: y + 0.18, w: w - 0.44, h: h - 0.36, margin: 0,
    fontFace: F.mono, fontSize: pt, color: 'B9C6DE', lineSpacing: pt * 1.5,
    valign: 'top',
  })
}

let page = 0
const nextPage = () => ++page

// ==========================================================================
// 1 · Title
// ==========================================================================
{
  const s = newSlide()
  s.addShape(pres.ShapeType.ellipse, {
    x: 9.4, y: -1.9, w: 6.6, h: 6.6, fill: { color: P.accent, transparency: 90 }, line: { width: 0 },
  })
  s.addShape(pres.ShapeType.ellipse, {
    x: 11.0, y: 3.4, w: 4.4, h: 4.4, fill: { color: P.violet, transparency: 92 }, line: { width: 0 },
  })

  s.addText('DEVELOPER WALKTHROUGH', {
    x: 0.9, y: 1.75, w: 9, h: 0.3, margin: 0, fontFace: F.body, fontSize: 12.5,
    bold: true, color: P.accent, charSpacing: 3.2,
  })
  s.addText('AgentOps', {
    x: 0.88, y: 2.12, w: 10, h: 1.15, margin: 0,
    fontFace: F.head, fontSize: 58, bold: true, color: P.text,
  })
  s.addText('Enterprise Agentic P2P & Procurement Platform', {
    x: 0.9, y: 3.32, w: 10, h: 0.55, margin: 0,
    fontFace: F.head, fontSize: 25, color: P.muted,
  })
  s.addText('Sixteen agents. Twenty-eight skills. Zero write access.', {
    x: 0.9, y: 4.0, w: 10, h: 0.4, margin: 0,
    fontFace: F.body, fontSize: 16, italic: true, color: P.mint,
  })

  const stats = [['16', 'agents'], ['28', 'skills'], ['33', 'actions'], ['29', 'tables'], ['79', 'tests']]
  stats.forEach(([n, l], i) => {
    const x = 0.9 + i * 1.68
    s.addText(n, { x, y: 4.86, w: 1.5, h: 0.68, margin: 0, fontFace: F.head, fontSize: 34, bold: true, color: P.accent })
    s.addText(l, { x, y: 5.52, w: 1.5, h: 0.3, margin: 0, fontFace: F.body, fontSize: 12, color: P.faint })
  })

  s.addText('30 live screenshots captured from the running application', {
    x: 0.9, y: 6.42, w: 11, h: 0.3, margin: 0, fontFace: F.body, fontSize: 12.5, color: P.faint,
  })
  s.addNotes('A developer walkthrough: the product screen by screen from live captures, then the code that makes the guarantees hold.')
}

// ==========================================================================
// 2 · The invariant
// ==========================================================================
{
  const s = newSlide()
  kicker(s, 'Start here')
  title(s, 'One rule explains the whole system')

  card(s, 0.62, 1.62, 12.06, 1.55, { fill: '10203A', line: P.accent, radius: 0.06 })
  s.addText('An agent returns proposals, never mutations.', {
    x: 1.0, y: 1.9, w: 11.3, h: 0.55, margin: 0,
    fontFace: F.head, fontSize: 27, bold: true, color: P.text,
  })
  s.addText(rich('There is no code path from an agent to a business table. Not a convention, not a review rule — a structural fact.', { fontFace: F.body, fontSize: 14.5, color: P.muted }), {
    x: 1.0, y: 2.52, w: 11.3, h: 0.45, margin: 0, lineSpacing: 20,
  })

  const three = [
    ['A proposal is inert', '`ProposedAction` is a dataclass. No session, no ORM object, no executor reference. It cannot write because there is nothing in it to write with.'],
    ['One consumer', 'The only code that reads a proposal is `hitl.create_checkpoint()`, which writes a `HumanTask` row and nothing else.'],
    ['One writer', 'Business data is written only by an `@action(...)` executor, reachable only from `hitl.decide()` after an authority check.'],
  ]
  three.forEach(([h, b], i) => {
    const x = 0.62 + i * 4.12
    card(s, x, 3.45, 3.82, 2.45)
    disc(s, i + 1, x + 0.3, 3.72)
    s.addText(h, { x: x + 0.3, y: 4.24, w: 3.25, h: 0.34, margin: 0, fontFace: F.head, fontSize: 16, bold: true, color: P.text })
    s.addText(rich(b, { fontFace: F.body, fontSize: 12, color: P.muted }), {
      x: x + 0.3, y: 4.64, w: 3.25, h: 1.1, margin: 0, lineSpacing: 16, valign: 'top',
    })
  })

  s.addText(rich('Everything else in this guide is a consequence of that sentence.', { fontFace: F.body, fontSize: 13.5, italic: true, color: P.mint }), {
    x: 0.62, y: 6.16, w: 12, h: 0.35, margin: 0,
  })
  footer(s, 'AgentOps · Developer Walkthrough'); pageNo(s, nextPage())
  s.addNotes('If a rebuild breaks this, it has the same screens and none of the guarantees.')
}

// ==========================================================================
// 3 · Contents
// ==========================================================================
{
  const s = newSlide()
  kicker(s, 'How this guide runs')
  title(s, 'Three parts, in the order you need them')

  const parts = [
    ['01', 'Orientation', 'Repository layout, the three ways to run it, and the authority ladder that governs everything you will click.', P.accent],
    ['02', 'The product, screen by screen', 'All 22 screens from live captures — what each one shows and, for each, what a developer should actually notice.', P.violet],
    ['03', 'The code', 'The run loop, the anatomy of an agent, the policy engine, the executor registry, and how to add your own.', P.mint],
  ]
  parts.forEach(([n, h, b, c], i) => {
    const y = 1.72 + i * 1.72
    card(s, 0.62, y, 12.06, 1.5)
    s.addText(n, { x: 1.0, y: y + 0.32, w: 1.0, h: 0.8, margin: 0, fontFace: F.head, fontSize: 40, bold: true, color: c })
    s.addText(h, { x: 2.2, y: y + 0.3, w: 9.9, h: 0.4, margin: 0, fontFace: F.head, fontSize: 21, bold: true, color: P.text })
    s.addText(b, { x: 2.2, y: y + 0.76, w: 9.9, h: 0.55, margin: 0, fontFace: F.body, fontSize: 13.5, color: P.muted, lineSpacing: 19 })
  })

  s.addText(rich('Every screenshot in Part 02 was captured from this application running locally, after a live agent sweep. Nothing is a mock-up.', { fontFace: F.body, fontSize: 13, color: P.faint }), {
    x: 0.62, y: 6.9, w: 11.4, h: 0.35, margin: 0,
  })
  pageNo(s, nextPage())
}

// ==========================================================================
// 4 · Repository layout
// ==========================================================================
{
  const s = newSlide()
  kicker(s, 'Part 01 · Orientation')
  title(s, 'Where everything lives')
  lede(s, 'Roughly 25,000 lines. The four files that carry the guarantees are marked.')

  codeBlock(s, TREE, 0.62, 1.82, 8.0, 4.7, 10.5)

  const notes = [
    ['policy.py', 'The seven gates. Read this before changing any threshold.', P.amber],
    ['hitl.py', 'The only place business data is written. 33 executors, one per action.', P.rose],
    ['agents/base.py', 'The run loop every agent shares — which is why the guarantees hold uniformly.', P.accent],
    ['enums.py', 'Everything downstream references it. Change here, regenerate everywhere.', P.violet],
  ]
  s.addText('THE FOUR THAT MATTER', {
    x: 8.86, y: 1.82, w: 3.8, h: 0.28, margin: 0, fontFace: F.body, fontSize: 10.5,
    bold: true, color: P.faint, charSpacing: 2,
  })
  notes.forEach(([n, b, c], i) => {
    const y = 2.24 + i * 1.1
    card(s, 8.86, y, 3.82, 0.96, { fill: P.card2 })
    s.addText(n, { x: 9.1, y: y + 0.14, w: 3.4, h: 0.28, margin: 0, fontFace: F.mono, fontSize: 12, bold: true, color: c })
    s.addText(b, { x: 9.1, y: y + 0.42, w: 3.4, h: 0.5, margin: 0, fontFace: F.body, fontSize: 11, color: P.muted, lineSpacing: 14 })
  })
  footer(s, 'Part 01 · Orientation'); pageNo(s, nextPage())
}

// ==========================================================================
// 5 · Running it
// ==========================================================================
{
  const s = newSlide()
  kicker(s, 'Part 01 · Orientation')
  title(s, 'Three ways to run it')
  lede(s, 'No cloud account, no API key, no database server. SQLite by default, one process, one port.')

  const ways = [
    ['Standard', './run.sh          # macOS / Linux\n.\\run.ps1         # Windows\n\n# → http://localhost:8000', 'Installs, builds the SPA, seeds the demo, serves API and UI on one port. Idempotent — safe to re-run.', P.accent],
    ['Development', './run.sh --dev\n\n# UI  → :5173  (hot reload)\n# API → :8000\n\nP2P_RELOAD=1 ./run.sh --dev', 'Vite proxies /api to the backend. Use :5173 — port 8000 serves the last built UI, which will be stale.', P.violet],
    ['Docker', 'docker compose up --build\n\n# fresh start:\ndocker compose down -v', 'Nothing on the host. The demo database persists in the p2p-data volume, so decisions survive a restart.', P.mint],
  ]
  ways.forEach(([h, code, note, c], i) => {
    const x = 0.62 + i * 4.12
    card(s, x, 1.86, 3.82, 4.5)
    s.addText(h, { x: x + 0.28, y: 2.06, w: 3.3, h: 0.36, margin: 0, fontFace: F.head, fontSize: 19, bold: true, color: c })
    card(s, x + 0.28, 2.5, 3.26, 1.65, { fill: '080D1A', line: '243250' })
    s.addText(code, { x: x + 0.44, y: 2.62, w: 2.98, h: 1.45, margin: 0, fontFace: F.mono, fontSize: 9.5, color: 'B9C6DE', lineSpacing: 14, valign: 'top' })
    s.addText(note, { x: x + 0.28, y: 4.32, w: 3.3, h: 1.2, margin: 0, fontFace: F.body, fontSize: 12, color: P.muted, lineSpacing: 17, valign: 'top' })
  })

  s.addText(rich('First run takes 1–3 minutes (virtualenv + npm install + UI build). Subsequent runs start in seconds.', { fontFace: F.body, fontSize: 12.5, color: P.faint }), {
    x: 0.62, y: 6.62, w: 12, h: 0.3, margin: 0,
  })
  footer(s, 'Part 01 · Orientation'); pageNo(s, nextPage())
}

// ==========================================================================
// 6 · The authority ladder
// ==========================================================================
{
  const s = newSlide()
  kicker(s, 'Part 01 · Orientation')
  title(s, 'The authority ladder')
  lede(s, 'A ladder, not a set — a Controller can decide everything a clerk can. This is enforced server-side, not in the UI.')

  s.addTable(
    [[
      { text: 'ROLE', options: { bold: true, color: P.faint, fontSize: 11, fontFace: F.body } },
      { text: 'AUTHORITY', options: { bold: true, color: P.faint, fontSize: 11, fontFace: F.body } },
      { text: 'MAY DECIDE', options: { bold: true, color: P.faint, fontSize: 11, fontFace: F.body } },
    ],
    ...ROLES.map(([r, a, d]) => [
      { text: r, options: { fontFace: F.mono, fontSize: 12, color: P.accent } },
      { text: a, options: { fontFace: F.body, fontSize: 12.5, color: P.text, bold: true } },
      { text: d, options: { fontFace: F.body, fontSize: 12.5, color: P.muted } },
    ])],
    { x: 0.62, y: 1.9, w: 7.7, colW: [2.1, 1.3, 4.3], rowH: 0.42,
      border: { type: 'solid', color: P.line, pt: 0.5 }, fill: { color: P.card },
      margin: [4, 10, 4, 10], valign: 'middle' }
  )

  card(s, 8.6, 1.9, 4.08, 3.5, { fill: P.card2 })
  s.addText('ESCALATION BY VALUE', { x: 8.88, y: 2.1, w: 3.6, h: 0.28, margin: 0, fontFace: F.body, fontSize: 10.5, bold: true, color: P.faint, charSpacing: 2 })
  s.addText('On top of the per-action minimum:', { x: 8.88, y: 2.42, w: 3.6, h: 0.3, margin: 0, fontFace: F.body, fontSize: 12, color: P.muted })
  const esc = [['≥ $50,000', 'Controller required', P.amber], ['≥ $250,000', 'CFO required', P.rose], ['≥ $100,000\n+ irreversible', 'Two distinct approvers', P.violet]]
  esc.forEach(([a, b, c], i) => {
    const y = 2.86 + i * 0.82
    s.addText(a, { x: 8.88, y, w: 1.65, h: 0.6, margin: 0, fontFace: F.mono, fontSize: 11.5, color: c, valign: 'middle' })
    s.addText(b, { x: 10.6, y, w: 1.9, h: 0.6, margin: 0, fontFace: F.body, fontSize: 12, color: P.text, valign: 'middle' })
  })

  card(s, 8.6, 5.6, 4.08, 0.94, { fill: '1A1420', line: P.rose })
  s.addText(rich('Dual approval compares `user.id`, not role. The same person approving twice is one approval.', { fontFace: F.body, fontSize: 11.5, color: P.text }), {
    x: 8.86, y: 5.76, w: 3.56, h: 0.65, margin: 0, lineSpacing: 15, valign: 'middle',
  })
  footer(s, 'Part 01 · Orientation'); pageNo(s, nextPage())
}

// ==========================================================================
// 7..36 · The tour — one live screenshot per slide
// ==========================================================================
TOUR.forEach((t) => {
  const s = newSlide()
  kicker(s, `Part 02 · ${t.part}`)
  title(s, t.title, 0.62, 0.6, 12.1, 26)
  s.addText(t.lede, { x: 0.62, y: 1.24, w: 12.1, h: 0.34, margin: 0, fontFace: F.body, fontSize: 13, color: P.muted })

  // Screenshot with a thin frame — 1680x1000 source, 8.35" wide keeps 2x density.
  const ix = 0.62, iy = 1.66, iw = 8.35, ih = iw * 1000 / 1680
  s.addShape(pres.ShapeType.roundRect, {
    x: ix - 0.05, y: iy - 0.05, w: iw + 0.1, h: ih + 0.1, rectRadius: 0.05,
    fill: { color: P.card }, line: { color: P.line, width: 1 },
  })
  s.addImage({ path: `${IMG}/${t.img}.jpg`, x: ix, y: iy, w: iw, h: ih })

  s.addText('WHAT TO LOOK AT', {
    x: 9.24, y: 1.66, w: 3.5, h: 0.28, margin: 0, fontFace: F.body, fontSize: 10.5,
    bold: true, color: P.faint, charSpacing: 2,
  })
  t.look.forEach(([h, b], i) => {
    const y = 2.06 + i * 1.52
    card(s, 9.24, y, 3.44, 1.36, { fill: P.card2 })
    s.addText(rich(h, { fontFace: F.head, fontSize: 13.5, bold: true, color: P.text }), {
      x: 9.46, y: y + 0.13, w: 3.0, h: 0.46, margin: 0, lineSpacing: 16, valign: 'top',
    })
    s.addText(rich(b, { fontFace: F.body, fontSize: 10.5, color: P.muted }), {
      x: 9.46, y: y + 0.6, w: 3.0, h: 0.68, margin: 0, lineSpacing: 13.5, valign: 'top',
    })
  })

  footer(s, `Part 02 · ${t.part}`)
  pageNo(s, nextPage())
  s.addNotes(`${t.title}. ${t.lede} ${t.look.map(([h, b]) => `${h}: ${b.replace(/[`*]/g, '')}`).join(' ')}`)
})

// ==========================================================================
// Part 03 · The code
// ==========================================================================
{
  const s = newSlide()
  s.addShape(pres.ShapeType.ellipse, { x: -1.8, y: 3.9, w: 6.0, h: 6.0, fill: { color: P.mint, transparency: 91 }, line: { width: 0 } })
  s.addText('PART 03', { x: 0.9, y: 2.5, w: 9, h: 0.34, margin: 0, fontFace: F.body, fontSize: 13, bold: true, color: P.mint, charSpacing: 3.2 })
  s.addText('The code', { x: 0.88, y: 2.9, w: 10, h: 0.95, margin: 0, fontFace: F.head, fontSize: 50, bold: true, color: P.text })
  s.addText('The run loop, the anatomy of an agent, the policy engine,\nthe executor registry — and how to add your own.', {
    x: 0.9, y: 3.94, w: 9.5, h: 0.9, margin: 0, fontFace: F.body, fontSize: 17, color: P.muted, lineSpacing: 26,
  })
  pageNo(s, nextPage())
}

// The run loop
{
  const s = newSlide()
  kicker(s, 'Part 03 · The code')
  title(s, 'The run loop — identical for all sixteen agents')
  lede(s, 'Everything except plan(), gather() and decide() is the base class. That is why the guarantees hold uniformly.')

  RUNLOOP.forEach(([h, b], i) => {
    const col = i % 2, row = Math.floor(i / 2)
    const x = 0.62 + col * 6.2, y = 1.92 + row * 1.16
    card(s, x, y, 5.9, 1.0, { fill: i === 6 ? '10203A' : P.card, line: i === 6 ? P.accent : P.line })
    disc(s, i + 1, x + 0.26, y + 0.32, 0.36, i === 6 ? P.accent : P.violet)
    s.addText(h, { x: x + 0.78, y: y + 0.14, w: 4.9, h: 0.32, margin: 0, fontFace: F.head, fontSize: 15, bold: true, color: P.text })
    s.addText(rich(b, { fontFace: F.body, fontSize: 11.5, color: P.muted }), {
      x: x + 0.78, y: y + 0.47, w: 4.9, h: 0.44, margin: 0, lineSpacing: 15, valign: 'top',
    })
  })

  s.addText(rich('Step 7 is where the guarantee lives: `policy.evaluate()` runs on every proposal, and the result is a `HumanTask` — never a write.', { fontFace: F.body, fontSize: 13, color: P.mint }), {
    x: 0.62, y: 6.62, w: 12, h: 0.35, margin: 0,
  })
  footer(s, 'Part 03 · The code'); pageNo(s, nextPage())
}

// ProposedAction
{
  const s = newSlide()
  kicker(s, 'Part 03 · The code')
  title(s, 'Why an agent cannot write')
  lede(s, 'The whole guarantee reduces to what this dataclass does not contain.')
  codeBlock(s, CODE.proposal, 0.62, 1.86, 7.7, 4.4, 11.5)

  card(s, 8.56, 1.86, 4.12, 4.4, { fill: P.card2 })
  s.addText('THE CONSEQUENCE', { x: 8.84, y: 2.06, w: 3.6, h: 0.28, margin: 0, fontFace: F.body, fontSize: 10.5, bold: true, color: P.faint, charSpacing: 2 })
  const cons = [
    'An agent that wanted to write to a business table would have to be rewritten to do so — it is not a matter of discipline.',
    'A code reviewer does not need to check for stray writes. There is nothing to write with.',
    'Testing this is trivial: run the agent, count the rows, assert nothing moved.',
  ]
  cons.forEach((c, i) => {
    const y = 2.46 + i * 1.28
    disc(s, i + 1, 8.84, y, 0.32, P.mint)
    s.addText(c, { x: 9.28, y: y - 0.04, w: 3.16, h: 1.1, margin: 0, fontFace: F.body, fontSize: 12, color: P.muted, lineSpacing: 17, valign: 'top' })
  })
  footer(s, 'Part 03 · The code'); pageNo(s, nextPage())
}

// plan()
{
  const s = newSlide()
  kicker(s, 'Part 03 · The code')
  title(s, 'Anatomy of an agent — plan()')
  lede(s, 'Three-Way Match, the clearest of the sixteen. plan() declares the steps; it does not run them.')
  codeBlock(s, CODE.plan, 0.62, 1.9, 7.7, 3.1, 10)

  card(s, 0.62, 5.2, 7.7, 1.2, { fill: '10203A', line: P.accent })
  s.addText(rich('plan() is called with an empty context by the Academy screen and by the build-spec generator. If it queried the database, both would break — and it would no longer be a plan, it would be a trace.', { fontFace: F.body, fontSize: 12.5, color: P.text }), {
    x: 0.9, y: 5.36, w: 7.16, h: 0.9, margin: 0, lineSpacing: 17, valign: 'top',
  })

  card(s, 8.56, 1.9, 4.12, 4.46, { fill: P.card2 })
  s.addText('EVERY STEP ANSWERS THREE THINGS', { x: 8.84, y: 2.1, w: 3.6, h: 0.28, margin: 0, fontFace: F.body, fontSize: 10.5, bold: true, color: P.faint, charSpacing: 2 })
  const three3 = [
    ['What it does', 'Written for a reviewer, not a log line.'],
    ['Which tool', 'The name shown in the Academy and in the run timeline.'],
    ['Why', 'The rationale a reader needs to judge whether the step belongs. "Header totals hide offsetting line errors" is a reason; "fetch data" is not.'],
  ]
  three3.forEach(([h, b], i) => {
    const y = 2.5 + i * 1.28
    disc(s, i + 1, 8.84, y, 0.32, P.violet)
    s.addText(h, { x: 9.28, y: y - 0.02, w: 3.16, h: 0.3, margin: 0, fontFace: F.head, fontSize: 14, bold: true, color: P.text })
    s.addText(b, { x: 9.28, y: y + 0.3, w: 3.16, h: 0.9, margin: 0, fontFace: F.body, fontSize: 11.5, color: P.muted, lineSpacing: 16, valign: 'top' })
  })
  footer(s, 'Part 03 · The code'); pageNo(s, nextPage())
}

// gather()
{
  const s = newSlide()
  kicker(s, 'Part 03 · The code')
  title(s, 'Anatomy of an agent — gather()')
  lede(s, 'Collects evidence and returns one Observation per tool. Still writes nothing.')
  codeBlock(s, CODE.gather, 0.62, 1.9, 7.7, 3.7, 10)

  card(s, 0.62, 5.82, 7.7, 0.7, { fill: '1A1420', line: P.rose })
  s.addText(rich('State goes on `context`, never on `self`. Agents are singletons in the registry — anything stored on the instance leaks into the next run.', { fontFace: F.body, fontSize: 12.5, color: P.text }), {
    x: 0.9, y: 5.94, w: 7.16, h: 0.5, margin: 0, valign: 'middle',
  })

  card(s, 8.56, 1.9, 4.12, 4.62, { fill: P.card2 })
  s.addText('WHY IT IS SHAPED THIS WAY', { x: 8.84, y: 2.1, w: 3.6, h: 0.28, margin: 0, fontFace: F.body, fontSize: 10.5, bold: true, color: P.faint, charSpacing: 2 })
  const why = [
    ['One Observation per tool', 'Each is persisted and streamed to the activity rail as it happens, so a reviewer sees what was asked and what came back.'],
    ['Policy is read per run', 'Tolerances come from `policy_rules` every time, so loosening one takes effect without a deploy.'],
    ['Failure is an observation too', '`ok=False` with a summary. An agent that cannot read its input says so rather than raising.'],
  ]
  why.forEach(([h, b], i) => {
    const y = 2.5 + i * 1.34
    disc(s, i + 1, 8.84, y, 0.32, P.mint)
    s.addText(h, { x: 9.28, y: y - 0.02, w: 3.16, h: 0.3, margin: 0, fontFace: F.head, fontSize: 14, bold: true, color: P.text })
    s.addText(rich(b, { fontFace: F.body, fontSize: 11.5, color: P.muted }), { x: 9.28, y: y + 0.3, w: 3.16, h: 0.95, margin: 0, lineSpacing: 16, valign: 'top' })
  })
  footer(s, 'Part 03 · The code'); pageNo(s, nextPage())
}

// decide
{
  const s = newSlide()
  kicker(s, 'Part 03 · The code')
  title(s, 'Anatomy of an agent — decide()')
  lede(s, 'Returns an AgentDecision. Every field is something a reviewer will read.')
  codeBlock(s, CODE.decide, 0.62, 1.86, 7.7, 4.5, 10)

  card(s, 8.56, 1.86, 4.12, 4.5, { fill: P.card2 })
  s.addText('THE FOUR RULES', { x: 8.84, y: 2.06, w: 3.6, h: 0.28, margin: 0, fontFace: F.body, fontSize: 10.5, bold: true, color: P.faint, charSpacing: 2 })
  const rules = [
    ['Confidence is real', 'A number the agent stands behind. The policy engine gates on it, so a constant 0.95 defeats the control.'],
    ['Evidence cites its source', 'Every item names the observation it came from.'],
    ['Impact is what is at risk', 'It drives role escalation. Inflated blocks work; deflated under-reviews it.'],
    ['Rules are quantitative', '"+8.00% against a 3% tolerance" is arguable. "Looks wrong" is not.'],
  ]
  rules.forEach(([h, b], i) => {
    const y = 2.44 + i * 1.0
    s.addText(h, { x: 8.84, y, w: 3.6, h: 0.28, margin: 0, fontFace: F.head, fontSize: 13.5, bold: true, color: P.mint })
    s.addText(b, { x: 8.84, y: y + 0.29, w: 3.6, h: 0.64, margin: 0, fontFace: F.body, fontSize: 11, color: P.muted, lineSpacing: 14.5, valign: 'top' })
  })
  footer(s, 'Part 03 · The code'); pageNo(s, nextPage())
}

// Policy engine
{
  const s = newSlide()
  kicker(s, 'Part 03 · The code')
  title(s, 'The policy engine — seven gates, default deny')
  lede(s, 'allow_auto_execute requires every gate to open. Anything else becomes a checkpoint.')

  GATES.forEach(([g, open], i) => {
    const y = 1.86 + i * 0.63
    card(s, 0.62, y, 5.9, 0.53, { fill: P.card })
    disc(s, i + 1, 0.78, y + 0.09, 0.34, i < 3 ? P.rose : P.amber)
    s.addText(g, { x: 1.24, y: y + 0.02, w: 2.5, h: 0.5, margin: 0, fontFace: F.body, fontSize: 12.5, bold: true, color: P.text, valign: 'middle' })
    s.addText(rich(open, { fontFace: F.body, fontSize: 11, color: P.muted }), { x: 3.8, y: y + 0.02, w: 2.6, h: 0.5, margin: 0, valign: 'middle' })
  })
  s.addText('OPENS WHEN', { x: 3.8, y: 1.6, w: 2.6, h: 0.22, margin: 0, fontFace: F.body, fontSize: 9.5, bold: true, color: P.faint, charSpacing: 1.6 })

  codeBlock(s, CODE.policy, 6.78, 1.86, 5.9, 4.44, 9.5)

  card(s, 0.62, 6.42, 12.06, 0.62, { fill: '10203A', line: P.accent })
  s.addText(rich('Turning global enforcement off opens gate 1 only. An L2 agent still stops, an irreversible action still stops, a low-confidence proposal still stops.', { fontFace: F.body, fontSize: 12.5, color: P.text }), {
    x: 0.9, y: 6.52, w: 11.5, h: 0.42, margin: 0, valign: 'middle',
  })
  footer(s, 'Part 03 · The code'); pageNo(s, nextPage())
}

// Executors
{
  const s = newSlide()
  kicker(s, 'Part 03 · The code')
  title(s, 'The executor registry — the only writer')
  lede(s, 'Thirty-three executors, one per action kind. If you are writing business data, you are writing one of these.')
  codeBlock(s, CODE.executor, 0.62, 1.86, 7.7, 4.5, 10)

  card(s, 8.56, 1.86, 4.12, 2.1, { fill: '1A1420', line: P.rose })
  s.addText('12 ARE IRREVERSIBLE', { x: 8.84, y: 2.04, w: 3.6, h: 0.28, margin: 0, fontFace: F.body, fontSize: 10.5, bold: true, color: P.rose, charSpacing: 2 })
  s.addText('post_to_erp · schedule_payment\nrelease_payment · block_supplier\nupdate_supplier_master\nsend_supplier_message\napprove_purchase_request\nissue_rfp · award_sourcing_event\nissue_contract_for_signature\nconsolidate_suppliers\npublish_executive_brief', {
    x: 8.84, y: 2.34, w: 3.6, h: 1.5, margin: 0, fontFace: F.mono, fontSize: 9, color: P.text, lineSpacing: 12, valign: 'top',
  })

  card(s, 8.56, 4.12, 4.12, 2.24, { fill: P.card2 })
  s.addText('EACH ONE REACHES OUTSIDE', { x: 8.84, y: 4.3, w: 3.6, h: 0.28, margin: 0, fontFace: F.body, fontSize: 10.5, bold: true, color: P.faint, charSpacing: 2 })
  s.addText(rich('A ledger, a bank, a supplier, a signature, a boardroom. None can be taken back by editing a row — so none may execute without a person, at any autonomy level, with enforcement off.', { fontFace: F.body, fontSize: 12, color: P.muted }), {
    x: 8.84, y: 4.64, w: 3.6, h: 1.5, margin: 0, lineSpacing: 17, valign: 'top',
  })
  footer(s, 'Part 03 · The code'); pageNo(s, nextPage())
}

// Adding an agent
{
  const s = newSlide()
  kicker(s, 'Part 03 · The code')
  title(s, 'Adding your own agent')
  lede(s, 'Six steps. The tests tell you what you forgot.')
  codeBlock(s, CODE.addagent, 0.62, 1.86, 7.7, 4.6, 10)

  card(s, 8.56, 1.86, 4.12, 4.6, { fill: P.card2 })
  s.addText('THE GUARDS THAT CATCH YOU', { x: 8.84, y: 2.06, w: 3.6, h: 0.28, margin: 0, fontFace: F.body, fontSize: 10.5, bold: true, color: P.faint, charSpacing: 2 })
  const guards = [
    ['No executor for an action', 'An agent may not advertise an action nothing can apply.'],
    ['No Academy lesson', 'A new agent must not ship undocumented.'],
    ['No build notes', 'A spec without the reasoning is not one anyone can rebuild from.'],
    ['A stale AGENT.md', 'Specs are regenerated in-memory and compared to what you committed.'],
  ]
  guards.forEach(([h, b], i) => {
    const y = 2.46 + i * 1.02
    s.addText('✕', { x: 8.84, y, w: 0.3, h: 0.3, margin: 0, fontFace: F.body, fontSize: 15, bold: true, color: P.rose })
    s.addText(h, { x: 9.2, y: y - 0.02, w: 3.24, h: 0.3, margin: 0, fontFace: F.head, fontSize: 13.5, bold: true, color: P.text })
    s.addText(b, { x: 9.2, y: y + 0.28, w: 3.24, h: 0.64, margin: 0, fontFace: F.body, fontSize: 11, color: P.muted, lineSpacing: 14.5, valign: 'top' })
  })
  footer(s, 'Part 03 · The code'); pageNo(s, nextPage())
}

// Testing
{
  const s = newSlide()
  kicker(s, 'Part 03 · The code')
  title(s, 'Testing — 79 tests, and the ones that fail the build')
  lede(s, 'Verified live: the full suite, the audit chain replayed from genesis, and both documentation generators.')

  const ivw = 7.2, ivh = ivw * 1466 / 2224
  s.addShape(pres.ShapeType.roundRect, {
    x: 0.57, y: 1.81, w: ivw + 0.1, h: ivh + 0.1, rectRadius: 0.05,
    fill: { color: P.card }, line: { color: P.line, width: 1 },
  })
  s.addImage({ path: `${IMG}/30-verification.jpg`, x: 0.62, y: 1.86, w: ivw, h: ivh })

  codeBlock(s, CODE.test, 8.08, 1.86, 4.6, 3.0, 8)

  card(s, 8.08, 5.02, 4.6, 1.6, { fill: '102A20', line: P.mint })
  s.addText('THREE DRIFT GUARDS', { x: 8.36, y: 5.18, w: 4.05, h: 0.28, margin: 0, fontFace: F.body, fontSize: 10.5, bold: true, color: P.mint, charSpacing: 2 })
  s.addText(rich('A new table outside a domain · a new agent without a lesson · a committed spec that no longer matches its code. Each fails the build rather than the demo.', { fontFace: F.body, fontSize: 11.5, color: P.text }), {
    x: 8.36, y: 5.5, w: 4.05, h: 1.0, margin: 0, lineSpacing: 15.5, valign: 'top',
  })
  footer(s, 'Part 03 · The code'); pageNo(s, nextPage())
}

// Where to look
{
  const s = newSlide()
  kicker(s, 'Reference')
  title(s, 'Where to look when something is wrong')

  const rows = [
    ['An agent proposes nothing', 'Its `decide()` returned no proposals, or the agent is disabled in `agent_configs`. Check the run in the Control Room — a blocked run says so.', P.amber],
    ['A proposal will not execute', 'Read the checkpoint\'s Policy & audit tab. It names the gate that held it and the role required.', P.accent],
    ['A decision is refused', 'Authority. `ACTION_MIN_ROLE`, plus value-based escalation, plus dual approval above $100k on irreversible actions.', P.violet],
    ['The audit chain is broken', '`GET /api/audit/verify` names the first divergent row. Something wrote history out of band.', P.rose],
    ['A deliverable stays a draft', 'Its checkpoint was rejected, or the proposal never carried `artifact_ids`.', P.mint],
    ['A doc test fails', 'Not a bug — a missed step. Run the two generators in `scripts/` and commit the result.', P.faint],
  ]
  rows.forEach(([h, b, c], i) => {
    const col = i % 2, row = Math.floor(i / 2)
    const x = 0.62 + col * 6.2, y = 1.62 + row * 1.62
    card(s, x, y, 5.9, 1.42)
    s.addText(h, { x: x + 0.28, y: y + 0.18, w: 5.34, h: 0.32, margin: 0, fontFace: F.head, fontSize: 16, bold: true, color: c })
    s.addText(rich(b, { fontFace: F.body, fontSize: 12, color: P.muted }), {
      x: x + 0.28, y: y + 0.54, w: 5.34, h: 0.76, margin: 0, lineSpacing: 16.5, valign: 'top',
    })
  })
  footer(s, 'AgentOps · Developer Walkthrough'); pageNo(s, nextPage())
}

// Close
{
  const s = newSlide()
  s.addShape(pres.ShapeType.ellipse, { x: 8.6, y: -2.2, w: 7.2, h: 7.2, fill: { color: P.accent, transparency: 91 }, line: { width: 0 } })
  s.addText('WHERE TO GO NEXT', { x: 0.9, y: 1.5, w: 9, h: 0.34, margin: 0, fontFace: F.body, fontSize: 12.5, bold: true, color: P.accent, charSpacing: 3.2 })
  s.addText('Read in this order', { x: 0.88, y: 1.92, w: 10, h: 0.85, margin: 0, fontFace: F.head, fontSize: 42, bold: true, color: P.text })

  const next = [
    ['docs/SPECIFICATION.md', 'The platform: guarantees, enums, data model, governance, API — and a rebuild order.'],
    ['agents/<key>/AGENT.md', 'One complete build specification per agent. Enough to rebuild it without the source.'],
    ['skills/<name>/SKILL.md', 'The 28 shared capabilities and their contracts.'],
    ['The Agents Academy screen', 'The same material, live, against seeded data you can run.'],
  ]
  next.forEach(([h, b], i) => {
    const y = 2.98 + i * 0.94
    disc(s, i + 1, 0.9, y + 0.08, 0.36, P.accent)
    s.addText(h, { x: 1.44, y, w: 5.0, h: 0.32, margin: 0, fontFace: F.mono, fontSize: 14, bold: true, color: P.text })
    s.addText(b, { x: 1.44, y: y + 0.34, w: 8.6, h: 0.5, margin: 0, fontFace: F.body, fontSize: 12.5, color: P.muted, lineSpacing: 17, valign: 'top' })
  })

  card(s, 0.88, 6.5, 11.5, 0.66, { fill: '10203A', line: P.mint })
  s.addText(rich('Check any rebuild against the invariant, not the feature list. An agent that can write to a business table has the same screens and none of the guarantees.', { fontFace: F.body, fontSize: 13, italic: true, color: P.text }), {
    x: 1.16, y: 6.6, w: 11.0, h: 0.46, margin: 0, valign: 'middle',
  })
  pageNo(s, nextPage())
}

const OUT = process.argv[2] || '/tmp/out.pptx'
pres.writeFile({ fileName: OUT }).then(() => console.log('wrote', OUT, '·', page + 1, 'slides'))
