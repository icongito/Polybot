// Soundtrack synthesizer, A minor. The score is written in 120 BPM "score seconds" (30s);
// TS stretches event timing to 96 BPM / 37.5s while envelopes keep their natural length.
// usage: node synth.js out.wav
const fs = require('fs');
const TS = 1.25, SR = 48000, DUR = 30, N = Math.round(SR * DUR * TS), BEAT = 0.5;
const L = new Float32Array(N), R = new Float32Array(N);
const padL = new Float32Array(N), padR = new Float32Array(N);
const revS = new Float32Array(N), dlyS = new Float32Array(N);
const mtof = m => 440 * Math.pow(2, (m - 69) / 12);
let seed = 12345; const noise = () => { seed = (seed * 16807) % 2147483647; return seed / 1073741823.5 - 1; };
const idx = t => Math.round(t * TS * SR);
function out(i, v, pan = 0, rv = 0, dl = 0) {
  if (i < 0 || i >= N) return;
  const a = (pan + 1) * Math.PI / 4; L[i] += v * Math.cos(a); R[i] += v * Math.sin(a);
  if (rv) revS[i] += v * rv; if (dl) dlyS[i] += v * dl;
}
function svf() { let ic1 = 0, ic2 = 0; return (x, fc, Q, mode) => {
  const g = Math.tan(Math.PI * Math.min(Math.max(fc, 20), SR * 0.45) / SR), k = 1 / Q;
  const a1 = 1 / (1 + g * (g + k)), a2 = g * a1, a3 = g * a2;
  const v3 = x - ic2, v1 = a1 * ic1 + a2 * v3, v2 = ic2 + a2 * ic1 + a3 * v3;
  ic1 = 2 * v1 - ic1; ic2 = 2 * v2 - ic2;
  return mode === 0 ? v2 : mode === 1 ? v1 : x - k * v1 - v2; }; }
const blep = (t, dt) => { if (t < dt) { t /= dt; return t + t - t * t - 1; } if (t > 1 - dt) { t = (t - 1) / dt; return t * t + t + t + 1; } return 0; };

// ── arrangement
const CH = { Am: [57, 60, 64, 69], F: [53, 57, 60, 65], C: [55, 60, 64, 67], G: [55, 59, 62, 67] };
const ROOT = { Am: 33, F: 29, C: 36, G: 31 };
const BARS = ['Am', 'Am', 'F', 'C', 'G', 'Am', 'F', 'C', 'G', 'Am', 'F', 'C', 'G', 'Am', 'F'];
const kicks = []; for (let t = 2; t < 24 - 1e-9; t += BEAT) kicks.push(t); kicks.push(26, 27, 28);

// sidechain gain curve
const SC = new Float32Array(N).fill(1);
for (const k of kicks) { const i0 = idx(k); for (let j = 0; j < SR * 0.45; j++) { const dt = j / SR; const g = 1 - 0.78 * Math.exp(-dt / 0.1) * Math.min(1, dt / 0.004 + 0.2); if (i0 + j < N) SC[i0 + j] = Math.min(SC[i0 + j], g); } }

// ── drums
function kick(t0, amp = 1, big = false) { const i0 = idx(t0); let ph = 0; const len = SR * (big ? 1.2 : 0.45);
  for (let j = 0; j < len; j++) { const t = j / SR; const f = 46 + 130 * Math.exp(-t / 0.028) + 22 * Math.exp(-t / 0.2); ph += 2 * Math.PI * f / SR;
    const env = Math.exp(-t / (big ? 0.6 : 0.26)) * Math.min(1, t / 0.0015); const v = Math.tanh(1.8 * Math.sin(ph)) * env + noise() * Math.exp(-t / 0.002) * 0.25;
    out(i0 + j, v * 0.62 * amp); } }
function clap(t0, amp = 1) { const i0 = idx(t0), f = svf(); for (let j = 0; j < SR * 0.4; j++) { const t = j / SR;
  let e = 0; for (const o of [0, 0.011, 0.023]) if (t >= o) e = Math.max(e, Math.exp(-(t - o) / 0.006)); e = Math.max(e, 0.6 * Math.exp(-Math.max(0, t - 0.023) / 0.11) * (t > 0.023));
  out(i0 + j, f(noise(), 1350, 1.4, 1) * e * 0.62 * amp, 0.05, 0.3); } }
