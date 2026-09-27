// Render the reel in beat-aligned segments, then concatenate without re-encoding.
// Re-render a single segment after a tweak with:  node tools/render-final.mjs --only 3
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { ROOT } from './lib.mjs';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, arr) => {
  if (a.startsWith('--')) acc.push([a.slice(2), arr[i + 1] && !arr[i + 1].startsWith('--') ? arr[i + 1] : true]);
  return acc;
}, []));
const SEG = [[0, 5], [5, 9], [9, 12], [12, 16], [16, 19], [19, 23], [23, 27], [27, 32]];
const dir = path.join(ROOT, 'out', 'segments');
fs.mkdirSync(dir, { recursive: true });
const scale = args.scale || '1', sub = args.sub || '6', subWorld = args.subWorld || '2', crf = args.crf || '16';
const only = args.only != null ? String(args.only).split(',').map(Number) : null;
SEG.forEach(([a, b], i) => {
  if (only && !only.includes(i)) return;
  const out = path.join(dir, `seg${i}.mp4`);
  console.log(`segment ${i}: beats ${a}-${b}`);
  const r = spawnSync('node', [path.join(ROOT, 'tools', 'render.mjs'), '--scale', scale, '--sub', sub, '--subWorld', subWorld,
    '--crf', crf, '--from', String(a), '--to', String(b), '--out', out], { stdio: 'inherit' });
  if (r.status !== 0) process.exit(r.status || 1);
});
// concat (stream copy)
const list = path.join(dir, 'list.txt');
fs.writeFileSync(list, SEG.map((_, i) => `file 'seg${i}.mp4'`).join('\n') + '\n');
const ff = (() => { const g = '/usr/local/lib/python3.11/dist-packages/imageio_ffmpeg/binaries/'; if (fs.existsSync(g)) { const f = fs.readdirSync(g).find((x) => x.startsWith('ffmpeg')); if (f) return g + f; } return 'ffmpeg'; })();
const final = path.resolve(args.out || path.join(ROOT, 'out', 'point-made.mp4'));
if (SEG.every((_, i) => fs.existsSync(path.join(dir, `seg${i}.mp4`)))) {
  const r = spawnSync(ff, ['-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', list, '-c', 'copy', '-movflags', '+faststart', final], { stdio: 'inherit' });
  console.log(r.status === 0 ? `wrote ${final}` : 'concat failed');
}
