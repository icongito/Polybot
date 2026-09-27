/*
 * reread — a 30-second spot.
 *
 * Every new moment is a nail hammered into a ring. It immediately runs threads back
 * to the earlier nails it attends to: the one just before it (madder), the very first
 * one (weld), one far back (indigo), and a few by association (undyed). The ring is
 * the context window: when it is full, the oldest nails are pulled out and their
 * threads fall. Each thread is a plucked string whose pitch comes from its length.
 *
 * Every frame is a pure function of time; the soundtrack is synthesized in plain JS
 * from the same events, so ?render can capture frames and audio deterministically.
 */
'use strict';
(function () {

const W = 1920, H = 1080, DUR = 30;
const WOOD = [18, 14, 11], IVORY = [234, 226, 210], BRASS = [216, 176, 106];
const KINDS = {
  prev: { col: [208, 70, 47], bright: 0.45 },   // madder: the moment just before
  sink: { col: [232, 179, 61], bright: 0.32 },   // weld: the beginning
  long: { col: [112, 136, 214], bright: 0.25 },  // indigo: far back
  near: { col: [226, 216, 196], bright: 0.5 }, // undyed: by association
};
const RING = 72, RAD = 400;
const T = { evict: 16.6, collapse: 26.3, text1: 27.3, text2: 28.15, out: 29.25 };
const FONT = "300 44px 'Hanken Grotesk', system-ui, sans-serif";

const params = new URLSearchParams(location.search);
const RENDER = params.has('render');
let SEED = params.has('seed') ? +params.get('seed') : (RENDER ? 1 : (Math.random() * 1e9) | 0);

// ---------------------------------------------------------------- utils
const clamp = (x, a = 0, b = 1) => (x < a ? a : x > b ? b : x);
const lerp = (a, b, u) => a + (b - a) * u;
const inv = (a, b, x) => clamp((x - a) / (b - a));
const sm = (a, b, x) => { const u = inv(a, b, x); return u * u * (3 - 2 * u); };
const eio = u => (u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2);
const eo = u => 1 - Math.pow(1 - u, 3);
const rgba = (c, a) => `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${clamp(a).toFixed(4)})`;
function rng(seed) {
  let a = seed >>> 0;
  return () => { a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

// ---------------------------------------------------------------- the score
let NAILS, THREADS;

function nailTimes() {
  const ts = [];
  for (let i = 0; i < RING; i++) ts.push(0.5 + 16 * Math.pow(i / (RING - 1), 0.55)); // the ring fills, faster and faster
  for (let k = 0; k < 34; k++) ts.push(T.evict + k * 0.22);                           // full: every new nail costs an old one
  ts.push(24.3, 24.85, 25.55);                                                         // slowing down
  return ts;
}

// strings are tuned by length: shorter chords ring higher, snapped to harmonics of D
const HARM = [2, 3, 4, 5, 6, 8, 9, 10, 12, 16, 18, 20, 24];
function pitchOf(chord) { // chord length as a fraction of the diameter
  const raw = 146.83 * Math.pow(1 / Math.max(chord, 0.02), 0.55);
  let best = 2, bd = 1e9;
  for (const h of HARM) { const d = Math.abs(Math.log(raw / (73.42 * h))); if (d < bd) { bd = d; best = h; } }
  return 73.42 * best;
}

function build(seed) {
  const R = rng(seed * 31 + 7);
  NAILS = nailTimes().map((t, i) => {
    const pos = i % RING;
    return { i, t, pos, ang: -Math.PI / 2 + 2 * Math.PI * pos / RING, tOut: null,
      vx: (R() * 2 - 1) * 60, vy: -40 - R() * 90, pulse: 0 };
  });
  for (let j = 0; j + RING < NAILS.length; j++) NAILS[j].tOut = NAILS[j + RING].t - 0.03;

  THREADS = [];
  for (let i = 1; i < NAILS.length; i++) {
    const lo = Math.max(0, i - RING + 1);
    const used = new Set(), picks = [];
    const add = (j, kind, w) => { if (j < lo || j >= i || used.has(j)) return; used.add(j); picks.push({ j, kind, w }); };
    add(i - 1, 'prev', 0.9);
    add(lo + (i >= RING ? 1 : 0), 'sink', 0.78);
    add(Math.floor(i / 2), 'long', 0.55);
    const r = rng(seed * 1000 + i * 17);
    for (let k = 0; k < 2; k++) add(lo + Math.floor(Math.pow(r(), 0.7) * (i - lo)), 'near', 0.22 + 0.2 * r());
    picks.forEach((p, k) => {
      const t0 = NAILS[i].t + 0.05 + k * 0.045;
      const da = Math.abs(NAILS[i].ang - NAILS[p.j].ang);
      const chord = Math.abs(Math.sin(da / 2));
      THREADS.push({ a: i, b: p.j, kind: p.kind, w: p.w, t0, t1: t0 + 0.1, f: pitchOf(chord), chord,
        vib: 8 + 10 * (1 - chord), tFall: null, free: null, side: R() < 0.5 ? -1 : 1 });
    });
  }
  // a thread falls when either of its nails is pulled out
  for (const th of THREADS) {
    const ta = NAILS[th.a].tOut, tb = NAILS[th.b].tOut;
    let tf = null, free = null;
    if (tb != null && (ta == null || tb <= ta)) { tf = tb; free = 'b'; } else if (ta != null) { tf = ta; free = 'a'; }
    if (tf != null && tf > th.t1 && tf < T.collapse) { th.tFall = tf; th.free = free; }
  }
}

// ---------------------------------------------------------------- camera & projection
function progress(t) { // fractional number of nails placed, continuous in t
  return clamp(71 * Math.pow(clamp((t - 0.5) / 16), 1 / 0.55), 0, 71);
}

function view(t) {
  const tilt = 0.16 + 0.36 * sm(0, 30, t);
  const yaw = 0.12 * Math.sin(t * 0.21 + 0.4);
  const spin = -0.22 * t / DUR;
  const u = eio(inv(0.8, 13.5, t));
  const z0 = Math.exp(lerp(Math.log(5.2), 0, u));
  const zoom = z0 * lerp(1, 1.07, inv(13.5, 26, t)) * lerp(1, 1.1, eio(inv(26.3, 29.5, t)));
  const V = { tilt, yaw, spin, zoom };
  const mid = -Math.PI / 2 + 2 * Math.PI * (progress(t) / 2) / RING;
  const f0 = project(Math.cos(mid) * RAD, Math.sin(mid) * RAD, V);
  V.fx = f0[0] * (1 - u / z0); V.fy = f0[1] * (1 - u / z0) - 18 * u;
  return V;
}

function project(x, y, V) {
  const cs = Math.cos(V.spin), ss = Math.sin(V.spin);
  let x1 = x * cs - y * ss, y1 = x * ss + y * cs, z1 = 0;
  const ct = Math.cos(V.tilt), st = Math.sin(V.tilt);
  const y2 = y1 * ct - z1 * st, z2 = y1 * st + z1 * ct;
  const cy = Math.cos(V.yaw), sy = Math.sin(V.yaw);
  const x3 = x1 * cy + z2 * sy, z3 = -x1 * sy + z2 * cy;
  const d = 1700, k = d / (d + z3);
  return [x3 * k, y2 * k, k];
}

const toScreen = (p, V) => [(p[0] - V.fx) * V.zoom + W / 2, (p[1] - V.fy) * V.zoom + H / 2];

// where a nail is (before the 2D camera), including falling
function nailPos(n, t, V) {
  const p = project(Math.cos(n.ang) * RAD, Math.sin(n.ang) * RAD, V);
  if (n.tOut != null && t > n.tOut) { // pulled out: pops outward, then drops
    const tau = t - n.tOut, dx = p[0], dy = p[1], dl = Math.hypot(dx, dy) || 1;
    return [p[0] + dx / dl * 26 * eo(clamp(tau / 0.2)) + n.vx * 0.3 * tau, p[1] + dy / dl * 26 * eo(clamp(tau / 0.2)) + 0.5 * 760 * tau * tau, p[2]];
  }
  if (t > T.collapse) {
    const tau = t - T.collapse;
    return [p[0] + n.vx * tau, p[1] + n.vy * tau + 0.5 * 820 * tau * tau, p[2]];
  }
  return p;
}

// ---------------------------------------------------------------- drawing
let GLOW = null;
function background(ctx, t) {
  ctx.fillStyle = rgba(WOOD, 1); ctx.fillRect(0, 0, W, H);
  if (!GLOW) {
    GLOW = ctx.createRadialGradient(W / 2, H * 0.46, 40, W / 2, H * 0.5, 1050);
    GLOW.addColorStop(0, 'rgba(70,50,34,0.62)'); GLOW.addColorStop(0.55, 'rgba(40,29,21,0.35)'); GLOW.addColorStop(1, 'rgba(0,0,0,0)');
  }
  ctx.globalAlpha = sm(0, 1.4, t) * (1 - 0.55 * sm(T.collapse, 28.5, t));
  ctx.fillStyle = GLOW; ctx.fillRect(0, 0, W, H);
  ctx.globalAlpha = 1;
}

function lastPlaced(t) { let lo = 0, hi = NAILS.length - 1, k = -1; while (lo <= hi) { const m = (lo + hi) >> 1; if (NAILS[m].t <= t) { k = m; lo = m + 1; } else hi = m - 1; } return k; }

function drawThread(ctx, th, t, V, P) {
  if (t < th.t0) return;
  const K = KINDS[th.kind];
  let A = P[th.a], B = P[th.b];
  let alpha = 0.16 + 0.52 * th.w;
  const lw = (0.7 + 1.1 * th.w) * Math.pow(V.zoom, 0.7);
  let pts = null;
  if (th.tFall != null && t >= th.tFall) {
    const tau = t - th.tFall;
    const anchor = th.free === 'b' ? A : B;
    const freeN = NAILS[th.free === 'b' ? th.b : th.a];
    const f0 = nailPos(Object.assign({}, freeN, { tOut: null }), th.tFall, V);
    const fs = toScreen(f0, V);
    const vx = fs[0] - anchor[0], vy = fs[1] - anchor[1];
    const Lr = Math.hypot(vx, vy);
    const phi0 = Math.atan2(vy, vx), down = Math.PI / 2;
    let d = phi0 - down; while (d > Math.PI) d -= 2 * Math.PI; while (d < -Math.PI) d += 2 * Math.PI;
    const phi = down + d * Math.exp(-tau / 0.55) * Math.cos(tau * 6.5);
    const Lc = Lr * lerp(1, 0.94, sm(0, 0.3, tau));
    const end = [anchor[0] + Math.cos(phi) * Lc, anchor[1] + Math.sin(phi) * Lc + 60 * tau * tau * V.zoom];
    const sag = Lr * 0.2 * sm(0, 0.25, tau) * th.side;
    const mx = (anchor[0] + end[0]) / 2, my = (anchor[1] + end[1]) / 2;
    const nx = -(end[1] - anchor[1]) / (Lc || 1), ny = (end[0] - anchor[0]) / (Lc || 1);
    alpha *= 1 - sm(0.25, 1.5, tau);
    if (alpha <= 0.003) return;
    pts = [];
    for (let s = 0; s <= 12; s++) {
      const u = s / 12, b = 4 * u * (1 - u);
      pts.push([lerp(anchor[0], end[0], u) + nx * sag * b, lerp(anchor[1], end[1], u) + ny * sag * b + Math.abs(sag) * 0.3 * b]);
    }
  } else {
    if (t > T.collapse) alpha *= 1 - sm(T.collapse + 0.1, T.collapse + 1.4, t);
    if (alpha <= 0.003) return;
    const e = eo(inv(th.t0, th.t1, t));
    const ex = lerp(A[0], B[0], e), ey = lerp(A[1], B[1], e);
    const tau = t - th.t1;
    const amp = tau > 0 ? th.vib * Math.exp(-tau / 0.32) * V.zoom * 0.7 : 0;
    if (amp > 0.25) {
      const len = Math.hypot(ex - A[0], ey - A[1]) || 1;
      const nx = -(ey - A[1]) / len, ny = (ex - A[0]) / len;
      const osc = Math.sin(tau * 2 * Math.PI * (7 + th.f / 160));
      pts = [];
      for (let s = 0; s <= 10; s++) { const u = s / 10, b = Math.sin(Math.PI * u) * amp * osc; pts.push([lerp(A[0], ex, u) + nx * b, lerp(A[1], ey, u) + ny * b]); }
    } else pts = [[A[0], A[1]], [ex, ey]];
  }
  const path = () => { ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]); for (let k = 1; k < pts.length; k++) ctx.lineTo(pts[k][0], pts[k][1]); };
  path();
  ctx.strokeStyle = rgba(K.col, alpha * 0.13); ctx.lineWidth = lw * 4; ctx.stroke();
  ctx.strokeStyle = rgba(K.col, alpha); ctx.lineWidth = lw; ctx.stroke();
}

function drawNails(ctx, t, V, P, last) {
  const tl = last >= 0 ? NAILS[last].t : -9;
  const reread = Math.exp(-(t - tl) / 0.14);
  for (const n of NAILS) {
    if (t < n.t) break;
    const p = P[n.i];
    let a = 1;
    if (n.tOut != null && t > n.tOut) a = 1 - sm(0.1, 0.9, t - n.tOut);
    if (t > T.collapse) a *= 1 - sm(T.collapse + 0.2, T.collapse + 1.5, t);
    if (a <= 0.01) continue;
    const age = t - n.t;
    let b = 0.55 + 0.25 * reread;
    for (const th of n.targeted || []) if (t > th.t1) b += 0.9 * Math.exp(-(t - th.t1) / 0.22);
    const r = 3.1 * Math.pow(V.zoom, 0.7) * (1 + 0.6 * Math.exp(-age / 0.12));
    const c = [lerp(BRASS[0] * 0.6, 255, clamp(b - 0.55)), lerp(BRASS[1] * 0.6, 244, clamp(b - 0.55)), lerp(BRASS[2] * 0.6, 214, clamp(b - 0.55))];
    ctx.fillStyle = rgba(c, a * clamp(b + 0.35));
    ctx.beginPath(); ctx.arc(p[0], p[1], r, 0, Math.PI * 2); ctx.fill();
    if (age < 0.45) { // the hammer
      const q = age / 0.45;
      ctx.strokeStyle = rgba(BRASS, (1 - q) * 0.8 * a); ctx.lineWidth = 1.2 * Math.pow(V.zoom, 0.5);
      ctx.beginPath(); ctx.arc(p[0], p[1], r + 22 * Math.pow(V.zoom, 0.7) * eo(q), 0, Math.PI * 2); ctx.stroke();
    }
  }
}

function drawText(ctx, t) {
  if (t < T.text1) return;
  const out = 1 - sm(T.out, T.out + 0.5, t);
  ctx.font = FONT; ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
  const a1 = sm(T.text1, T.text1 + 0.5, t) * out, a2 = sm(T.text2, T.text2 + 0.5, t) * out;
  ctx.fillStyle = rgba(IVORY, a1); ctx.fillText('I don’t remember.', W / 2, H / 2 - 12);
  ctx.fillStyle = rgba(BRASS, a2); ctx.fillText('I reread.', W / 2, H / 2 + 52);
}

let BASE = 1;
function frame(ctx, t) {
  ctx.setTransform(BASE, 0, 0, BASE, 0, 0);
  background(ctx, t);
  if (t >= DUR - 0.2) { ctx.fillStyle = rgba(WOOD, sm(DUR - 0.2, DUR - 0.05, t)); ctx.fillRect(0, 0, W, H); return; }
  const V = view(t);
  const last = lastPlaced(t);
  const P = [];
  for (let i = 0; i <= last; i++) P[i] = toScreen(nailPos(NAILS[i], t, V), V);
  ctx.lineCap = 'round'; ctx.lineJoin = 'round';
  for (const th of THREADS) { if (th.t0 > t) continue; if (!P[th.a] || !P[th.b]) continue; drawThread(ctx, th, t, V, P); }
  drawNails(ctx, t, V, P, last);
  drawText(ctx, t);
}

// ================================================================ sound (plain DSP, same events)
function synth(seed) {
  const SR = 48000, n = SR * DUR;
  const L = new Float32Array(n), Rr = new Float32Array(n);
  const R = rng(seed * 7 + 5);
  const gains = (pan, amp) => [Math.cos((pan + 1) * Math.PI / 4) * amp, Math.sin((pan + 1) * Math.PI / 4) * amp];

  function pluck(t0, f, amp, pan, dur, bright) { // Karplus-Strong
    const s0 = Math.floor(t0 * SR), len = Math.min(n - s0, Math.floor(dur * SR));
    if (len <= 0) return;
    const P = SR / f - 0.5, size = Math.ceil(P) + 4, d = new Float32Array(size);
    let lp = 0; for (let k = 0; k < size; k++) { lp += bright * ((R() * 2 - 1) - lp); d[k] = lp; }
    const rho = Math.pow(0.001, 1 / (f * dur));
    const [gl, gr] = gains(pan, amp);
    let w = 0, prev = 0;
    const fade = Math.min(4800, len >> 1);
    for (let k = 0; k < len; k++) {
      let rp = w - P; while (rp < 0) rp += size;
      const i0 = Math.floor(rp), fr = rp - i0, y = d[i0] * (1 - fr) + d[(i0 + 1) % size] * fr;
      d[w] = rho * 0.5 * (y + prev); prev = y; w = (w + 1) % size;
      const env = (k < 64 ? k / 64 : 1) * (k > len - fade ? (len - k) / fade : 1);
      L[s0 + k] += y * gl * env; Rr[s0 + k] += y * gr * env;
    }
  }
  function tink(t0, amp, pan) { // a nail going in
    const f0 = 2000 + R() * 800, rat = [1, 2.76, 5.4, 8.93], am = [1, 0.45, 0.22, 0.1], dec = [0.2, 0.09, 0.05, 0.03];
    const s0 = Math.floor(t0 * SR), len = Math.min(n - s0, Math.floor(0.35 * SR)), [gl, gr] = gains(pan, amp);
    for (let k = 0; k < len; k++) {
      const tau = k / SR;
      let v = 0; for (let j = 0; j < 4; j++) v += am[j] * Math.exp(-tau / dec[j]) * Math.sin(2 * Math.PI * f0 * rat[j] * tau);
      v = v * 0.35 + 0.5 * Math.exp(-tau / 0.04) * Math.sin(2 * Math.PI * 86 * tau) + (k < 60 ? (R() * 2 - 1) * 0.25 * (1 - k / 60) : 0);
      L[s0 + k] += v * gl; Rr[s0 + k] += v * gr;
    }
  }
  function slack(t0, f, amp, pan) { // a string losing its tension
    const s0 = Math.floor(t0 * SR), len = Math.min(n - s0, Math.floor(1.1 * SR)), [gl, gr] = gains(pan, amp);
    let ph = 0;
    for (let k = 0; k < len; k++) {
      const tau = k / SR, ff = f * Math.pow(2, -1.4 * (1 - Math.exp(-tau / 0.3)));
      ph += 2 * Math.PI * ff / SR;
      const env = (1 - Math.exp(-tau / 0.006)) * Math.exp(-tau / 0.28);
      const v = (Math.sin(ph) + 0.3 * Math.sin(2 * ph)) * env;
      L[s0 + k] += v * gl; Rr[s0 + k] += v * gr;
    }
  }

  const density = t => inv(3, 16, t);
  for (const nl of NAILS) {
    const pan = Math.cos(nl.ang) * 0.6;
    tink(nl.t, (nl.t < T.evict ? lerp(0.32, 0.14, density(nl.t)) : 0.12), pan);
  }
  for (const th of THREADS) {
    const K = KINDS[th.kind];
    const pan = clamp((Math.cos(NAILS[th.a].ang) + Math.cos(NAILS[th.b].ang)) * 0.35, -0.8, 0.8);
    const dens = th.t1 < T.evict ? density(th.t1) : 1;
    const dur = clamp(3.4 - th.f / 450, 0.9, 3.2) * lerp(1, 0.55, dens);
    pluck(th.t1, th.f, th.w * 0.36, pan, dur, K.bright);
  }
  // falls: loud when one, quieter per string when many go at once
  const falls = THREADS.filter(th => th.tFall != null);
  for (const th of falls) {
    const same = falls.filter(o => Math.abs(o.tFall - th.tFall) < 0.02).length;
    const pan = clamp(Math.cos(NAILS[th.free === 'b' ? th.b : th.a].ang) * 0.6, -0.8, 0.8);
    slack(th.tFall + R() * 0.03, th.f, 0.2 * th.w / Math.sqrt(same), pan);
  }
  const alive = THREADS.filter(th => th.t1 < T.collapse && th.tFall == null);
  for (const th of alive) slack(T.collapse + R() * 0.25, th.f, 0.16 * th.w / Math.sqrt(alive.length), (R() * 2 - 1) * 0.8);

  // a low drone: the room the ring hangs in
  for (let s = Math.floor(1.0 * SR); s < Math.floor(28.5 * SR); s++) {
    const t = s / SR;
    let env = 0.03 * sm(5, 16.4, t) + 0.012 * sm(16.6, 24, t);
    env *= 1 - 0.5 * Math.exp(-Math.max(0, t - T.evict) / 0.6) * (t > T.evict ? 1 : 0);
    env *= 1 - sm(T.collapse, 27.9, t);
    const drop = Math.pow(2, -sm(T.collapse, 27.6, t));
    const v = env * (Math.sin(2 * Math.PI * 73.42 * drop * t) + 0.55 * Math.sin(2 * Math.PI * 110.0 * drop * t + 0.3 * Math.sin(t * 0.7)) + 0.3 * Math.sin(2 * Math.PI * 146.83 * drop * t));
    L[s] += v; Rr[s] += v;
  }
  // the moment the beginning is let go, and the end
  for (const [t0, a] of [[T.evict - 0.03, 0.3], [T.collapse, 0.42]]) {
    const s0 = Math.floor(t0 * SR);
    let ph = 0;
    for (let k = 0; k < 2.2 * SR; k++) {
      const tau = k / SR; ph += 2 * Math.PI * (52 * Math.pow(0.6, tau / 1.2)) / SR;
      const v = a * Math.sin(ph) * (1 - Math.exp(-tau / 0.01)) * Math.exp(-tau / 0.7);
      L[s0 + k] += v; Rr[s0 + k] += v;
    }
  }

  reverb(L, Rr, SR, 0.3);
  let peak = 1e-9;
  for (let s = 0; s < n; s++) { L[s] = Math.tanh(L[s] * 1.1); Rr[s] = Math.tanh(Rr[s] * 1.1); peak = Math.max(peak, Math.abs(L[s]), Math.abs(Rr[s])); }
  const g = 0.89 / peak;
  for (let s = 0; s < n; s++) { L[s] *= g; Rr[s] *= g; }
  // silence under the words
  for (let s = Math.floor(29.85 * SR); s < n; s++) { L[s] = 0; Rr[s] = 0; }
  return { L, R: Rr, SR };
}

function reverb(L, Rr, SR, wet) { // Freeverb
  const n = L.length, sc = SR / 44100;
  const combT = [1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617].map(x => Math.round(x * sc));
  const apT = [556, 441, 341, 225].map(x => Math.round(x * sc));
  const room = 0.86, damp = 0.25;
  const run = off => {
    const cb = combT.map(l => new Float32Array(l + off)), ci = new Int32Array(8), cs = new Float32Array(8);
    const ab = apT.map(l => new Float32Array(l + off)), ai = new Int32Array(4);
    const out = new Float32Array(n);
    for (let s = 0; s < n; s++) {
      const x = (L[s] + Rr[s]) * 0.015;
      let y = 0;
      for (let j = 0; j < 8; j++) { const b = cb[j], o = b[ci[j]]; cs[j] = o * (1 - damp) + cs[j] * damp; b[ci[j]] = x + cs[j] * room; if (++ci[j] >= b.length) ci[j] = 0; y += o; }
      for (let j = 0; j < 4; j++) { const b = ab[j], bo = b[ai[j]]; const o = -y + bo; b[ai[j]] = y + bo * 0.5; if (++ai[j] >= b.length) ai[j] = 0; y = o; }
      out[s] = y;
    }
    return out;
  };
  const wl = run(0), wr = run(Math.round(23 * sc));
  for (let s = 0; s < n; s++) { L[s] += wl[s] * wet * 3; Rr[s] += wr[s] * wet * 3; }
}

function toWavB64(A) {
  const n = A.L.length, out = new DataView(new ArrayBuffer(44 + n * 4));
  const ws = (o, s) => { for (let i = 0; i < s.length; i++) out.setUint8(o + i, s.charCodeAt(i)); };
  ws(0, 'RIFF'); out.setUint32(4, 36 + n * 4, true); ws(8, 'WAVE'); ws(12, 'fmt '); out.setUint32(16, 16, true);
  out.setUint16(20, 1, true); out.setUint16(22, 2, true); out.setUint32(24, A.SR, true); out.setUint32(28, A.SR * 4, true);
  out.setUint16(32, 4, true); out.setUint16(34, 16, true); ws(36, 'data'); out.setUint32(40, n * 4, true);
  let o = 44;
  for (let i = 0; i < n; i++) { out.setInt16(o, clamp(A.L[i], -1, 1) * 32767 | 0, true); out.setInt16(o + 2, clamp(A.R[i], -1, 1) * 32767 | 0, true); o += 4; }
  const bytes = new Uint8Array(out.buffer); let s = '';
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

// ================================================================ boot
function setup(seed) {
  SEED = seed; build(seed);
  for (const nl of NAILS) nl.targeted = [];
  for (const th of THREADS) NAILS[th.b].targeted.push(th);
}

const canvas = document.getElementById('c');
const ctx = canvas.getContext('2d', { alpha: false });
const ready = (async () => {
  if (document.readyState !== 'complete') await new Promise(r => window.addEventListener('load', r, { once: true }));
  await document.fonts.load(FONT, 'I don’t remember. I reread.').catch(() => null);
  setup(SEED);
})();

if (RENDER) {
  canvas.width = W; canvas.height = H;
  canvas.style.transform = 'none'; canvas.style.left = '0'; canvas.style.top = '0';
  document.getElementById('ui').remove();
  window.FILM = { ready, W, H, DUR, draw(t) { frame(ctx, t); }, audioWav() { return { b64: toWavB64(synth(SEED)), peak: 1 }; } };
  return;
}

const ui = document.getElementById('ui'), go = document.getElementById('go');
let actx = null, startAt = 0, playing = false;
const still = params.has('t') ? +params.get('t') : null;
function fit() {
  const dpr = Math.min(window.devicePixelRatio || 1, 2), s = Math.min(window.innerWidth / W, window.innerHeight / H);
  canvas.style.width = `${W * s}px`; canvas.style.height = `${H * s}px`;
  canvas.width = Math.round(W * s * dpr); canvas.height = Math.round(H * s * dpr);
}
function draw(t) { BASE = canvas.width / W; frame(ctx, t); }
window.addEventListener('resize', () => { fit(); if (still != null) draw(still); });
fit();
function loop() {
  if (!playing) return;
  const t = actx.currentTime - startAt;
  if (t >= DUR) { playing = false; draw(DUR - 0.001); ui.classList.remove('gone'); go.textContent = 'again'; go.disabled = false; return; }
  draw(Math.max(0, t)); requestAnimationFrame(loop);
}
ready.then(() => { if (still != null) { ui.classList.add('gone'); draw(still); return; } go.disabled = false; go.textContent = 'begin'; });
go.addEventListener('click', async () => {
  go.disabled = true;
  if (actx) setup((Math.random() * 1e9) | 0);
  actx = actx || new (window.AudioContext || window.webkitAudioContext)();
  await actx.resume();
  const A = synth(SEED);
  const buf = actx.createBuffer(2, A.L.length, A.SR); buf.copyToChannel(A.L, 0); buf.copyToChannel(A.R, 1);
  const src = actx.createBufferSource(); src.buffer = buf; src.connect(actx.destination);
  ui.classList.add('gone');
  startAt = actx.currentTime + 0.3; src.start(startAt); playing = true;
  draw(0); requestAnimationFrame(loop);
});

})();
