/* scene-point.js — 0D. The dot detonates into a halftone field; the shock
   front "develops" the word `point` out of thousands of points, with the
   protagonist dot sitting as the tittle of the i. */
(function (R) {
  'use strict';
  const G = R.glyphs;
  const CELL = 18;                 // halftone pitch (world px)
  const GX = Math.ceil(R.W / CELL) + 4, GY = Math.ceil(R.H / CELL) + 4; // + margin
  const MARGIN = 2;
  const EM = 340;                  // px per x-height
  // tittle of the i sits exactly at frame centre
  const lay = G.layout('point');
  const iLetter = lay.letters.find((l) => l.ch === 'i');
  const titG = [iLetter.x + G.W / 2, G.TIT.y];
  const ORIGIN = [R.W / 2 - titG[0] * EM, R.H / 2 + titG[1] * EM]; // baseline-left, y down
  const TIT_R = G.TIT.r * EM;

  const FIELD_FS = R.GLSL + G.GLSL_SDF2 + G.wordGLSL('sdWord', 'point') + `
uniform float uT, uBoom, uInvX, uCollapse, uEm, uCell, uDev;
uniform vec2 uOrigin, uCenter;
void main(){
  vec2 cell = floor(gl_FragCoord.xy) - float(${MARGIN});
  vec2 c = (cell + .5) * uCell;                       // world px, y down
  float d0 = length(c - uCenter);
  // shock front
  float speed = 2900.;
  float front = uBoom * speed;
  float behind = front - d0;
  float crest = exp(-pow((d0 - front) / 70., 2.)) * step(0., uBoom);
  // letter coverage
  vec2 g = vec2(c.x - uOrigin.x, uOrigin.y - c.y) / uEm;
  float sd = sdWord(g) * uEm;
  float inside = smoothstep(uCell*.9, -uCell*.9, sd);
  float develop = smoothstep(0., 420., behind) * uDev;
  float n = fbm(c * .0045 + vec2(uT*.35, -uT*.2));
  float rOut = .07 + .12 * n;
  float rIn = .66;
  float rNorm = mix(rOut, rIn, inside * develop);
  // inversion wave: letters empty out while the ground fills in
  float invw = smoothstep(uInvX + 70., uInvX - 70., c.x);
  float crestInv = exp(-pow((c.x - uInvX) / 90., 2.));
  float rInv = mix(.63 + .05 * n, .05 + .06 * n, inside);
  float r = mix(rNorm, rInv, invw * develop);
  float age = max(behind, 0.) / speed;
  r *= 1. + .45 * sin(age * 26.) * exp(-age * 5.5) * step(0., behind);
  r *= step(0., behind + 30.);
  r += crest * .38 + crestInv * .22 * develop;
  // collapse: the field is eaten from the edges toward the dot
  float k = smoothstep(uCollapse, uCollapse - 260., d0);
  r *= k;
  float acc = sat(crest * 1.4 + crestInv * .9 * develop);
  fragColor = vec4(max(r, 0.), acc, inside, 1.);
}`;

  const DOTS_FS = R.GLSL + `
uniform sampler2D uField;
uniform float uZoom, uCell, uT, uFront, uRefr, uZoomRot;
uniform vec2 uCenter;
uniform vec2 uFocus;
uniform vec3 uShake;
uniform vec3 uBg, uInk, uAcc;
uniform vec4 uDot;       // x, y, r, glow
uniform vec2 uSquash;    // x/y scale of the dot
uniform float uDotRot;
void main(){
  vec2 px = designPx();
  px = rot(uShake.z) * (px - vec2(960.,540.)) + vec2(960.,540.) + uShake.xy;
  vec2 w = uFocus + rot(uZoomRot) * (px - uFocus) / uZoom;
  vec2 dv = w - uCenter; float dl = length(dv);
  w -= dv / max(dl, 1.) * exp(-pow((dl - uFront) / 110., 2.)) * uRefr;
  vec2 cc = w / uCell;
  vec2 ci = floor(cc);
  float aa = .8 / (uZoom * uScale);
  float cov = 0., acc = 0.;
  for(int j=-1;j<=1;j++) for(int i=-1;i<=1;i++){
    vec2 cid = ci + vec2(i,j);
    vec4 f = texelFetch(uField, ivec2(cid) + ivec2(${MARGIN}), 0);
    float r = f.r * uCell;
    float d = length(w - (cid + .5) * uCell) - r;
    float c = smoothstep(aa, -aa, d) * step(.001, f.r);
    if (c > cov) { cov = c; acc = f.g; }
  }
  vec3 dotc = mix(uInk, uAcc * 1.25, acc);
  vec3 col = mix(uBg, dotc, cov);
  // protagonist
  vec2 dq = rot(uDotRot) * (px - uDot.xy);
  dq /= uSquash;
  float dd = length(dq) - uDot.z;
  float daa = .8 / uScale / min(uSquash.x, uSquash.y);
  float dc = smoothstep(daa, -daa, dd);
  float glow = uDot.w * exp(-max(dd,0.) / 60.) * .6;
  col += uAcc * glow;
  col = mix(col, uAcc * (1. + uDot.w * .6), dc);
  fragColor = vec4(col, 1.);
}`;

  let fieldProg, dotsProg, fieldTarget;

  R.scenePoint = {
    CELL, EM, ORIGIN, TIT_R,
    center: [R.W / 2, R.H / 2],
    init() {
      fieldProg = new R.Program(FIELD_FS, 'point-field');
      dotsProg = new R.Program(DOTS_FS, 'point-dots');
      fieldTarget = new R.Target(GX, GY, { nearest: true });
    },
    // p: parameter block (see state())
    render(target, p, env) {
      R.draw(fieldProg, fieldTarget, {
        uT: p.t, uBoom: p.boom, uInvX: p.invX, uCollapse: p.collapse,
        uEm: EM, uCell: CELL, uDev: p.dev, uOrigin: ORIGIN, uCenter: this.center,
      });
      R.draw(dotsProg, target, {
        uField: fieldTarget.tex, uZoom: p.zoom, uFocus: p.focus, uCell: CELL, uT: p.t,
        uFront: Math.max(p.boom, 0) * 2900, uRefr: p.refr || 0, uZoomRot: p.zoomRot || 0, uCenter: this.center,
        uShake: env.shake, uBg: p.bg, uInk: p.ink, uAcc: p.acc,
        uDot: [p.dot[0], p.dot[1], p.dot[2], p.glow], uSquash: p.squash, uDotRot: p.dotRot || 0,
        uScale: env.scale, uJitter: env.jitter,
      });
    },
  };
})(window.REEL = window.REEL || {});
