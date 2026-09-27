/* timeline.js — the beat sheet. 128 BPM, 32 beats, 15.000 s.
   Every event below is expressed in beats; R.b(n) converts to seconds. */
(function (R) {
  'use strict';
  const E = R.E, b = R.b, lerp = R.lerp, inv = R.inv;
  const P = R.palette = {
    ink: R.hex('#0B0B0C'),
    paper: R.hex('#F1EEE7'),
    orange: R.hex('#FF4D17'),
    blue: R.hex('#2536FF'),
  };
  R.SCENES = ['scenePoint', 'sceneLine', 'sceneWorld', 'sceneWords', 'sceneFinale', 'climax'];
  const PEN_R = 17;
  R.PEN_R = PEN_R;

  // ------------------------------------------------------------ camera shake
  const HITS = [ // [beat, amplitude px, decay]
    [0.25, 16, 9], [3, 7, 12], [5, 4, 16], [8, 2.5, 18], [8.25, 2, 18], [8.5, 2, 18], [8.75, 2, 18],
    [10, 3, 14], [13.1, 5, 12], [16, 6, 10], [19, 3, 14], [23, 5, 14], [24, 4, 16], [25, 4, 16], [26, 5, 16], [28, 7, 11],
  ];
  const n1 = (x) => Math.sin(x * 1.7) * 0.6 + Math.sin(x * 3.1 + 1.3) * 0.3 + Math.sin(x * 7.3 + 2.1) * 0.1;
  R.shakeAt = function (t) {
    let a = 0;
    for (const [bt, amp, dec] of HITS) a += amp * R.kick(t, bt, dec);
    return [a * n1(t * 60), a * n1(t * 60 + 17.3), a * 0.0012 * n1(t * 45 + 5.1)];
  };

  // ------------------------------------------------------------ lens / post
  R.lensAt = function (t) {
    const B = t / R.BEAT;
    const impact = (bt, n = 2) => (t >= b(bt) && t < b(bt) + n / R.FPS ? 1 : 0);
    const ch = B < 5 ? 'point' : B < 9 ? 'line' : B < 12 ? 'plane' : B < 19 ? 'volume' : B < 23 ? 'time' : B < 27 ? 'climax' : 'end';
    const base = { point: 0.0012, line: 0.0006, plane: 0.0007, volume: 0.001, time: 0.0024, climax: 0.0028, end: 0 }[ch];
    const light = ch === 'line' || (ch === 'climax' && false);
    return {
      ca: base + 0.016 * R.kick(t, 0.25, 12) + 0.008 * R.kick(t, 3, 10) + 0.012 * R.kick(t, 16, 9) + 0.006 * R.kick(t, 28, 14)
        + (ch === 'climax' ? 0.0025 * R.pb(t, 23, 27) : 0),
      invert: impact(0.25, 2) || impact(16, 1) || impact(26.99, 1),
      flash: [1, 1, 1, 0.9 * impact(21, 1)],
      bloom: ch === 'end' ? 0.35 : 0.55,
      grain: light ? 0.035 : ch === 'end' ? 0.03 : 0.045,
      vig: light ? 0.1 : ch === 'plane' || ch === 'volume' ? 0.16 : 0.28,
    };
  };

  // Motion-blur samples per frame for offline renders: fast choreography gets more,
  // holds get fewer (raymarched frames are expensive), 2D frames are cheap.
  const FAST = [[9.0, 10.15], [10.45, 10.78], [10.95, 11.25], [11.45, 11.85], [12.0, 14.35], [14.9, 16.3], [16.35, 17.75], [17.85, 19.15]];
  R.subframeHint = function (t, sub2D = 6, subWorld = 2, subFast = 4) {
    const B = t / R.BEAT;
    if (B < 9 || B >= 27) return sub2D;
    if (B >= 23) {
      const i = R.climax.cutAt(t);
      const world = (k) => ['plane', 'volume', 'time'].includes(R.CUTS[k][1]);
      const iris = i > 0 && R.CUTS[i][0] <= 24.5 && t - b(R.CUTS[i][0]) < 0.075;
      return world(i) || (iris && world(i - 1)) ? subWorld : sub2D;
    }
    for (const [a, c] of FAST) if (B >= a && B < c) return subFast;
    return subWorld;
  };

  // HUD: colour follows the ground; the timecode obeys the time chapter's clock
  R.hudState = function (t) {
    const B = t / R.BEAT;
    if (B >= 27) return { alpha: 0 };
    const st = { alpha: 0.78, color: P.paper };
    if (B < 0.25) st.alpha = 0;
    else if (B < 0.6) st.alpha = 0.78 * R.pb(t, 0.25, 0.6);
    if (B >= 5 && B < 9) st.color = P.ink;
    if (B >= 19 && B < 23) {
      const w = R.worldState(t);
      st.tc = b(19) + w.fx.tau;
    }
    if (B >= 23) {
      const i = R.climax.cutAt(t);
      const [, kind, o] = R.CUTS[i];
      const bg = o.bg || o.paper || o.floor || (kind === 'line' ? P.paper : kind === 'point' ? P.ink : kind === 'time' ? P.ink : P.blue);
      const lum = 0.3 * bg[0] + 0.59 * bg[1] + 0.11 * bg[2];
      st.color = lum > 0.6 ? P.ink : P.paper;
      const c = R.climax.chapterAt(t);
      if (c) st.chapter = [0, c[0], c[1]];
    }
    return st;
  };

  // ------------------------------------------------------------ 0D point
  function pointState(t) {
    const SP = R.scenePoint;
    const p = { t, bg: P.ink, ink: P.paper, acc: P.orange, dev: 1 };
    p.boom = t - b(0.25);
    p.invX = t < b(2) ? -1e5 : lerp(-250, 2250, R.pb(t, 2, 2.6, E.inOutCubic));
    p.refr = 34 * Math.exp(-Math.max(0, t - b(0.25)) * 3.5);
    const zIn = R.pb(t, 3, 3.5, E.outExpo);
    const zOut = R.pb(t, 4, 4.75, E.inOutCubic);
    p.zoom = 1 + 1.6 * zIn * (1 - zOut);
    p.focus = SP.center;
    p.zoomRot = -0.12 * zIn * (1 - zOut);
    p.collapse = t < b(4) ? 1e5 : lerp(1500, -80, R.pb(t, 4.05, 4.62, E.inOutSine));

    // protagonist
    let r, sq = [1, 1], glow = 0;
    const hit = b(0.25);
    if (t < hit) {
      const u = E.inCubic(inv(0, hit, t));
      r = lerp(R.DOT0, R.DOT0 + 12, u);
      sq = [1 + 0.42 * u, 1 - 0.34 * u];
      glow = 0.9 * u;
    } else {
      const dt = t - hit;
      r = lerp(R.DOT0 + 12, SP.TIT_R, E.spring(dt * 1.15, 3.2, 7.5));
      const k = R.ring(t, 0.25, 3.4, 8);
      sq = [1 - 0.22 * k, 1 + 0.26 * k];
      glow = 1.6 * Math.exp(-dt * 7);
    }
    r *= 1 + 0.2 * Math.exp(-Math.pow((SP.center[0] - p.invX) / 160, 2));
    r *= p.zoom;
    // shrink to pen nib as the field implodes
    const s = R.pb(t, 4.1, 4.75, E.inOutCubic);
    r = lerp(r, PEN_R, s);
    glow += 0.8 * Math.sin(Math.PI * R.pb(t, 4.3, 4.8));
    let pos = SP.center;
    const hp = R.pb(t, 4.45, 5, E.inOutSine);
    if (hp > 0) {
      const st = R.sceneLine.START;
      pos = [lerp(SP.center[0], st[0], hp), lerp(SP.center[1], st[1], hp) - 190 * R.hop(hp)];
      const v = Math.sin(Math.PI * hp);
      sq = [1 - 0.18 * v, 1 + 0.22 * v];
    }
    p.dot = [pos[0], pos[1], r];
    p.squash = sq;
    p.glow = glow;
    return p;
  }

  R.pointState = pointState;

  // ------------------------------------------------------------ 1D line
  const WRITE = E.bezier(0.42, 0.0, 0.22, 1);
  function lineState(t) {
    const SL = R.sceneLine;
    const p = { paper: P.paper, ink: P.ink, acc: P.orange, spacing: 8.5, strandW: 4.5, squash: [1, 1], lineY: 540, stretch: 1.35 };
    const wr = WRITE(inv(b(5), b(6.5), t));
    p.write = wr;
    p.pull = R.pb(t, 7, 7.5);
    p.mode = t < b(7.5) ? 'write' : 'staff';
    let r = PEN_R, pos, sq = [1, 1], rotA = 0;
    if (t < b(6.5)) {
      const h = SL.at(wr).p, h0 = SL.at(Math.max(0, wr - 0.004)).p;
      const vx = h[0] - h0[0], vy = h[1] - h0[1], sp = Math.hypot(vx, vy);
      pos = h; rotA = Math.atan2(vy, vx);
      const st = Math.min(0.5, sp * 0.02);
      sq = [1 + st, 1 / (1 + st)];
      // landing squash at the start
      const land = R.kick(t, 5, 16);
      sq = [sq[0] * (1 + 0.35 * land), sq[1] * (1 - 0.3 * land)];
    } else if (t < b(7)) {
      // pen lifts and dots the i
      const u = R.pb(t, 6.5, 7, E.inOutSine);
      pos = [lerp(SL.END[0], SL.TITTLE[0], u), lerp(SL.END[1], SL.TITTLE[1], u) - 230 * R.hop(u)];
      r = lerp(PEN_R, 25, u);
      const v = Math.sin(Math.PI * u);
      sq = [1 - 0.15 * v, 1 + 0.2 * v];
    } else {
      pos = SL.TITTLE.slice(); r = 25;
      const land = R.ring(t, 7, 5, 9);
      sq = [1 + 0.3 * land, 1 - 0.3 * land];
    }
    // staff: strands fan out into five lines
    const sep = R.pb(t, 7.3, 7.85, E.outBack);
    p.spacing = lerp(8.5, 64, sep);
    // bounce choreography (after the i vanishes, the dot hangs... then drops)
    const lineYk = (k) => p.lineY + (k - 2) * p.spacing;
    const hits = [[8, 0], [8.25, 1], [8.5, 2], [8.75, 3]];
    const x0 = SL.TITTLE[0], dx = 118;
    p.deflect = [];
    if (t >= b(7.4)) {
      if (t < b(8)) {
        const u = inv(b(7.4), b(8), t);
        pos = [x0, lerp(SL.TITTLE[1], lineYk(0) - r, u * u)];
        sq = [1 - 0.12 * u * u, 1 + 0.18 * u * u];
      } else {
        let i = 0; while (i < hits.length - 1 && t >= b(hits[i + 1][0])) i++;
        const [hb, k] = hits[i];
        const u = inv(b(hb), b(hb + 0.25), t);
        const xa = x0 + i * dx, xb = x0 + (i + 1) * dx;
        const ya = lineYk(k) - r;
        const yb = i < hits.length - 1 ? lineYk(hits[i + 1][1]) - r : -300;
        const peak = i < hits.length - 1 ? 60 : 0;
        if (i < hits.length - 1) pos = [lerp(xa, xb, u), lerp(ya, yb, u) - (peak + 0.5 * Math.abs(yb - ya)) * R.hop(u) * 1.0 + (yb - ya) * 0];
        else pos = [lerp(xa, xa + 260, u), lerp(ya, yb, E.outCubic(u))];
        const land = R.kick(t, hb, 22);
        sq = [1 + 0.38 * land, 1 - 0.34 * land];
      }
      for (let i = 0; i < hits.length; i++) {
        const [hb, k] = hits[i];
        const dt = t - b(hb);
        if (dt < 0) continue;
        const env = Math.exp(-dt * 7);
        p.deflect.push({ k, x: x0 + i * dx, w: 95, a: 24 * env * Math.cos(dt * Math.PI * 2 * 6.5), v: 6 * env * Math.sin(dt * 40) });
      }
    }
    // lines rush upward, the last one dragging the blue plane
    p.lift = [0, 0, 0, 0, 0];
    for (let k = 0; k < 5; k++) {
      const u = R.ps(t, b(8.72) + k * 0.018, b(9) - (4 - k) * 0.004, E.inCubic);
      p.lift[k] = u * (lineYk(k) + 80);
    }
    if (t >= b(8.72)) p.curtain = { k: 4, color: P.blue };
    p.dot = [pos[0], pos[1], r];
    p.squash = sq; p.dotRot = rotA;
    return p;
  }

  R.lineState = lineState;

  R.director = function (t, target, env) {
    if (t < b(5)) { R.scenePoint.render(target, pointState(t), env); return; }
    if (t < b(9)) { R.sceneLine.render(target, lineState(t), env); return; }
    if (t < b(23)) { R.sceneWorld.render(target, R.worldState(t), env); return; }
    if (t < b(27)) { R.climax.render(t, target, env); return; }
    R.sceneFinale.render(target, R.finaleState(t), env);
  };
})(window.REEL = window.REEL || {});
