/* glyphs.js — a small constructed, geometric lowercase alphabet (Bayer/Bauhaus
   lineage) defined as signed-distance parts. The same skeleton is rendered as
   halftone dots (0D), a single line (1D), paper planes (2D), solids (3D) and
   time-smeared solids (4D): every chapter word is made of what it names.
   Units: x-height = 1, baseline y = 0, y up. Stroke weight W. */
(function (R) {
  'use strict';
  const W = 0.25;           // stroke weight
  const TRACK = 0.13;       // letter spacing
  const TIT = { y: 1.36, r: 0.16 }; // tittle (the protagonist dot lives here)

  const wh = W / Math.cos(Math.atan(0.5)); // horizontal stroke width of v diagonals
  const deg = Math.PI / 180;

  // part: {t:type, ...}; types: box(c,h) ring(c,r) arcU(c,r) arcD(c,r) gap(c,r,a0,a1) poly(pts) disc(c,r)
  const L = {
    p: { adv: 1, parts: [{ t: 'box', c: [W / 2, 0.25], h: [W / 2, 0.75] }, { t: 'ring', c: [0.5, 0.5], r: 0.5 }] },
    o: { adv: 1, parts: [{ t: 'ring', c: [0.5, 0.5], r: 0.5 }] },
    l: { adv: W, parts: [{ t: 'box', c: [W / 2, 0.75], h: [W / 2, 0.75] }] },
    a: { adv: 1, parts: [{ t: 'ring', c: [0.5, 0.5], r: 0.5 }, { t: 'box', c: [1 - W / 2, 0.5], h: [W / 2, 0.5] }] },
    n: { adv: 1, parts: [{ t: 'box', c: [W / 2, 0.5], h: [W / 2, 0.5] }, { t: 'arcU', c: [0.5, 0.5], r: 0.5 }, { t: 'box', c: [1 - W / 2, 0.28], h: [W / 2, 0.28] }] },
    e: { adv: 1, parts: [{ t: 'gap', c: [0.5, 0.5], r: 0.5, a0: -60 * deg, a1: -21 * deg }, { t: 'box', c: [0.5, 0.5], h: [0.275, W / 2] }] },
    v: { adv: 1, parts: [{ t: 'vee', c: [0.5, 0.5] }] },
    u: { adv: 1, parts: [{ t: 'box', c: [W / 2, 0.72], h: [W / 2, 0.28] }, { t: 'arcD', c: [0.5, 0.5], r: 0.5 }, { t: 'box', c: [1 - W / 2, 0.5], h: [W / 2, 0.5] }] },
    m: { adv: 1.55, parts: [
      { t: 'box', c: [W / 2, 0.305], h: [W / 2, 0.305] },
      { t: 'arcU', c: [0.45, 0.55], r: 0.45 },
      { t: 'box', c: [0.9 - W / 2, 0.305], h: [W / 2, 0.305] },
      { t: 'arcU', c: [1.1, 0.55], r: 0.45 },
      { t: 'box', c: [1.55 - W / 2, 0.305], h: [W / 2, 0.305] }] },
    t: { adv: 0.66, parts: [{ t: 'box', c: [0.3, 0.68], h: [W / 2, 0.68] }, { t: 'box', c: [0.33, 1 - W / 2], h: [0.33, W / 2] }] },
    i: { adv: W, parts: [{ t: 'box', c: [W / 2, 0.5], h: [W / 2, 0.5] }], tittle: { c: [W / 2, TIT.y], r: TIT.r } },
    d: { adv: 1, parts: [{ t: 'ring', c: [0.5, 0.5], r: 0.5 }, { t: 'box', c: [1 - W / 2, 0.75], h: [W / 2, 0.75] }] },
    ' ': { adv: 0.3, parts: [] },
  };

  function layout(word, track = TRACK) {
    let x = 0; const out = [];
    for (const ch of word) {
      const g = L[ch]; if (!g) throw new Error('glyph missing: ' + ch);
      out.push({ ch, x, g });
      x += g.adv + track;
    }
    return { letters: out, width: x - track };
  }

  const f = (v) => (Number.isInteger(v) ? v.toFixed(1) : String(+v.toFixed(5)));
  const v2 = (a) => `vec2(${f(a[0])},${f(a[1])})`;

  // GLSL expression for one part, evaluated at vec2 `q` (letter-local)
  function partExpr(pt, q = 'q', w = 'GW') {
    switch (pt.t) {
      case 'box': return `sdBox2(${q},${v2(pt.c)},${v2(pt.h)})`;
      case 'ring': return `sdRing2(${q},${v2(pt.c)},${f(pt.r)},${w})`;
      case 'arcU': return `max(sdRing2(${q},${v2(pt.c)},${f(pt.r)},${w}), ${f(pt.c[1])}-${q}.y)`;
      case 'arcD': return `max(sdRing2(${q},${v2(pt.c)},${f(pt.r)},${w}), ${q}.y-${f(pt.c[1])})`;
      case 'gap': {
        const am = 0.5 * (pt.a0 + pt.a1), ha = 0.5 * (pt.a1 - pt.a0);
        return `sdGap2(${q},${v2(pt.c)},${f(pt.r)},${w},vec2(${f(Math.cos(-am))},${f(Math.sin(-am))}),vec2(${f(-Math.sin(ha))},${f(Math.cos(ha))}))`;
      }
      case 'vee': return `sdVee2(${q})`;
      case 'poly': return `sdPoly6(${q}, vec2[6](${pt.pts.map(v2).join(',')}))`;
      case 'disc': return `(length(${q}-${v2(pt.c)})-${f(pt.r)})`;
    }
    throw new Error('part type ' + pt.t);
  }

  // Static word SDF (union of all parts, tittles optional)
  function wordGLSL(fn, word, { track = TRACK, tittles = false } = {}) {
    const lay = layout(word, track);
    let s = `float ${fn}(vec2 p){ float d = 1e5; vec2 q;\n`;
    for (const lt of lay.letters) {
      s += `  q = p - vec2(${f(lt.x)}, 0.);\n`;
      for (const pt of lt.g.parts) s += `  d = min(d, ${partExpr(pt)});\n`;
      if (tittles && lt.g.tittle) s += `  d = min(d, length(q-${v2(lt.g.tittle.c)})-${f(lt.g.tittle.r)});\n`;
    }
    return s + '  return d; }\n';
  }

  const GLSL_SDF2 = `
#define GW ${f(W)}
float sdBox2(vec2 p, vec2 c, vec2 h){ vec2 d = abs(p-c)-h; return length(max(d,0.)) + min(max(d.x,d.y),0.); }
float sdRing2(vec2 p, vec2 c, float r, float w){ return abs(length(p-c) - (r - w*.5)) - w*.5; }
float sdWedge2(vec2 q, float ha){ q.y = abs(q.y); return dot(q, vec2(-sin(ha), cos(ha))); }
float sdRingGap2(vec2 p, vec2 c, float r, float w, float a0, float a1){
  float d = sdRing2(p,c,r,w);
  vec2 q = p - c; float am = .5*(a0+a1), ha = .5*(a1-a0);
  float cs = cos(-am), sn = sin(-am);
  q = vec2(cs*q.x - sn*q.y, sn*q.x + cs*q.y);
  return max(d, -sdWedge2(q, ha));
}
float sdGap2(vec2 p, vec2 c, float r, float w, vec2 cs, vec2 n){
  float d = sdRing2(p,c,r,w);
  vec2 q = p - c; q = vec2(cs.x*q.x - cs.y*q.y, cs.y*q.x + cs.x*q.y);
  q.y = abs(q.y);
  return max(d, -dot(q, n));
}
float sdSeg2(vec2 p, vec2 a, vec2 b, float th){ vec2 ba = b-a; float l = length(ba); vec2 d = ba/l; vec2 q = p - (a+b)*.5; q = vec2(d.x*q.x + d.y*q.y, -d.y*q.x + d.x*q.y); q = abs(q) - vec2(l, th)*.5; return length(max(q,0.)) + min(max(q.x,q.y),0.); }
float sdVee2(vec2 p){
  const float wh = ${f(wh)};
  vec2 a = vec2(wh*.5 - .05, 1.1), b = vec2(wh*.5 + .55, -.1);
  float d = min(sdSeg2(p, a, b, GW), sdSeg2(vec2(1.-p.x, p.y), a, b, GW));
  const float k = .894427191;
  d = max(d, (.5 - p.x - .5*p.y) * k);
  d = max(d, (p.x - .5 - .5*p.y) * k);
  return max(d, max(-p.y, p.y - 1.));
}
float sdPoly6(vec2 p, vec2 v[6]){
  float d = dot(p-v[0],p-v[0]); float s = 1.0;
  for(int i=0, j=5; i<6; j=i, i++){
    vec2 e = v[j]-v[i]; vec2 w = p-v[i];
    vec2 b = w - e*clamp(dot(w,e)/dot(e,e),0.,1.);
    d = min(d, dot(b,b));
    bvec3 c = bvec3(p.y>=v[i].y, p.y<v[j].y, e.x*w.y>e.y*w.x);
    if(all(c) || all(not(c))) s *= -1.0;
  }
  return s*sqrt(d);
}
`;

  // Canvas2D renderer for the same parts (y-up glyph space -> y-down canvas)
  function drawWord(ctx, word, x0, base, em, fill, { track = TRACK, tittles = true } = {}) {
    const lay = layout(word, track);
    ctx.fillStyle = fill;
    for (const lt of lay.letters) {
      const X = (gx) => x0 + (lt.x + gx) * em, Y = (gy) => base - gy * em;
      for (const pt of lt.g.parts) {
        ctx.beginPath();
        if (pt.t === 'box') {
          ctx.rect(X(pt.c[0] - pt.h[0]), Y(pt.c[1] + pt.h[1]), 2 * pt.h[0] * em, 2 * pt.h[1] * em);
        } else if (pt.t === 'vee') {
          const P = [[0, 1], [0.5, 0], [1, 1], [1 - wh, 1], [0.5, 2 * wh], [wh, 1]];
          P.forEach((q, i) => (i ? ctx.lineTo(X(q[0]), Y(q[1])) : ctx.moveTo(X(q[0]), Y(q[1]))));
          ctx.closePath();
        } else {
          const cx = X(pt.c[0]), cy = Y(pt.c[1]), ro = pt.r * em, ri = (pt.r - W) * em;
          let a0 = 0, a1 = Math.PI * 2;                       // canvas angles, clockwise
          if (pt.t === 'arcU') { a0 = Math.PI; a1 = Math.PI * 2; }
          if (pt.t === 'arcD') { a0 = 0; a1 = Math.PI; }
          if (pt.t === 'gap') { a0 = -(pt.a0 + Math.PI * 2); a1 = -pt.a1; }
          if (pt.t === 'ring') { ctx.arc(cx, cy, ro, 0, Math.PI * 2); ctx.moveTo(cx + ri, cy); ctx.arc(cx, cy, ri, Math.PI * 2, 0, true); }
          else { ctx.arc(cx, cy, ro, a0, a1); ctx.arc(cx, cy, ri, a1, a0, true); ctx.closePath(); }
        }
        ctx.fill();
      }
      if (tittles && lt.g.tittle) { ctx.beginPath(); ctx.arc(X(lt.g.tittle.c[0]), Y(lt.g.tittle.c[1]), lt.g.tittle.r * em, 0, Math.PI * 2); ctx.fill(); }
    }
    return lay.width * em;
  }

  R.glyphs = { W, TRACK, TIT, L, layout, partExpr, wordGLSL, GLSL_SDF2, fmt: f, v2, drawWord };
})(window.REEL = window.REEL || {});
