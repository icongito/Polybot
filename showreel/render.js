// Renders reel.html frame-by-frame (4 parallel pages) and pipes JPEG frames into ffmpeg in order.
// usage: node render.js ffmpegPath out_video.mp4 [fps]
const { chromium } = require('/opt/node22/lib/node_modules/playwright');
const { spawn } = require('child_process'), path = require('path');
const [FF, OUT, FPSarg] = process.argv.slice(2); const FPS = +(FPSarg || 60), TOTAL = 30 * FPS, WORKERS = 4;
(async () => {
  const ff = spawn(FF, ['-y', '-hide_banner', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'mjpeg', '-i', '-',
    '-c:v', 'libx264', '-preset', 'slow', '-crf', '12', '-pix_fmt', 'yuv420p', OUT], { stdio: ['pipe', 'inherit', 'inherit'] });
  const b = await chromium.launch();
  const pages = await Promise.all([...Array(WORKERS)].map(async () => { const p = await b.newPage({ viewport: { width: 1920, height: 1080 } });
    p.on('pageerror', e => console.log('pageerror', e.message)); await p.goto('file://' + path.join(__dirname, 'reel.html')); await p.evaluate(() => window.ready); return p; }));
  const done = new Map(); let next = 0, claimed = 0; const t0 = Date.now();
  const flush = async () => { while (done.has(next)) { const buf = done.get(next); done.delete(next); if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r)); next++;
    if (next % 150 === 0) console.log(`${next}/${TOTAL} frames, ${((Date.now() - t0) / 1000).toFixed(0)}s`); } };
  await Promise.all(pages.map(async p => { while (true) { const i = claimed++; if (i >= TOTAL) break;
    while (i - next > 240) await new Promise(r => setTimeout(r, 20));
    const url = await p.evaluate(t => { render(t); return document.getElementById('c').toDataURL('image/jpeg', 0.96); }, i / FPS);
    done.set(i, Buffer.from(url.split(',')[1], 'base64')); await flush(); } }));
  await flush(); ff.stdin.end(); await new Promise(r => ff.on('close', r)); await b.close();
  console.log('done', ((Date.now() - t0) / 1000).toFixed(0) + 's');
})();
