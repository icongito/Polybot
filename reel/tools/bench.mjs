// Time renderAt() for given beats:  node tools/bench.mjs --beats 12.5,16 --scale 0.5 [--dbg 3] [--sub 1]
import { openReel } from './lib.mjs';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, arr) => {
  if (a.startsWith('--')) acc.push([a.slice(2), arr[i + 1] && !arr[i + 1].startsWith('--') ? arr[i + 1] : true]);
  return acc;
}, []));
const scale = parseFloat(args.scale || '0.5');
const beats = String(args.beats || '12').split(',').map(Number);
const { page, close } = await openReel({ scale });
for (const dbg of String(args.dbg || '0').split(',').map(Number)) {
  for (const bt of beats) {
    const ms = await page.evaluate(([t, dbg, sub]) => {
      window.REEL.dbg = dbg;
      const gl = window.REEL.gl; const px = new Uint8Array(4);
      window.REEL.renderAt(t, { subframes: sub }); gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);
      const t0 = performance.now();
      window.REEL.renderAt(t, { subframes: sub }); gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);
      return performance.now() - t0;
    }, [bt * 0.46875, dbg, parseInt(args.sub || '1', 10)]);
    console.log(`dbg=${dbg} beat ${bt}: ${ms.toFixed(0)} ms`);
  }
}
await close();
