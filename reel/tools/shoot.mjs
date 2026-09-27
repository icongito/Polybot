// Render selected moments to PNG (and optionally a labelled contact sheet).
//   node tools/shoot.mjs --beats 0,0.25,1 --scale 0.5 --out /tmp/shots [--sheet] [--sub 4]
//   node tools/shoot.mjs --range 0:5:0.25   (beats, start:end:step)
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { openReel } from './lib.mjs';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, arr) => {
  if (a.startsWith('--')) acc.push([a.slice(2), arr[i + 1] && !arr[i + 1].startsWith('--') ? arr[i + 1] : true]);
  return acc;
}, []));
const scale = parseFloat(args.scale || '0.5');
const out = args.out || 'out/shots';
const sub = parseInt(args.sub || '1', 10);
let beats = [];
if (args.beats) beats = String(args.beats).split(',').map(Number);
if (args.range) { const [a, b, s] = String(args.range).split(':').map(Number); for (let x = a; x <= b + 1e-9; x += s) beats.push(+x.toFixed(4)); }
if (args.times) beats = String(args.times).split(',').map((s) => Number(s) / 0.46875);
fs.mkdirSync(out, { recursive: true });

const { page, close } = await openReel({ scale });
const files = [];
for (const bt of beats) {
  const t = bt * 0.46875;
  const t0 = Date.now();
  const url = await page.evaluate(([t, sub]) => { window.REEL.renderAt(t, { subframes: sub }); return document.getElementById('c').toDataURL('image/png'); }, [t, sub]);
  const f = path.join(out, `b${bt.toFixed(3).padStart(7, '0')}.png`);
  fs.writeFileSync(f, Buffer.from(url.split(',')[1], 'base64'));
  files.push([f, bt, t]);
  console.log(`b${bt.toFixed(3)}  t=${t.toFixed(3)}s  ${Date.now() - t0}ms  -> ${f}`);
}
await close();

if (args.sheet) {
  const cols = parseInt(args.cols || '4', 10);
  const py = `
import sys, json
from PIL import Image, ImageDraw, ImageFont
items = json.loads(sys.argv[1]); cols = int(sys.argv[2]); outp = sys.argv[3]
ims = [Image.open(f) for f,_,_ in items]
w, h = ims[0].size; tw = 640; th = int(h * tw / w)
rows = (len(ims) + cols - 1) // cols
sheet = Image.new('RGB', (cols * tw + (cols + 1) * 6, rows * (th + 22) + 6), (40, 40, 40))
d = ImageDraw.Draw(sheet)
try: font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', 13)
except: font = None
for i, (im, (f, bt, t)) in enumerate(zip(ims, items)):
    x = 6 + (i % cols) * (tw + 6); y = 6 + (i // cols) * (th + 22)
    sheet.paste(im.resize((tw, th), Image.LANCZOS), (x, y + 18))
    d.text((x, y + 2), f"beat {bt:.3f}   t={t:.3f}s   f{round(t*60)}", fill=(230, 230, 230), font=font)
sheet.save(outp)
print(outp)
`;
  const outp = path.join(out, args.name ? `${args.name}.png` : 'sheet.png');
  console.log(execFileSync('python3', ['-c', py, JSON.stringify(files), String(cols), outp]).toString());
}
