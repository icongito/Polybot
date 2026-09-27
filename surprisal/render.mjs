// Renders surprisal to video: headless Chromium draws each frame of index.html?render,
// ffmpeg encodes. The soundtrack is synthesized by the page itself (OfflineAudioContext).
//
//   node render.mjs                         full film -> surprisal.mp4
//   node render.mjs --stills 1.5,12,22      PNG stills -> stills/
//   node render.mjs --audio                 soundtrack only -> audio.wav
//   options: --fps 60 --workers 4 --from 0 --to 60 --out file.mp4 --seed 1
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
let chromium;
try { ({ chromium } = require('playwright')); } catch { ({ chromium } = require('/opt/node22/lib/node_modules/playwright')); }

const ROOT = path.dirname(new URL(import.meta.url).pathname);
const args = Object.fromEntries(process.argv.slice(2).reduce((a, v, i, arr) => {
  if (v.startsWith('--')) a.push([v.slice(2), arr[i + 1] && !arr[i + 1].startsWith('--') ? arr[i + 1] : true]);
  return a;
}, []));
const FPS = +(args.fps || 60), WORKERS = +(args.workers || 4), SEED = +(args.seed || 1);
const FROM = +(args.from || 0), TO = +(args.to || 60);
const OUT = path.resolve(args.out || path.join(ROOT, 'surprisal.mp4'));
const FFMPEG = process.env.FFMPEG || 'ffmpeg';
const TMP = path.join(ROOT, '.render');

const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.woff2': 'font/woff2', '.css': 'text/css' };
const server = http.createServer((req, res) => {
  const p = path.join(ROOT, decodeURIComponent(new URL(req.url, 'http://x').pathname));
  if (!p.startsWith(ROOT) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { 'content-type': MIME[path.extname(p)] || 'application/octet-stream' });
  fs.createReadStream(p).pipe(res);
});
await new Promise(r => server.listen(0, '127.0.0.1', r));
const URL_ = `http://127.0.0.1:${server.address().port}/index.html?render&seed=${SEED}${args.mute ? '&mute=' + args.mute : ''}`;

const browser = await chromium.launch({ args: ['--autoplay-policy=no-user-gesture-required', '--disable-gpu'] });
async function openPage() {
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
  page.on('console', m => { if (m.type() === 'error') console.error('[page]', m.text()); });
  page.on('pageerror', e => console.error('[page error]', e.message));
  await page.goto(URL_);
  await page.evaluate(() => window.FILM.ready);
  return page;
}
const shot = page => page.screenshot({ type: 'png', clip: { x: 0, y: 0, width: 1920, height: 1080 } });

function run(cmd, argv, opts = {}) {
  return new Promise((res, rej) => {
    const p = spawn(cmd, argv, { stdio: [opts.stdin ? 'pipe' : 'ignore', 'ignore', 'inherit'] });
    p.on('exit', c => (c === 0 ? res() : rej(new Error(`${cmd} exited ${c}`))));
    if (opts.stdin) opts.stdin(p);
  });
}

async function renderAudio(file) {
  const page = await openPage();
  const t0 = Date.now();
  const { b64, peak } = await page.evaluate(() => window.FILM.audioWav());
  fs.writeFileSync(file, Buffer.from(b64, 'base64'));
  console.log(`audio: ${file} (raw peak ${peak.toFixed(3)}, ${((Date.now() - t0) / 1000).toFixed(1)}s)`);
  await page.close();
}

try {
  if (args.stills) {
    const dir = path.join(ROOT, 'stills'); fs.mkdirSync(dir, { recursive: true });
    const page = await openPage();
    for (const t of String(args.stills).split(',').map(Number)) {
      await page.evaluate(t => window.FILM.draw(t), t);
      const f = path.join(dir, `t${t.toFixed(2).padStart(5, '0')}.png`);
      fs.writeFileSync(f, await shot(page));
      console.log(f);
    }
  } else if (args.audio) {
    await renderAudio(path.resolve(ROOT, args.wav || 'audio.wav'));
  } else {
    fs.mkdirSync(TMP, { recursive: true });
    const audio = path.join(TMP, 'audio.wav');
    const audioP = renderAudio(audio);
    const f0 = Math.round(FROM * FPS), f1 = Math.round(TO * FPS);
    const per = Math.ceil((f1 - f0) / WORKERS);
    const started = Date.now();
    let done = 0;
    const segs = [];
    await Promise.all(Array.from({ length: WORKERS }, async (_, w) => {
      const a = f0 + w * per, b = Math.min(f1, a + per);
      if (a >= b) return;
      const seg = path.join(TMP, `seg${w}.mp4`); segs[w] = seg;
      const page = await openPage();
      await run(FFMPEG, ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'png', '-i', '-',
        '-c:v', 'libx264', '-preset', 'slow', '-crf', '23', '-pix_fmt', 'yuv420p', '-g', String(FPS * 2), seg], {
        stdin: async p => {
          for (let i = a; i < b; i++) {
            await page.evaluate(t => window.FILM.draw(t), i / FPS);
            const buf = await shot(page);
            if (!p.stdin.write(buf)) await new Promise(r => p.stdin.once('drain', r));
            if (++done % 120 === 0) {
              const el = (Date.now() - started) / 1000;
              console.log(`${done}/${f1 - f0} frames  ${el.toFixed(0)}s elapsed, ~${(el / done * (f1 - f0 - done)).toFixed(0)}s left`);
            }
          }
          p.stdin.end();
        },
      });
      await page.close();
    }));
    await audioP;
    const list = path.join(TMP, 'list.txt');
    fs.writeFileSync(list, segs.filter(Boolean).map(s => `file '${s}'`).join('\n'));
    await run(FFMPEG, ['-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', list, '-ss', String(FROM), '-t', String(TO - FROM), '-i', audio,
      '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '256k', '-shortest', '-movflags', '+faststart', OUT]);
    await run(FFMPEG, ['-y', '-loglevel', 'error', '-i', audio, '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', path.join(ROOT, 'soundtrack.m4a')]);
    console.log(`wrote ${OUT} in ${((Date.now() - started) / 1000).toFixed(0)}s`);
  }
} finally {
  await browser.close();
  server.close();
}
