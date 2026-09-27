// Render the reel to video: headless Chromium draws each frame deterministically,
// raw RGBA frames are piped straight into ffmpeg (H.264, yuv420p, faststart).
//   node tools/render.mjs --scale 1 --sub 6 --out out/reel.mp4
//   node tools/render.mjs --scale 0.5 --sub 1 --out /tmp/preview.mp4 --from 9 --to 23   (beats)
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { openReel, ROOT } from './lib.mjs';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, arr) => {
  if (a.startsWith('--')) acc.push([a.slice(2), arr[i + 1] && !arr[i + 1].startsWith('--') ? arr[i + 1] : true]);
  return acc;
}, []));
const scale = parseFloat(args.scale || '1');
const fps = parseInt(args.fps || '60', 10);
const sub = parseInt(args.sub || '1', 10);
const subWorld = parseInt(args.subWorld || args.sub || '1', 10);   // raymarched chapters may use fewer
const subFast = parseInt(args.subFast || args.subWorld || args.sub || '1', 10); // ...except during fast moves
const out = path.resolve(args.out || path.join(ROOT, 'out', 'reel.mp4'));
const BEAT = 60 / 128;
const f0 = args.from ? Math.round(parseFloat(args.from) * BEAT * fps) : 0;
const f1 = args.to ? Math.round(parseFloat(args.to) * BEAT * fps) : Math.round(15 * fps);
const crf = args.crf || '14';

function ffmpegPath() {
  if (process.env.FFMPEG) return process.env.FFMPEG;
  for (const p of ['/usr/bin/ffmpeg', '/usr/local/bin/ffmpeg']) if (fs.existsSync(p)) return p;
  const g = '/usr/local/lib/python3.11/dist-packages/imageio_ffmpeg/binaries/';
  if (fs.existsSync(g)) { const f = fs.readdirSync(g).find((x) => x.startsWith('ffmpeg')); if (f) return g + f; }
  return 'ffmpeg';
}

const W = Math.round(1920 * scale), H = Math.round(1080 * scale);
fs.mkdirSync(path.dirname(out), { recursive: true });
const ff = spawn(ffmpegPath(), [
  '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', `${W}x${H}`, '-r', String(fps), '-i', '-',
  '-vf', 'vflip', '-c:v', 'libx264', '-preset', args.preset || 'slow', '-crf', crf, '-tune', 'film',
  '-pix_fmt', 'yuv420p', '-movflags', '+faststart', out,
], { stdio: ['pipe', 'inherit', 'inherit'] });

const { page, close } = await openReel({ scale });
const t0 = Date.now();
for (let f = f0; f < f1; f++) {
  const t = f / fps;
  const b64 = await page.evaluate(([t, sub, subWorld, subFast]) => {
    const R = window.REEL, gl = R.gl;
    const n = R.subframeHint(t, sub, subWorld, subFast);
    R.renderAt(t, { subframes: n, shutter: 0.5 });
    const w = gl.drawingBufferWidth, h = gl.drawingBufferHeight;
    const px = new Uint8Array(w * h * 4);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, px);
    let s = '';
    const CH = 0x8000;
    for (let i = 0; i < px.length; i += CH) s += String.fromCharCode.apply(null, px.subarray(i, i + CH));
    return btoa(s);
  }, [t, sub, subWorld, subFast]);
  const buf = Buffer.from(b64, 'base64');
  if (!ff.stdin.write(buf)) await new Promise((r) => ff.stdin.once('drain', r));
  const done = f - f0 + 1, total = f1 - f0;
  if (done % 30 === 0 || done === total) {
    const el = (Date.now() - t0) / 1000;
    console.log(`frame ${f} (${done}/${total})  ${el.toFixed(0)}s elapsed, ~${((el / done) * (total - done)).toFixed(0)}s left`);
  }
}
ff.stdin.end();
await new Promise((r) => ff.on('close', r));
await close();
console.log('wrote', out);
