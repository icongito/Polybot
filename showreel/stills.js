// usage: node stills.js out.jpg [--full] t1 t2 ...   (contact sheet, 3 columns; --full writes individual 1080p frames)
const { chromium } = require('/opt/node22/lib/node_modules/playwright');
const fs = require('fs'), path = require('path');
(async () => {
  let [out, ...times] = process.argv.slice(2);
  const full = times[0] === '--full'; if (full) times = times.slice(1);
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1920, height: 1080 } });
  p.on('pageerror', e => console.log('pageerror:', e.message));
  await p.goto('file://' + path.join(__dirname, 'reel.html'));
  await p.evaluate(() => window.ready);
  if (full) {
    fs.mkdirSync(out, { recursive: true });
    for (const t of times) {
      const url = await p.evaluate(t => { render(+t); return document.getElementById('c').toDataURL('image/jpeg', 0.9); }, t);
      fs.writeFileSync(path.join(out, `t${(+t).toFixed(2).padStart(5, '0')}.jpg`), Buffer.from(url.split(',')[1], 'base64'));
    }
  } else {
    const url = await p.evaluate(times => {
      const cols = 3, w = 640, h = 360, rows = Math.ceil(times.length / cols);
      const s = document.createElement('canvas'); s.width = cols * w; s.height = rows * h; const g = s.getContext('2d');
      times.forEach((t, i) => { render(+t); g.drawImage(document.getElementById('c'), (i % cols) * w, Math.floor(i / cols) * h, w, h);
        g.fillStyle = 'rgba(0,0,0,.7)'; g.fillRect((i % cols) * w, Math.floor(i / cols) * h, 70, 26); g.fillStyle = '#ff0'; g.font = 'bold 18px sans-serif'; g.fillText(t, (i % cols) * w + 6, Math.floor(i / cols) * h + 19);
        g.strokeStyle = '#555'; g.strokeRect((i % cols) * w + .5, Math.floor(i / cols) * h + .5, w - 1, h - 1); });
      return s.toDataURL('image/jpeg', 0.85);
    }, times);
    fs.writeFileSync(out, Buffer.from(url.split(',')[1], 'base64'));
  }
  await b.close();
})();
