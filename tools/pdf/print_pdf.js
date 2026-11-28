// manual.html -> PDF with page numbers (Playwright, Chromium).
//   node print_pdf.js manual.html out.pdf
const { chromium } = require('playwright');
const path = require('path');
(async () => {
  const [src, out] = process.argv.slice(2);
  const b = await chromium.launch();
  const p = await b.newPage();
  await p.goto('file://' + path.resolve(src), { waitUntil: 'load' });
  await p.evaluate(() => document.fonts.ready);
  const foot = `<div style="width:100%;font-size:8px;color:#888;font-family:NanumBarunGothic,NanumGothic,sans-serif;
    padding:0 18mm;display:flex;justify-content:space-between"><span>Ghazni Scope 사용 매뉴얼</span>
    <span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>`;
  await p.pdf({ path: out, format: 'A4', printBackground: true, displayHeaderFooter: true,
                headerTemplate: '<span></span>', footerTemplate: foot,
                margin: { top: '20mm', bottom: '20mm', left: '18mm', right: '18mm' }, outline: true, tagged: true });
  await b.close();
  console.log('wrote ' + out);
})();
