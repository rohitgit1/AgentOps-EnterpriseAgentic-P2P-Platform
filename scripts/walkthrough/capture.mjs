import pw from 'playwright'
const { chromium } = pw

const BASE = 'http://127.0.0.1:8000'
const OUT = process.env.WALKTHROUGH_SHOTS ||
  new URL('../../build/walkthrough/shots', import.meta.url).pathname

const browser = await chromium.launch({ ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}) })
const ctx = await browser.newContext({ viewport: { width: 1680, height: 1000 }, deviceScaleFactor: 2 })
const page = await ctx.newPage()
const errors = []
page.on('pageerror', e => errors.push('' + e))

const shot = async (name, wait = 900) => {
  await page.waitForTimeout(wait)
  await page.screenshot({ path: `${OUT}/${name}.png` })
  console.log('  ✓', name)
}
const go = async (label, name) => {
  await page.locator(`nav a:has-text("${label}")`).first().click()
  await shot(name)
}

await page.goto(BASE, { waitUntil: 'networkidle' })
await shot('01-login')

const controller = page.locator('button', { hasText: 'Sasha Mbeki' })
await (await controller.count() ? controller.first() : page.locator('button').first()).click()
await page.waitForTimeout(1800)

await shot('02-dashboard')

await go('Approval Inbox', '03-inbox')

// Checkpoint drawer + its three tabs
// The inbox rows are clickable divs, not buttons.
await page.locator('div.cursor-pointer.group').first().click()
await shot('04-checkpoint-proposal')
await page.locator('button:has-text("Agent reasoning")').click(); await shot('05-checkpoint-reasoning')
await page.locator('button:has-text("Policy & audit")').click(); await shot('06-checkpoint-policy')
await page.keyboard.press('Escape'); await page.waitForTimeout(500)

await go('Invoices', '07-invoices')
await page.locator('tbody tr, div.cursor-pointer').first().click().catch(() => {})
await shot('08-invoice-detail')
await page.keyboard.press('Escape'); await page.waitForTimeout(400)

await go('Exceptions', '09-exceptions')
await go('Payments', '10-payments')

await page.locator('nav a[href="/procurement"]').click(); await shot('11-procurement')
await go('Sourcing Events', '12-sourcing')
await go('Spend & Savings', '13-spend')
await go('Supplier Risk', '14-supplier-risk')
await go('Contracts', '15-contracts')
await go('Tail Spend', '16-tail-spend')

await go('Agent Control Room', '17-control-room')
await page.locator('button:has-text("Configure")').first().click()
await shot('18-agent-config')
await page.keyboard.press('Escape'); await page.waitForTimeout(400)

await go('Agent I/O Catalogue', '19-agent-io')
await go('Artifact Library', '20-artifacts')
await go('SLA Command Center', '21-sla')
await go('Skills Library', '22-skills')
await go('Audit Trail', '23-audit')
await go('Governance', '24-governance')

await go('Agents Academy', '25-academy')
await page.locator('nav button:has-text("Sourcing Event")').first().click()
await page.waitForTimeout(700)
await page.locator('text=Input and output').scrollIntoViewIfNeeded()
await shot('26-academy-io')
await page.locator('text=Worked example').scrollIntoViewIfNeeded()
await shot('27-academy-example')

await go('Data Model', '28-data-model')
await page.locator('button:has-text("human_tasks")').first().click()
await shot('29-data-model-drawer')
await page.keyboard.press('Escape'); await page.waitForTimeout(400)

await page.goto(`${BASE}/api/docs`, { waitUntil: 'networkidle' })
await shot('30-api-docs', 2500)

console.log('page errors:', errors.length ? JSON.stringify(errors) : 'none')
await browser.close()