function hat(t0, dec, amp, pan) { const i0 = idx(t0), f = svf(); for (let j = 0; j < SR * dec * 6; j++) { const t = j / SR; out(i0 + j, f(noise(), 8500, 0.8, 2) * Math.exp(-t / dec) * amp, pan, 0.05); } }
function snare(t0, amp) { const i0 = idx(t0), f = svf(); let ph = 0; for (let j = 0; j < SR * 0.25; j++) { const t = j / SR; ph += 2 * Math.PI * 190 / SR;
  out(i0 + j, (f(noise(), 2400, 0.9, 1) * 0.9 + Math.sin(ph) * 0.5 * Math.exp(-t / 0.04)) * Math.exp(-t / 0.075) * amp, 0, 0.18); } }
function crash(t0, amp, dec = 1.3) { const i0 = idx(t0), f = svf(); for (let j = 0; j < SR * dec * 3 && i0 + j < N; j++) { const t = j / SR;
  out(i0 + j, f(noise(), 6000, 0.7, 2) * Math.exp(-t / dec) * amp * Math.min(1, t / 0.002), (j % 2 ? 0.2 : -0.2), 0.25); } }

for (const k of kicks) kick(k, k >= 26 ? 0.85 : 1, false);
for (let t = 2.5; t < 24; t += 1) clap(t, 1);
for (let t = 2.25; t < 24; t += 0.5) hat(t, 0.055, 0.2, 0.15);
for (let t = 10; t < 24; t += 0.125) { if (Math.abs((t * 4) % 2 - 1) < 1e-6) hat(t, 0.018, 0.09, (t * 8) % 2 < 1 ? -0.35 : 0.35); }
// build: snare roll accelerating
{ let t = 24; while (t < 25.92) { const v = 0.25 + 0.75 * Math.pow((t - 24) / 2, 1.6); snare(t, 0.62 * v); t += t < 25 ? 0.25 : t < 25.5 ? 0.125 : 0.0625; } }

// ── bass: offbeat 8ths, sidechained
{ const f = svf(); let ph = 0, ph2 = 0;
  const notes = []; for (let b = 1; b <= 11; b++) { const r = ROOT[BARS[b]]; for (let q = 0; q < 4; q++) { const t = b * 2 + q * 0.5 + 0.25; notes.push([t, r, 0.2]); if (b >= 5 && q === 3) notes.push([t + 0.125, r + 12, 0.1]); } }
  notes.push([26, 33, 1.6]); notes.push([28, 29, 1.6]);
  const buf = new Float32Array(N);
  for (const [t0, m, d] of notes) { const i0 = idx(t0), fr = mtof(m), dt = fr / SR; ph = 0; ph2 = 0;
    for (let j = 0; j < SR * (d * TS + 0.08); j++) { const t = j / SR / TS; ph = (ph + dt) % 1; ph2 += 2 * Math.PI * fr / SR;
      const env = Math.min(1, t / 0.003) * (t < d ? 1 : Math.exp(-(t - d) / 0.02));
      buf[i0 + j] += ((2 * ph - 1 - blep(ph, dt)) * 0.55 + Math.sin(ph2) * 0.65) * env; } }
  for (let i = 0; i < N; i++) { const t = i / SR / TS; // cutoff envelope retriggered on each 8th offbeat
    const lt = ((t - 0.25) % 0.5 + 0.5) % 0.5; const fc = 160 + 1100 * Math.exp(-lt / 0.07);
    out(i, f(buf[i], fc, 1.1, 0) * 0.34 * SC[i]); } }

// ── pads (supersaw chords), filtered as a bus
{ for (let b = 0; b < BARS.length; b++) { const ch = CH[BARS[b]], t0 = b * 2, t1 = t0 + 2; const stab = b === 13;
    for (const m of ch) for (const [det, pan] of [[-0.11, -0.8], [0, 0], [0.12, 0.8]]) {
      const fr = mtof(m + det), dt = fr / SR; let ph = (noise() + 1) / 2;
      for (let i = idx(t0) - SR * 0.02; i < Math.min(N, idx(t1) + SR * 0.25); i++) { if (i < 0) continue; const t = i / SR / TS;
        ph = (ph + dt) % 1; const s = 2 * ph - 1 - blep(ph, dt);
        const env = Math.min(1, (t - t0 + 0.02) / 0.03) * (t < t1 ? 1 : Math.exp(-(t - t1) / 0.08)) * (stab ? 0.6 + 0.9 * Math.exp(-(t - t0) / 0.5) : 1);
        const a = (pan + 1) * Math.PI / 4; padL[i] += s * env * Math.cos(a); padR[i] += s * env * Math.sin(a); } } }
  const fl = svf(), fr_ = svf();
  for (let i = 0; i < N; i++) { const t = i / SR / TS;
    let fc = 1500; if (t < 2) fc = 250 + 900 * (t / 2) ** 2; else if (t >= 24 && t < 26) fc = 900 + 7000 * ((t - 24) / 2) ** 2.2; else if (t >= 26) fc = 3200 - 1900 * Math.min(1, (t - 26) / 3);
    let g = 0.05; if (t < 2) g = 0.05 * Math.min(1, t / 1.2); if (t >= 29.2) g *= Math.max(0, 1 - (t - 29.2) / 0.7);
    const sc = t < 2 ? 1 : SC[i]; const l = fl(padL[i], fc, 0.9, 0) * g * sc, r = fr_(padR[i], fc, 0.9, 0) * g * sc;
    L[i] += l; R[i] += r; revS[i] += (l + r) * 0.12; } }

