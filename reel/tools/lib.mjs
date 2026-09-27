// Shared helpers for the capture tools: static server + browser launch.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.woff2': 'font/woff2', '.png': 'image/png', '.json': 'application/json', '.css': 'text/css' };

export function serve(root = ROOT) {
  return new Promise((resolve) => {
    const srv = http.createServer((req, res) => {
      const p = path.join(root, decodeURIComponent(req.url.split('?')[0]));
      if (!p.startsWith(root)) { res.writeHead(403); res.end(); return; }
      fs.readFile(p, (err, data) => {
        if (err) { res.writeHead(404); res.end(); return; }
        res.writeHead(200, { 'Content-Type': TYPES[path.extname(p)] || 'application/octet-stream' });
        res.end(data);
      });
    });
    srv.listen(0, '127.0.0.1', () => resolve(srv));
  });
}

export async function loadPlaywright() {
  try { return await import('playwright'); } catch { /* fall through */ }
  return import('/opt/node22/lib/node_modules/playwright/index.mjs');
}

export async function openReel({ scale = 1, page: pageName = 'index.html' } = {}) {
  const { chromium } = await loadPlaywright();
  const srv = await serve();
  const browser = await chromium.launch({
    args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--disable-gpu-vsync'],
  });
  const page = await browser.newPage({ viewport: { width: Math.max(1920, Math.round(1920 * scale)), height: Math.max(1080, Math.round(1080 * scale)) } });
  page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') console.log('[page]', m.text().slice(0, 2000)); });
  page.on('pageerror', (e) => console.log('[pageerror]', e.message));
  await page.goto(`http://127.0.0.1:${srv.address().port}/${pageName}?capture&scale=${scale}`);
  await page.waitForFunction(() => window.__ready === true, null, { timeout: 120000 });
  return { browser, page, close: async () => { await browser.close(); srv.close(); } };
}
