/* scene-line.js — 1D. "A line is a dot that went for a walk" (Klee).
   The dot writes `line` as one continuous 5-strand ribbon, dots its own i,
   the ribbon is pulled taut into a musical staff, and the dot bounces down
   the staff like notes before the lines rush upward dragging the next plane. */
(function (R) {
  'use strict';
  const G = R.glyphs;
  const EM = 330;
  const TR = 0.13;
  const lx = { l: 0, i: G.W + TR, n: 2 * (G.W + TR), e: 2 * (G.W + TR) + 1 + TR };
  const WIDTH = lx.e + 1;
  const ORIGIN = [R.W / 2 - (WIDTH * EM) / 2, 700];  // baseline-left
  const c = G.W / 2, rr = 0.5 - c, f = 0.1;           // centreline offsets, ring radius, fillet

  // ---- path in em units (y up), sampled densely
  const pts = [];
  const push = (x, y) => pts.push([x, y]);
  function line(x0, y0, x1, y1, n = 24) { for (let i = 1; i <= n; i++) push(x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n); }
  function arc(cx, cy, r, a0, a1, n = 24) { for (let i = 1; i <= n; i++) { const a = a0 + (a1 - a0) * i / n; push(cx + r * Math.cos(a), cy + r * Math.sin(a)); } }
  function cubic(p0, p1, p2, p3, n = 30) {
    for (let i = 1; i <= n; i++) {
      const t = i / n, u = 1 - t;
      push(u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0],
        u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1]);
    }
  }
  const PI = Math.PI;
  const xl = lx.l + c, xi = lx.i + c, xn0 = lx.n + c, xn1 = lx.n + 1 - c, ec = lx.e + 0.5;
  push(xl, 1.5);
  line(xl, 1.5, xl, f, 40);
  arc(xl + f, f, f, PI, 1.5 * PI, 10);
  line(xl + f, 0, xi - f, 0, 10);
  arc(xi - f, f, f, 1.5 * PI, 2 * PI, 10);
  line(xi, f, xi, 1, 30);
  line(xi, 1, xi, f, 30);               // retrace — strands nest into a paperclip cap
  arc(xi + f, f, f, PI, 1.5 * PI, 10);
  line(xi + f, 0, xn0 - f, 0, 10);
  arc(xn0 - f, f, f, 1.5 * PI, 2 * PI, 10);
  line(xn0, f, xn0, 0.5, 14);
  arc(lx.n + 0.5, 0.5, rr, PI, 0, 40);   // arch
  line(xn1, 0.5, xn1, f, 14);
  arc(xn1 + f, f, f, PI, 1.5 * PI, 10);
  cubic([xn1 + f, 0], [xn1 + f + 0.17, 0], [ec - rr - 0.16, 0.5], [ec - rr, 0.5], 30);
  line(ec - rr, 0.5, ec + rr, 0.5, 24);  // crossbar
  arc(ec, 0.5, rr, 0, (302 / 180) * PI, 90);
  // cumulative length
  const S = [0];
  for (let i = 1; i < pts.length; i++) S.push(S[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
  const LEN = S[S.length - 1];
  const toScr = (p) => [ORIGIN[0] + p[0] * EM, ORIGIN[1] - p[1] * EM];
  const SCR = pts.map(toScr);
  const TITTLE = toScr([xi, G.TIT.y + 0.02]);
  const START = SCR[0];
  const END = SCR[SCR.length - 1];

  // position at arc-length fraction u (0..1) along the written path
  function at(u) {
    const s = R.clamp(u) * LEN;
    let lo = 0, hi = S.length - 1;
    while (hi - lo > 1) { const m = (lo + hi) >> 1; if (S[m] < s) lo = m; else hi = m; }
    const k = (s - S[lo]) / Math.max(1e-9, S[hi] - S[lo]);
    return { i: lo, k, p: [SCR[lo][0] + (SCR[hi][0] - SCR[lo][0]) * k, SCR[lo][1] + (SCR[hi][1] - SCR[lo][1]) * k] };
  }

  const STRANDS = 5;
  function ribbon(ctx, poly, spacing, strandW, ink, paper) {
    // concentric strokes: alternating ink/paper widths produce perfect parallel strands
    ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    const outer = (STRANDS - 1) * spacing + strandW;
    for (let k = 0; k < STRANDS; k++) {
      const wInk = outer - 2 * k * spacing;
      const wGap = wInk - 2 * strandW;
      ctx.beginPath();
      ctx.moveTo(poly[0][0], poly[0][1]);
      for (let i = 1; i < poly.length; i++) ctx.lineTo(poly[i][0], poly[i][1]);
      ctx.strokeStyle = ink; ctx.lineWidth = wInk; ctx.stroke();
      if (wGap > 0.5) { ctx.strokeStyle = paper; ctx.lineWidth = wGap; ctx.stroke(); }
    }
  }

  let canvas, ctx, tex;
  R.sceneLine = {
    EM, ORIGIN, START, END, TITTLE, LEN, SCR, S, at,
    init() { this.resize(); },
    resize() {
      canvas = R.canvas2d(Math.round(R.W * R.scale), Math.round(R.H * R.scale));
      ctx = canvas.getContext('2d');
      if (tex) R.gl.deleteTexture(tex.tex);
      tex = new R.CanvasTex(canvas);
    },
    render(target, p, env) {
      const s = env.scale;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.fillStyle = R.rgba(p.paper); ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.setTransform(s, 0, 0, s, 0, 0);
      ctx.translate(R.W / 2 + env.shake[0], R.H / 2 + env.shake[1]);
      ctx.rotate(env.shake[2]);
      ctx.translate(-R.W / 2, -R.H / 2);
      const ink = R.rgba(p.ink), paper = R.rgba(p.paper);

      if (p.mode === 'write') {
        // written portion of the path, optionally morphing toward a straight line
        const head = at(p.write);
        const n = head.i + 1;
        const poly = new Array(n + 1);
        for (let i = 0; i < n; i++) poly[i] = SCR[i];
        poly[n] = head.p;
        if (p.pull > 0) {
          for (let i = 0; i <= n; i++) {
            const si = i < n ? S[i] : head.k;
            const u = (i < n ? S[i] : S[head.i]) / LEN;
            const edge = Math.abs(2 * u - 1);             // 1 at the ends, 0 in the middle
            const d = (1 - edge) * 0.45;
            const k = R.E.inOutCubic(R.clamp((p.pull - d) / (1 - 0.45)));
            const sx = R.W / 2 + (u - 0.5) * LEN * EM * p.stretch;
            poly[i] = [R.lerp(poly[i][0], sx, k), R.lerp(poly[i][1], p.lineY, k)];
          }
        }
        ribbon(ctx, poly, p.spacing, p.strandW, ink, paper);
      } else if (p.mode === 'staff') {
        ctx.lineCap = 'butt';
        for (let k = 0; k < STRANDS; k++) {
          const y0 = p.lineY + (k - 2) * p.spacing - p.lift[k];
          ctx.beginPath();
          for (let x = -40; x <= R.W + 40; x += 12) {
            let y = y0;
            for (const dfl of p.deflect) if (dfl.k === k) y += dfl.a * Math.exp(-Math.pow((x - dfl.x) / dfl.w, 2)) + dfl.v * Math.sin((x - dfl.x) / dfl.w * 2.2) * Math.exp(-Math.pow((x - dfl.x) / (dfl.w * 3), 2));
            if (x === -40) ctx.moveTo(x, y); else ctx.lineTo(x, y);
          }
          ctx.strokeStyle = ink; ctx.lineWidth = p.strandW; ctx.stroke();
          if (p.curtain && k === p.curtain.k) {
            ctx.lineTo(R.W + 40, R.H + 40); ctx.lineTo(-40, R.H + 40); ctx.closePath();
            ctx.fillStyle = R.rgba(p.curtain.color); ctx.fill();
            ctx.stroke();
          }
        }
      }
      // the dot
      if (p.dot) {
        const [x, y, r] = p.dot;
        ctx.save();
        ctx.translate(x, y);
        ctx.rotate(p.dotRot || 0);
        ctx.scale(p.squash[0], p.squash[1]);
        ctx.beginPath(); ctx.arc(0, 0, r, 0, Math.PI * 2);
        ctx.fillStyle = R.rgba(p.acc); ctx.fill();
        ctx.restore();
      }
      tex.upload();
      R.draw(R.blitProg, target, { uTex: tex, uAlpha: 1 });
    },
  };
})(window.REEL = window.REEL || {});