// ── arp plucks
function pluck(t0, m, amp, pan, rv = 0.2, dl = 0.35) { const i0 = idx(t0), fr = mtof(m), dt = fr / SR, f = svf(); let ph = 0;
  for (let j = 0; j < SR * 0.35; j++) { const t = j / SR; ph = (ph + dt) % 1; const s = (ph < 0.5 ? 1 : -1) * 0.6 + (2 * ph - 1 - blep(ph, dt)) * 0.4;
    out(i0 + j, f(s, 400 + 5000 * Math.exp(-t / 0.05), 1.2, 0) * Math.exp(-t / 0.09) * Math.min(1, t / 0.002) * amp, pan, rv, dl); } }
{ const pat = [0, 1, 2, 3, 2, 1, 3, 2]; for (let t = 6; t < 24 - 1e-9; t += 0.125) { const b = Math.floor(t / 2), ch = CH[BARS[b]], k = Math.round(t / 0.125);
    pluck(t, ch[pat[k % 8]] + 12, 0.075 * (k % 4 === 0 ? 1 : 0.7), (k % 2 ? 0.3 : -0.3)); }
  for (let t = 26.5; t < 29; t += 0.25) { const ch = CH[BARS[Math.floor(t / 2)]], k = Math.round(t / 0.25); pluck(t, ch[[0, 2, 3, 1][k % 4]] + 12, 0.05, k % 2 ? 0.35 : -0.35, 0.35, 0.4); } }

// ── bells (ball landings / countdown / bookend)
function bell(t0, m, amp, pan = 0, rv = 0.45) { const i0 = idx(t0), fr = mtof(m); for (let j = 0; j < SR * 1.2; j++) { const t = j / SR;
  const v = Math.sin(2 * Math.PI * fr * t + 1.6 * Math.exp(-t / 0.06) * Math.sin(2 * Math.PI * fr * 2 * t)) * Math.exp(-t / 0.32) * Math.min(1, t / 0.001);
  out(i0 + j, v * amp, pan, rv, 0.15); } }
function thud(t0, amp) { const i0 = idx(t0); let ph = 0; for (let j = 0; j < SR * 0.2; j++) { const t = j / SR; ph += 2 * Math.PI * (70 + 80 * Math.exp(-t / 0.02)) / SR; out(i0 + j, Math.sin(ph) * Math.exp(-t / 0.06) * amp); } }
bell(0.5, 81, 0.22, -0.15); thud(0.5, 0.35);
bell(1.0, 84, 0.2, 0.15); thud(1.0, 0.3);
bell(1.5, 88, 0.2, 0); thud(1.5, 0.3);
[24, 24.5, 25].forEach(t => bell(t, 86, 0.14, 0, 0.3)); bell(25.5, 91, 0.16, 0, 0.3);
bell(29.38, 81, 0.22, 0, 0.6); bell(29.62, 93, 0.1, 0, 0.6);

// ── whooshes / risers / impact
function sweep(t0, d, f0, f1, amp, rising = true, pan0 = -0.6, pan1 = 0.6) { const i0 = idx(t0), f = svf(); for (let j = 0; j < SR * d * TS; j++) { const k = j / (SR * d * TS);
  const fc = f0 * Math.pow(f1 / f0, k), env = rising ? Math.pow(k, 2) * (1 - Math.pow(k, 40)) : Math.pow(1 - k, 2) * Math.min(1, k * 30);
  out(i0 + j, f(noise(), fc, 2.2, 1) * env * amp, lerp(pan0, pan1, k), 0.15); } }
