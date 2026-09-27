/* timeline-climax.js — b23..b27: an accelerating montage (8ths, 16ths, 32nds)
   through every dimension, stitched by dot-irises and variable-font flash
   words; b27..b28: silence; b28..b32: "Point made." */
(function (R) {
  'use strict';
  const E = R.E, b = R.b, lerp = R.lerp, inv = R.inv;
  const P = R.palette;
  const lin = (c) => c.map((v) => Math.pow(v, 2.2));

  // [beat, kind, opts]
  // Fast cuts stay in a dark-to-mid luminance band (blue <-> ink is under a 10%
  // relative-luminance swing); colour lives in the content, not full-frame flashes.
  const CUTS = [
    [23.0, 'point', { src: 1.55, speed: 0.6, bg: P.blue, ink: P.paper, zoom: 1.35 }],
    [23.5, 'line', { src: 5.45, speed: 2.1, paper: P.ink, ink: P.paper }],
    [24.0, 'plane', { src: 9.95, floor: P.orange, disc: P.blue }],
    [24.5, 'volume', { src: 14.4, yaw: 0.75, pitch: 0.05, dist: 5.5, vh: 3.3 }],
    [25.0, 'word', { word: 'type', bg: P.ink, fg: P.orange, w0: 25, w1: 151 }],
    [25.25, 'time', { src: 20.4 }],
    [25.5, 'word', { word: 'form', bg: P.blue, fg: P.paper, w0: 151, w1: 40 }],
    [25.75, 'point', { src: 3.2, speed: 0.4, bg: P.ink, ink: P.orange, acc: P.paper }],
    [26.0, 'line', { src: 8.1, speed: 1, paper: P.blue, ink: P.paper }],
    [26.125, 'word', { word: 'space', bg: P.ink, fg: P.paper, w0: 30, w1: 140 }],
    [26.25, 'volume', { src: 16.8, yaw: -0.6, pitch: 0.35, dist: 7, vh: 4.2 }],
    [26.375, 'word', { word: 'light', bg: P.blue, fg: P.orange, w0: 151, w1: 25 }],
    [26.5, 'plane', { src: 10.8, floor: P.ink }],
    [26.625, 'word', { word: 'rhythm', bg: P.ink, fg: P.orange, w0: 25, w1: 120 }],
    [26.75, 'time', { src: 22.7 }],
    [26.875, 'point', { src: 0.55, speed: 0.5 }],
    [27.0, 'end', {}],
  ];
  R.CUTS = CUTS;
  // hard cuts (seconds): motion blur must not straddle these
  R.CUT_TIMES = CUTS.map((c) => b(c[0])).concat([b(5), b(31.5)]);
  const CH = { point: ['0D', 'point'], line: ['1D', 'line'], plane: ['2D', 'plane'], volume: ['3D', 'volume'], time: ['4D', 'time'], word: null };

  function cutAt(t) {
    const B = t / R.BEAT;
    let i = 0;
    while (i < CUTS.length - 1 && B >= CUTS[i + 1][0]) i++;
    return i;
  }

  function renderCut(i, t, target, env) {
    const [cb, kind, o] = CUTS[i];
    const u = t - b(cb);
    const src = b(o.src || 0) + u * (o.speed || 1);
    if (kind === 'point') {
      const p = R.pointState(src);
      if (o.bg) p.bg = o.bg; if (o.ink) p.ink = o.ink; if (o.acc) p.acc = o.acc;
      if (o.zoom) { p.zoom *= o.zoom; p.dot[2] *= o.zoom; }
      R.scenePoint.render(target, p, env);
    } else if (kind === 'line') {
      const p = R.lineState(src);
      if (o.paper) p.paper = o.paper; if (o.ink) p.ink = o.ink;
      R.sceneLine.render(target, p, env);
    } else if (kind === 'plane' || kind === 'volume' || kind === 'time') {
      const st = R.worldState(src);
      if (o.floor) { st.pal[4] = lin(o.floor); st.light.bgTop = st.light.bgBot = lin(o.floor); }
      if (o.disc) st.pal[2] = lin(o.disc);
      if (o.yaw != null) {
        const tg = [-0.1, 0.7, 0];
        st.cam = R.orbitCam(tg, o.yaw + u * 0.6, o.pitch, o.dist, o.vh);
        st.camDist = o.dist; st.light.fogStart = o.dist + 3.5;
      }
      R.sceneWorld.render(target, st, env);
    } else if (kind === 'word') {
      const k = E.outCubic(inv(b(cb), b(CUTS[i + 1][0]), t));
      R.sceneWords.render(target, {
        bg: o.bg, fg: o.fg, word: o.word, wdth: lerp(o.w0, o.w1, k), wght: 1000, size: 520, fit: 0,
      }, env);
    } else {
      R.sceneFinale.render(target, finaleState(t), env);
    }
  }

  // iris: the next cut opens out of the dot
  const IRIS_FS = R.GLSL + `
in vec2 vUv;
uniform sampler2D uA, uB;
uniform float uR;
uniform vec3 uRing;
void main(){
  vec2 px = designPx();
  float d = length(px - vec2(960., 540.)) - uR;
  float aa = 1. / uScale;
  float m = smoothstep(aa, -aa, d);
  vec3 c = mix(texture(uA, vUv).rgb, texture(uB, vUv).rgb, m);
  float ring = smoothstep(aa, -aa, abs(d + 9.) - 9.) * step(1., uR);
  fragColor = vec4(mix(c, uRing, ring), 1.);
}`;
  let irisProg;
  R.climax = {
    init() { irisProg = new R.Program(IRIS_FS, 'iris'); },
    render(t, target, env) {
      const i = cutAt(t);
      const cb = CUTS[i][0];
      const since = t - b(cb);
      const irisDur = 0.075;
      // iris only on the eighth-note cuts
      if (i > 0 && cb <= 24.5 && since < irisDur) {
        renderCut(i - 1, t, R.tmpA, env);
        renderCut(i, t, R.tmpB, env);
        const r = lerp(0, 1150, E.inQuad(since / irisDur));
        R.draw(irisProg, target, { uA: R.tmpA.tex, uB: R.tmpB.tex, uR: r, uRing: P.orange, uScale: env.scale, uJitter: env.jitter });
      } else renderCut(i, t, target, env);
    },
    cutAt,
    chapterAt(t) { const k = CUTS[cutAt(t)][1]; return CH[k] || null; },
  };

  // ------------------------------------------------------------ finale
  function finaleState(t) {
    const B = t / R.BEAT;
    const p = { bg: P.ink, fg: P.paper, acc: P.orange, squash: [1, 1], textA: 0, x1: 0, x2: 0, caption: 0 };
    const cx = R.W / 2, cy = R.H / 2;
    let dx = 0, sq = [1, 1];
    if (B >= 27.5 && B < 31.5) {
      p.textA = 1;
      // "point" glides in and parks; "made" is thrown in and slams into the full stop
      p.x1 = -1700 * (1 - E.outExpo(inv(b(27.5), b(27.92), t)));
      const u = inv(b(27.62), b(28), t);
      p.x2 = u < 1 ? -1700 * (1 - E.inCubic(u)) : -10 * R.ring(t, 28, 2.6, 9);
      const hit = t >= b(28) ? t - b(28) : -1;
      if (hit >= 0) {
        dx = 26 * Math.exp(-hit * 7) * Math.sin(hit * 19);
        const k = Math.exp(-hit * 16);
        sq = [1 - 0.32 * k, 1 + 0.26 * k];
      }
      p.caption = R.pb(t, 29, 29.9);
      p.captionLines = ['MOTION DESIGN REEL', 'POINT  LINE  PLANE  VOLUME  TIME', '0D—4D / 128 BPM / 15.000 S / 2026'];
    }
    // one heartbeat before the loop re-detonates
    if (B >= 31.5) { const k = Math.sin(Math.PI * R.pb(t, 31.55, 31.95)); sq = [1 + 0.12 * k, 1 + 0.12 * k]; }
    p.dot = [cx + Math.max(0, dx), cy, R.DOT0];
    p.squash = sq;
    return p;
  }
  R.finaleState = finaleState;
})(window.REEL = window.REEL || {});
