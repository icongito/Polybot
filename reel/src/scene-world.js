/* scene-world.js — 2D, 3D and 4D share one raymarched world.
   The "flat" plane chapter is the same scene seen top-down through a camera
   so far away it is effectively orthographic; tilting and dollying in turns
   the paper cut-outs into solids (a dolly-zoom from infinity). Time effects
   (slit-scan, Harris-shutter RGB, chronophotography) evaluate the procedural
   motion at a different time per pixel / per channel.

   Software GL predicates branches, so the SDF is generated per "cast"
   (which glyphs occupy which slot) with every glyph unrolled. */
(function (R) {
  'use strict';
  const G = R.glyphs;
  const MAXP = 5, SLOTS = 6;
  const IDS = { p: 1, l: 2, a: 3, n: 4, e: 5, v: 6, o: 7, u: 8, m: 9, t: 10, i: 11 };
  R.GLYPH_ID = IDS;

  // slot casts: each slot lists up to two glyphs (A, B), chosen by uSlotSel
  const CASTS = {
    plane: ['p', 'l', 'a', 'n', 'e', ''],
    flip: ['p/v', 'l', 'a/l', 'n/u', 'e/m', 'e'],
    volume: ['v', '', 'l', 'u', 'm', 'e'],
    swap: ['v/t', 'i', 'l', 'u', 'm', 'e'],
    time: ['t', 'i', '', '', 'm', 'e'],
  };

  function pivot(pt) { return pt.c || [0.5, 0.5]; }
  function glyphCode(ch, s) {
    const g = G.L[ch];
    let c = '';
    g.parts.forEach((pt, j) => {
      const k = s * MAXP + j;
      c += `      r = pxf(g2, ${k}, ${G.v2(pivot(pt))}); dd = ${G.partExpr(pt, 'r')} * uPartS[${k}]; if (dd < d2) { d2 = dd; if (bp < 1.) pj = ${j}; } if (dd < .003 && uPartPrio[${k}] > bp) { bp = uPartPrio[${k}]; pj = ${j}; }\n`;
    });
    return c;
  }
  function mapCode(cast, ghosts) {
    let s = '';
    const active = [];
    cast.forEach((spec, si) => {
      if (!spec) return;
      active.push(si);
      const [A, Bg] = spec.split('/');
      s += `float slot${si}(vec3 p, float tau, out int pj){
  vec3 q = slotLocal(p, ${si}, tau);
  vec3 bq = abs(q - vec3(0., .5, 0.)) - uSlotBox[${si}];
  float db = (length(max(bq, 0.)) + min(max(bq.x, max(bq.y, bq.z)), 0.)) * uSlotMinS[${si}];
  pj = -1;
  if (db > .08) return db;
  vec2 g2 = vec2(q.x + uSlotAdv[${si}] * .5, q.y), r;
  float d2 = 1e5, dd, bp = 0.; pj = 0;
`;
      if (Bg) s += `  if (uSlotSel[${si}] < .5) {\n${glyphCode(A, si)}  } else {\n${glyphCode(Bg, si)}  }\n`;
      else s += glyphCode(A, si);
      s += `  return extrude(d2, q.z, uSlotDepth[${si}], min(uRound, uSlotDepth[${si}] * .8)) * uSlotMinS[${si}];
}
`;
    });
    s += `float mapFull(vec3 p, float tau, out int id, out int sub){
  float d = 1e5, dd; int pj; id = -1; sub = 0;
`;
    for (const si of active) {
      s += `  if (uSlotB[${si}].w > 0.) { dd = slot${si}(p, tau, pj); if (dd < d) { d = dd; id = pj < 0 ? -2 : 1; sub = ${si * MAXP} + max(pj, 0); } }\n`;
    }
    s += `  vec3 dc = dotAt(tau);
  dd = sdDot(p - dc);
  if (dd < d) { d = dd; id = 2; }
`;
    if (ghosts) {
      s += `  for (int k = 1; k <= 6; k++) {
    vec3 gc = dotAt(tau - float(k) * uGhostDt);
    dd = length(p - gc) - uDotShape.x * (1. - float(k) * .11);
    if (dd < d) { d = dd; id = 3; sub = k; }
  }
`;
    }
    s += '  return d;\n}\n';
    // single-surface distance for normals
    s += `float surfDist(vec3 p, float tau, int id, int sub){
  int pj;
  if (id == 2) return sdDot(p - dotAt(tau));
`;
    if (ghosts) s += `  if (id == 3) return length(p - dotAt(tau - float(sub) * uGhostDt)) - uDotShape.x * (1. - float(sub) * .11);\n`;
    s += `  int s = sub / ${MAXP};\n`;
    for (const si of active) s += `  if (s == ${si}) return slot${si}(p, tau, pj);\n`;
    s += `  return 1e5;\n}\n`;
    return s;
  }

  const HEAD = R.GLSL + G.GLSL_SDF2 + `
uniform vec3 uCamPos, uCamF, uCamR, uCamU;
uniform float uFocal, uPixAng, uDbg, uSunOn;
uniform float uSlotSel[${SLOTS}];
uniform vec3 uSlotPos[${SLOTS}];
uniform mat3 uSlotM[${SLOTS}];
uniform vec3 uSlotScl[${SLOTS}];
uniform float uSlotMinS[${SLOTS}];
uniform vec3 uSlotBox[${SLOTS}];
uniform float uSlotAdv[${SLOTS}];
uniform float uSlotDepth[${SLOTS}];
uniform vec4 uSlotB[${SLOTS}];
uniform vec4 uPart[${SLOTS * MAXP}];
uniform float uPartS[${SLOTS * MAXP}];
uniform float uPartPrio[${SLOTS * MAXP}];
uniform vec3 uBoxMin, uBoxMax;
uniform float uPartCol[${SLOTS * MAXP}];
uniform vec3 uPal[6];
uniform vec3 uDotC, uDotShape, uDotScl;
uniform float uDotEmit, uDotSpec;
uniform vec3 uSunDir, uSunCol, uSkyCol, uBgTop, uBgBot, uRimCol;
uniform float uAmb, uShadowK, uSpec, uFog, uFogStart, uRound, uGloss;
uniform float uTau, uSpin, uSlit, uRGB, uBob, uGhostDt, uTone, uExpo, uDotGlow;
uniform vec3 uShake;
uniform int uZero;
#define ZERO min(uZero, 0)

float extrude(float d2, float z, float h, float r){ vec2 w = vec2(d2 + r, abs(z) - h + r); return min(max(w.x,w.y),0.) + length(max(w,0.)) - r; }
vec2 r2(vec2 v, float a){ float c=cos(a), s=sin(a); return vec2(c*v.x - s*v.y, s*v.x + c*v.y); }
vec2 pxf(vec2 q, int k, vec2 pv){ vec4 T = uPart[k]; vec2 v = q - T.xy - pv; return vec2(T.z*v.x - T.w*v.y, T.w*v.x + T.z*v.y) / uPartS[k] + pv; }
float sdEllipsoid(vec3 p, vec3 r){ float k0 = length(p/r); float k1 = length(p/(r*r)); return k0*(k0-1.0)/max(k1, 1e-6); }
// the dot: a rounded cylinder that morphs flat disc (R>>rb) <-> sphere (R==rb)
float sdDot(vec3 p){
  vec3 q = p / uDotScl;
  vec2 d = vec2(length(q.xz) - (uDotShape.x - uDotShape.y), abs(q.y) - uDotShape.z);
  return (min(max(d.x, d.y), 0.) + length(max(d, 0.)) - uDotShape.y) * min(uDotScl.x, min(uDotScl.y, uDotScl.z));
}

// procedural motion (drives the 4D chapter; zero elsewhere)
float spinOf(int s, float tau){ return uSpin * (sin(tau * 3.1 + float(s) * .9) * 1.2 + tau * 1.7); }
// one bounce per beat; a 1:2 Lissajous sway makes the ghost trail a figure-eight
vec3 dotAt(float tau){ float w = tau * 3.14159265 * 2.1333; return uDotC + vec3(uBob * .55 * sin(2. * w), uBob * abs(sin(w)), 0.); }
vec3 slotLocal(vec3 p, int s, float tau){
  vec3 q = p - uSlotPos[s];
#ifdef PROC_SPIN
  q.xz = r2(q.xz, -spinOf(s, tau));
#endif
  return (uSlotM[s] * q) / uSlotScl[s];
}
`;

  const TAIL = `
float map(vec3 p, float tau){ int a, b; return mapFull(p, tau, a, b); }
// distance usable for shading: bounding proxies report "far"
float mapS(vec3 p, float tau, out bool proxy){ int a, b; float d = mapFull(p, tau, a, b); proxy = a == -2; return d; }
vec2 boxHit(vec3 ro, vec3 rd){
  vec3 inv = 1. / rd;
  vec3 t0 = (uBoxMin - ro) * inv, t1 = (uBoxMax - ro) * inv;
  vec3 tn = min(t0, t1), tf = max(t0, t1);
  return vec2(max(max(tn.x, tn.y), tn.z), min(min(tf.x, tf.y), tf.z));
}
vec3 calcNormal(vec3 p, float tau, int id, int sub){
  vec3 n = vec3(0.);
  for (int i = ZERO; i < 4; i++) {
    vec3 e = .5773 * (2. * vec3(float(((i + 3) >> 1) & 1), float((i >> 1) & 1), float(i & 1)) - 1.);
    n += e * surfDist(p + e * .0015, tau, id, sub);
  }
  return normalize(n);
}
float softShadow(vec3 ro, vec3 rd, float tau){
  vec2 bh = boxHit(ro, rd);
  if (bh.y <= 0. || bh.x >= bh.y) return 1.;
  float res = 1., t = max(bh.x, .02);
  for (int i = 0; i < 40; i++) {
    bool proxy;
    float h = mapS(ro + rd * t, tau, proxy);
    if (!proxy) res = min(res, uShadowK * h / t);
    t += clamp(h, .008, .3);
    if (res < .003 || t > bh.y) break;
  }
  res = clamp(res, 0., 1.);
  return res * res * (3. - 2. * res);
}
float calcAO(vec3 p, vec3 n, float tau){
  if (any(lessThan(p, uBoxMin - .5)) || any(greaterThan(p, uBoxMax + .5))) return 1.;
  float o = 0., s = 1.;
  for (int i = ZERO; i < 4; i++) { float h = .015 + .11 * float(i); vec3 q = p + n * h; bool proxy; float dm = mapS(q, tau, proxy); if (proxy) dm = 1e3; o += (h - min(dm, q.y)) * s; s *= .72; }
  return clamp(1. - 2.1 * o, 0., 1.);
}
vec3 skyCol(vec3 rd){ return mix(uBgBot, uBgTop, smoothstep(-.05, .6, rd.y)); }

vec3 render(vec2 px, float tau){
  if (mod(floor(uDbg / 8.), 2.) > .5) return vec3(.5);
  vec2 uv = (px - vec2(960., 540.)) / 540.;
  uv = r2(uv, uShake.z) + uShake.xy / 540.;
  vec3 ro = uCamPos;
  vec3 rd = normalize(uCamF * uFocal + uCamR * uv.x - uCamU * uv.y);
  float tfl = rd.y < 0. ? -ro.y / rd.y : 1e9;
  int id = -1, sub = 0;
  float t = tfl;
  bool hit = false;
  int steps = 0;
  vec2 bh = boxHit(ro, rd);
  if (bh.x < bh.y && bh.y > 0.) {
    float tt = max(bh.x, 0.), tend = min(bh.y, tfl);
    for (int i = 0; i < 100; i++) {
      float h = mapFull(ro + rd * tt, tau, id, sub);
      steps = i;
      if (h < tt * uPixAng * .5 + .00005 && id >= 1) { hit = true; break; }
      tt += h;
      if (tt > tend) break;
    }
    if (hit) t = tt;
  }
  if (mod(floor(uDbg / 4.), 2.) > .5) return vec3(float(steps) / 100., float(steps) / 30., hit ? .0 : 1.);
  vec3 bg = skyCol(rd);
  if (!hit) { if (tfl > 1e8) return bg; id = 0; }
  vec3 p = ro + rd * t;
  vec3 n = id == 0 ? vec3(0., 1., 0.) : calcNormal(p, tau, id, sub);
  vec3 alb; float spec = uSpec, shin = 48.;
  if (id == 0) {
    alb = uPal[4];
    float g = vnoise(p.xz * 60.) * .5 + vnoise(p.xz * 13.) * .5;
    alb *= .96 + .06 * g;
  } else if (id == 1) {
    alb = uPal[int(uPartCol[sub] + .5)];
    alb *= .97 + .05 * vnoise(p.xy * 50. + p.z * 30.);
  } else if (id == 2) {
    alb = uPal[2]; spec = uDotSpec; shin = 90.;
  } else {
    alb = mix(uPal[2], uPal[4] * .6, float(sub) / 7.); spec = uDotSpec * .5;
  }
  vec3 L = normalize(uSunDir);
  vec3 dcl = dotAt(tau);
  vec3 Lp = dcl - p; float dl = max(length(Lp), 1e-4); Lp /= dl;
  // one shadow ray per pixel: toward the sun by day, toward the glowing dot by night
  bool wantSh = mod(uDbg, 2.) < .5 && (uSunOn > .5 || (uDotEmit > 0. && id != 2));
  float shv = wantSh ? softShadow(p + n * .006, uSunOn > .5 ? L : Lp, tau) : 1.;
  float sh = uSunOn > .5 ? shv : 1.;
  float dif = max(dot(n, L), 0.) * sh;
  float ao = mod(floor(uDbg / 2.), 2.) < .5 ? calcAO(p, n, tau) : 1.;
  float skyw = .6 + .4 * n.y;
  vec3 lin = uSunCol * dif + uSkyCol * uAmb * skyw * ao;
  lin += uPal[4] * uAmb * .25 * clamp(-n.y * .5 + .5, 0., 1.) * ao;
  vec3 col = alb * lin;
  vec3 hv = normalize(L - rd);
  float fres = pow(1. - max(dot(n, -rd), 0.), 5.);
  col += uSunCol * pow(max(dot(n, hv), 0.), shin) * spec * sh;
  vec3 env = skyCol(reflect(rd, n));
  if (id == 1) col += env * (uGloss * (.04 + .5 * fres)) * ao;
  if (id >= 2) col += mix(env, vec3(dot(env, vec3(.33))), .7) * (uGloss * (.02 + .35 * fres));
  col += uRimCol * pow(1. - max(dot(n, -rd), 0.), 3.) * (id == 0 ? 0. : 1.) * ao;
  if (uDotEmit > 0.) {
    float att = 1. / (1. + dl * dl * 1.3);
    float occ = (id == 2 || uSunOn > .5) ? 1. : shv * .8 + .2;
    col += alb * uPal[2] * max(dot(n, Lp), 0.) * att * uDotEmit * 7. * occ;
    if (id == 2) col += uPal[2] * uDotEmit * 2.2;
    if (id == 3) col = mix(col, uPal[2] * uDotEmit * 1.6, pow(1. - float(sub) / 7., 1.5));
  }
  if (id == 2) col += uPal[2] * uDotGlow;
  float fog = 1. - exp(-max(t - uFogStart, 0.) * uFog);
  return mix(col, bg, fog);
}

void main(){
  vec2 px = designPx();
  float tau = uTau - uSlit * (px.y / 1080.);
  vec3 col = vec3(0.);
  int n = uRGB > 0. ? 3 : 1;
  for (int c = ZERO; c < 3; c++) {
    if (c >= n) break;
    vec3 v = render(px, tau - float(c) * uRGB);
    if (n == 1) col = v; else col[c] = v[c];
  }
  // filmic shoulder for the lit 3D chapters (identity while flat)
  vec3 x = col * uExpo;
  vec3 tm = clamp((x * (2.51 * x + .03)) / (x * (2.43 * x + .59) + .14), 0., 1.);
  col = mix(col, tm, uTone);
  fragColor = vec4(lin2srgb(col), 1.);
}`;

  const progs = {};
  function layout(word, track = G.TRACK) {
    const lay = G.layout(word, track);
    return lay.letters.map((l) => ({ ch: l.ch, cx: l.x + l.g.adv / 2 - lay.width / 2, adv: l.g.adv }));
  }
  R.worldLayout = layout;

  R.sceneWorld = {
    SLOTS, MAXP, IDS, CASTS,
    source(k) { const head = k === 'time' ? HEAD.replace('precision highp int;', 'precision highp int;\n#define PROC_SPIN') : HEAD; return head + mapCode(CASTS[k], k === 'time') + TAIL; },
    progs,
    init() {
      for (const k in CASTS) {
        const head = k === 'time' ? HEAD.replace('precision highp int;', 'precision highp int;\n#define PROC_SPIN') : HEAD;
        progs[k] = new R.Program(head + mapCode(CASTS[k], k === 'time') + TAIL, 'world-' + k);
      }
    },
    render(target, st, env) {
      const prog = progs[st.cast];
      const U = {
        uCamPos: st.cam.pos, uCamF: st.cam.f, uCamR: st.cam.r, uCamU: st.cam.u, uFocal: st.cam.focal,
        uPixAng: 1 / (st.cam.focal * 540), uDbg: R.dbg || 0, uZero: 0, uSunOn: Math.max(...st.light.sunCol) > 0.15 ? 1 : 0,
        uScale: env.scale, uJitter: env.jitter, uShake: [env.shake[0] * 0.5, env.shake[1] * 0.5, env.shake[2]],
      };
      const cast = CASTS[st.cast];
      const sel = [], pos = [], mats = [], scl = [], mins = [], adv = [], dep = [], bnd = [], part = [], pscl = [], pcol = [], sbox = [], prio = [];
      const bmin = [1e9, 1e9, 1e9], bmax = [-1e9, -1e9, -1e9];
      const grow = (c, r) => { for (let i = 0; i < 3; i++) { bmin[i] = Math.min(bmin[i], c[i] - r); bmax[i] = Math.max(bmax[i], c[i] + r); } };
      for (let s = 0; s < SLOTS; s++) {
        const sl = st.slots[s];
        const spec = cast[s] || '';
        const opts = spec.split('/');
        const on = sl && sl.ch && opts.includes(sl.ch);
        sel.push(on && opts.length > 1 && sl.ch === opts[1] ? 1 : 0);
        pos.push(...(sl ? sl.pos : [0, 0, 0]));
        mats.push(...slotMatrix(sl ? sl.rot : [0, 0, 0]));
        const sc = sl ? sl.scl.map((v) => Math.max(1e-3, v)) : [1, 1, 1];
        scl.push(...sc);
        mins.push(Math.min(...sc));
        adv.push(sl ? sl.adv : 1);
        dep.push(sl ? sl.depth : 0.1);
        let br = 1.25, pad = 0;
        if (sl) for (const pp of sl.parts || []) { pad = Math.max(pad, Math.hypot(pp[0], pp[1]) + Math.max(0, 1 / Math.max(pp[3], 0.05) - 1) * 0.1 + Math.abs(pp[2]) * 0.6); }
        br += pad;
        sbox.push((sl ? sl.adv : 1) / 2 + 0.06 + pad, 1.08 + pad, (sl ? sl.depth : 0.1) + 0.03 + pad);
        br *= Math.max(...sc);
        // w <= 0 disables the slot
        bnd.push(sl ? sl.pos[0] : 0, sl ? sl.pos[1] + 0.5 : 0, sl ? sl.pos[2] : 0, on ? br : -1);
        if (on) grow([sl.pos[0], sl.pos[1] + 0.5, sl.pos[2]], br);
        for (let j = 0; j < MAXP; j++) {
          const pp = sl && sl.parts && sl.parts[j] ? sl.parts[j] : [0, 0, 0, 1];
          part.push(pp[0], pp[1], Math.cos(-pp[2]), Math.sin(-pp[2]));
          pscl.push(Math.max(0.001, pp[3]));
          const ci = sl && sl.cols ? sl.cols[j] ?? sl.cols[0] : 0;
          pcol.push(ci);
          prio.push(ci === 1 ? 3 : ci === 2 ? 2.5 : 2);   // ink prints on top
        }
      }
      Object.assign(U, {
        uSlotSel: sel, uSlotBox: sbox, uSlotPos: pos, uSlotM: mats, uSlotScl: scl, uSlotMinS: mins, uSlotAdv: adv, uSlotDepth: dep, uSlotB: bnd,
        uPart: part, uPartS: pscl, uPartCol: pcol, uPartPrio: prio, uPal: st.pal.flat(),
        uDotC: st.dot.c, uDotShape: [st.dot.R, Math.min(st.dot.R, st.dot.rb), st.dot.hh || 0], uDotScl: (st.dot.scl || [1, 1, 1]).map((v) => Math.max(0.05, v)),
        uDotEmit: st.dot.emit || 0, uDotSpec: st.dot.spec ?? 0.6, uRimCol: st.light.rim || [0, 0, 0],
        uSunDir: st.light.sun, uSunCol: st.light.sunCol, uSkyCol: st.light.sky, uBgTop: st.light.bgTop, uBgBot: st.light.bgBot,
        uAmb: st.light.amb, uFogStart: st.light.fogStart ?? 12, uShadowK: st.light.shadowK, uSpec: st.light.spec, uFog: st.light.fog, uRound: st.light.round ?? 0.03,
        uGloss: st.light.gloss ?? 0.3,
        uTau: st.fx.tau || 0, uSpin: st.fx.spin || 0, uSlit: st.fx.slit || 0, uRGB: st.fx.rgb || 0, uBob: st.fx.bob || 0,
        uGhostDt: st.fx.ghostDt || 0.03, uTone: st.light.tone || 0, uExpo: st.light.expo || 1, uDotGlow: st.dot.glow || 0,
      });
      // object bounds: letters + dot (+ its bounce / ghosts)
      const dr = st.dot.R * Math.max(...(st.dot.scl || [1, 1, 1]));
      grow(st.dot.c, dr + 0.02);
      if (st.fx.bob) {
        const sw = st.fx.bob * 0.55;
        grow([st.dot.c[0] - sw, st.dot.c[1] + st.fx.bob, st.dot.c[2]], dr + 0.02);
        grow([st.dot.c[0] + sw, st.dot.c[1] + st.fx.bob, st.dot.c[2]], dr + 0.02);
      }
      if (st.cast === 'time') {
        // procedural spin sweeps letters around their axes
        for (let s = 0; s < SLOTS; s++) if (bnd[s * 4 + 3] > 0) grow([bnd[s * 4], bnd[s * 4 + 1], bnd[s * 4 + 2]], bnd[s * 4 + 3]);
      }
      U.uBoxMin = [bmin[0], Math.max(-2.5, bmin[1]), bmin[2]];
      U.uBoxMax = bmax;
      R.draw(prog, target, U);
    },
  };

  // world->slot-local rotation, same op order as the shader used to apply
  function slotMatrix(rv) {
    const f = (v) => {
      let [x, y, z] = v;
      let c = Math.cos(-rv[1]), s = Math.sin(-rv[1]);
      [x, z] = [c * x - s * z, s * x + c * z];
      c = Math.cos(-rv[0]); s = Math.sin(-rv[0]);
      [y, z] = [c * y - s * z, s * y + c * z];
      c = Math.cos(-rv[2]); s = Math.sin(-rv[2]);
      [x, y] = [c * x - s * y, s * x + c * y];
      return [x, y, z];
    };
    return [...f([1, 0, 0]), ...f([0, 1, 0]), ...f([0, 0, 1])];
  }

  // camera from orbit parameters: target, yaw, pitch (elevation), distance, view height at target
  R.orbitCam = function (tg, yaw, pitch, dist, viewH, roll = 0) {
    const cp = Math.cos(pitch), sp = Math.sin(pitch);
    const pos = [tg[0] + dist * cp * Math.sin(yaw), tg[1] + dist * sp, tg[2] + dist * cp * Math.cos(yaw)];
    const f = norm([tg[0] - pos[0], tg[1] - pos[1], tg[2] - pos[2]]);
    let r = [Math.cos(yaw), 0, -Math.sin(yaw)];
    let u = cross(r, f);
    if (roll) { const c = Math.cos(roll), s = Math.sin(roll); const r2 = r.map((v, i) => v * c + u[i] * s); u = u.map((v, i) => v * c - r[i] * s); r = r2; }
    const focal = dist / (viewH / 2);
    return { pos, f, r, u, focal };
  };
  function norm(v) { const l = Math.hypot(v[0], v[1], v[2]); return [v[0] / l, v[1] / l, v[2] / l]; }
  function cross(a, b) { return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]; }
  R.norm3 = norm;
})(window.REEL = window.REEL || {});
