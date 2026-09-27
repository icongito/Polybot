// Inline scripts + fonts into one self-contained page.
//   dist/index.html     full standalone document (open directly, works offline)
//   dist/artifact.html  same page without the document skeleton (for hosts that add their own)
import fs from 'node:fs';
import path from 'node:path';
import { ROOT } from './lib.mjs';

const src = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
const m = src.match(/<!--REEL:SCRIPTS-->([\s\S]*?)<!--\/REEL:SCRIPTS-->/);
if (!m) throw new Error('script block markers not found');
const files = [...m[1].matchAll(/<script src="([^"]+)"><\/script>/g)].map((x) => x[1]);
const fonts = { flex: 'fonts/RobotoFlex.woff2', mono: 'fonts/GeistMono.woff2' };
const fontData = Object.fromEntries(Object.entries(fonts).map(([k, f]) => [k, fs.readFileSync(path.join(ROOT, f)).toString('base64')]));

let inline = `<script>window.REEL = window.REEL || {}; window.REEL.FONT_DATA = ${JSON.stringify(fontData)};</script>\n`;
for (const f of files) {
  const code = fs.readFileSync(path.join(ROOT, f), 'utf8');
  if (/<\/script/i.test(code)) throw new Error(`${f} contains a closing script tag`);
  inline += `<script>/* ${f} */\n${code}</script>\n`;
}
const full = src.replace(m[0], inline);
fs.mkdirSync(path.join(ROOT, 'dist'), { recursive: true });
fs.writeFileSync(path.join(ROOT, 'dist', 'index.html'), full);

// fragment: <title> + <style> + body content
const title = full.match(/<title>[\s\S]*?<\/title>/)[0];
const style = full.match(/<style>[\s\S]*?<\/style>/)[0];
const body = full.match(/<body>([\s\S]*)<\/body>/)[1];
fs.writeFileSync(path.join(ROOT, 'dist', 'artifact.html'), `${title}\n${style}\n${body}`);
const kb = (p) => (fs.statSync(path.join(ROOT, 'dist', p)).size / 1024).toFixed(0) + ' KB';
console.log('dist/index.html', kb('index.html'), ' dist/artifact.html', kb('artifact.html'));
