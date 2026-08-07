import pw from 'playwright'
const SC = process.env.WALKTHROUGH_BUILD ||
  new URL('../../build/walkthrough', import.meta.url).pathname
const b = await pw.chromium.launch({ ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}) })
const p = await b.newPage()
const errs = []
p.on('pageerror', e => errs.push('' + e))
await p.goto('file://' + SC + '/walkthrough.html', { waitUntil: 'networkidle' })
await p.waitForTimeout(1500)
await p.pdf({
  path: (process.env.WALKTHROUGH_OUT || SC) + '/AgentOps-Developer-Walkthrough.pdf',
  format: 'A4', printBackground: true,
  margin: { top: '16mm', bottom: '18mm', left: '15mm', right: '15mm' },
  displayHeaderFooter: true,
  headerTemplate: '<div></div>',
  footerTemplate: `<div style="width:100%;font:8pt Calibri,Arial,sans-serif;color:#8E9AB0;
     padding:0 15mm;display:flex;justify-content:space-between">
     <span>AgentOps · Developer Walkthrough</span>
     <span class="pageNumber"></span></div>`,
})
console.log('errors:', errs.length ? JSON.stringify(errs) : 'none')
await b.close()