const lerp = (a, b, t) => a + (b - a) * t;
sweep(1.6, 0.4, 300, 5000, 0.5);                      // ball launch
crash(2.0, 0.16);
for (const c of [4, 6, 8, 10, 12, 14, 16, 18, 22, 24]) sweep(c - 0.3, 0.3, 500, 4000, 0.22, true, c % 4 ? -0.5 : 0.5, c % 4 ? 0.5 : -0.5);
for (const c of [20, 20.5, 21, 21.5]) sweep(c, 0.3, 5000, 600, 0.45, false, c % 1 ? 0.6 : -0.6, c % 1 ? -0.6 : 0.6);
sweep(24, 1.93, 250, 9000, 0.8);                      // build riser
{ const i0 = idx(24); let ph = 0; for (let j = 0; j < SR * 1.93 * TS; j++) { const k = j / (SR * 1.93 * TS); const fr = 110 * Math.pow(8, k); ph = (ph + fr / SR) % 1; out(i0 + j, (2 * ph - 1) * 0.07 * k, 0, 0.3); } }
// impact at 26
{ const i0 = idx(26); let ph = 0; const f = svf(); for (let j = 0; j < SR * 2.5; j++) { const t = j / SR; ph += 2 * Math.PI * (32 + 70 * Math.exp(-t / 0.35)) / SR;
    out(i0 + j, Math.tanh(1.5 * Math.sin(ph)) * Math.exp(-t / 0.9) * 0.5 + f(noise(), 900, 0.7, 0) * Math.exp(-t / 0.25) * 0.5, 0, 0.35); } }
crash(26, 0.2, 1.8);
sweep(29.0, 0.38, 400, 6000, 0.3, true, 0.5, -0.5);    // collapse

// pre-impact gap: duck everything but the tail of the riser in the last 60ms before 26
for (let i = idx(25.94); i < idx(26); i++) { L[i] *= 0.15; R[i] *= 0.15; revS[i] *= 0.2; dlyS[i] *= 0.2; }

// ── ping-pong dotted-8th delay
{ const D = idx(0.375); const dl = new Float32Array(N), dr = new Float32Array(N); const lp1 = svf(), lp2 = svf();
  for (let i = 0; i < N; i++) { const inL = dlyS[i] + (i >= D ? dr[i - D] * 0.42 : 0), inR = (i >= D ? dl[i - D] * 0.42 : 0);
    dl[i] = lp1(inL, 3500, 0.7, 0); dr[i] = lp2(inR, 3500, 0.7, 0); L[i] += dl[i] * 0.55; R[i] += dr[i] * 0.55; revS[i] += (dl[i] + dr[i]) * 0.1; } }
// ── freeverb
{ const s = SR / 44100, combs = [1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617], aps = [556, 441, 341, 225];
  const run = (spread) => { const cb = combs.map(c => ({ b: new Float32Array(Math.round((c + spread) * s)), i: 0, f: 0 })), ab = aps.map(a => ({ b: new Float32Array(Math.round((a + spread) * s)), i: 0 }));
    const o = new Float32Array(N); const pre = svf();
    for (let n = 0; n < N; n++) { const x = pre(revS[n], 300, 0.7, 2) * 0.03; let y = 0;
      for (const c of cb) { const v = c.b[c.i]; c.f = v * 0.72 + c.f * 0.28; c.b[c.i] = x + c.f * 0.86; c.i = (c.i + 1) % c.b.length; y += v; }
      for (const a of ab) { const v = a.b[a.i]; a.b[a.i] = y + v * 0.5; a.i = (a.i + 1) % a.b.length; y = v - y; }
      o[n] = y; } return o; };
  const rl = run(0), rr = run(23); for (let i = 0; i < N; i++) { L[i] += rl[i] * 0.9; R[i] += rr[i] * 0.9; } }

// ── master: DC block, gentle saturation, end fade
{ let xl = 0, yl = 0, xr = 0, yr = 0; for (let i = 0; i < N; i++) { const t = i / SR / TS;
    yl = L[i] - xl + 0.9995 * yl; xl = L[i]; yr = R[i] - xr + 0.9995 * yr; xr = R[i];
    const fade = t > 29.75 ? Math.max(0, 1 - (t - 29.75) / 0.25) : 1;
    L[i] = Math.tanh(yl * 1.1) * fade; R[i] = Math.tanh(yr * 1.1) * fade; } }

// ── write float WAV
const buf = Buffer.alloc(44 + N * 8); buf.write('RIFF', 0); buf.writeUInt32LE(36 + N * 8, 4); buf.write('WAVE', 8); buf.write('fmt ', 12);
buf.writeUInt32LE(16, 16); buf.writeUInt16LE(3, 20); buf.writeUInt16LE(2, 22); buf.writeUInt32LE(SR, 24); buf.writeUInt32LE(SR * 8, 28); buf.writeUInt16LE(8, 32); buf.writeUInt16LE(32, 34);
buf.write('data', 36); buf.writeUInt32LE(N * 8, 40);
let peak = 0; for (let i = 0; i < N; i++) { buf.writeFloatLE(L[i], 44 + i * 8); buf.writeFloatLE(R[i], 48 + i * 8); peak = Math.max(peak, Math.abs(L[i]), Math.abs(R[i])); }
fs.writeFileSync(process.argv[2] || 'music.wav', buf); console.log('peak', peak.toFixed(3));
