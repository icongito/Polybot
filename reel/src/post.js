/* post.js — the "lens": bloom, radial chromatic aberration, flash, vignette,
   UI overlay and film grain. Applied once per output frame. */
(function (R) {
  'use strict';
  const BRIGHT_FS = R.GLSL + `
in vec2 vUv;
uniform sampler2D uTex;
uniform float uThresh;
void main(){
  vec2 px = 1. / vec2(textureSize(uTex, 0));
  vec3 c = vec3(0.);
  // 4-tap box downsample
  c += texture(uTex, vUv + px*vec2(-1.,-1.)).rgb;
  c += texture(uTex, vUv + px*vec2( 1.,-1.)).rgb;
  c += texture(uTex, vUv + px*vec2(-1., 1.)).rgb;
  c += texture(uTex, vUv + px*vec2( 1., 1.)).rgb;
  c *= .25;
  float l = max(c.r, max(c.g, c.b));
  float k = smoothstep(uThresh, uThresh + .35, l);
  fragColor = vec4(c * k, 1.);
}`;
  const BLUR_FS = R.GLSL + `
in vec2 vUv;
uniform sampler2D uTex;
uniform vec2 uDir;
void main(){
  vec2 px = uDir / vec2(textureSize(uTex, 0));
  // 9-tap gaussian via linear sampling (5 fetches)
  vec3 c = texture(uTex, vUv).rgb * .2270270270;
  c += texture(uTex, vUv + px*1.3846153846).rgb * .3162162162;
  c += texture(uTex, vUv - px*1.3846153846).rgb * .3162162162;
  c += texture(uTex, vUv + px*3.2307692308).rgb * .0702702703;
  c += texture(uTex, vUv - px*3.2307692308).rgb * .0702702703;
  fragColor = vec4(c, 1.);
}`;
  const POST_FS = R.GLSL + `
in vec2 vUv;
uniform sampler2D uScene, uBloomA, uBloomB, uUI;
uniform float uCA, uGrain, uVig, uBloom, uTime, uUIOn, uInvert;
uniform vec4 uFlash;
void main(){
  vec2 uv = vUv;
  vec2 d = uv - .5;
  float r2 = dot(d * vec2(1.7778, 1.), d * vec2(1.7778, 1.));
  vec3 col;
  if (uCA > 0.0005) {
    vec2 off = d * uCA * (.35 + r2 * 1.6);
    col.r = texture(uScene, uv - off).r;
    col.g = texture(uScene, uv - off * .35).g;
    col.b = texture(uScene, uv + off).b;
  } else col = texture(uScene, uv).rgb;
  col += (texture(uBloomA, uv).rgb * .6 + texture(uBloomB, uv).rgb * .8) * uBloom;
  col = mix(col, uFlash.rgb, uFlash.a);
  col = mix(col, vec3(1.) - clamp(col, 0., 1.), uInvert);
  if (uUIOn > .5) { vec4 ui = texture(uUI, uv); col = col * (1. - ui.a) + ui.rgb; }
  col *= 1. - uVig * smoothstep(.15, 1.3, r2);
  // soft highlight rolloff (keeps HDR flashes filmic)
  col = col / (1. + max(col - 1., 0.) * .6);
  float g = hash12(floor(gl_FragCoord.xy) + fract(uTime * 13.37) * 917.) - .5;
  float g2 = hash12(floor(gl_FragCoord.xy * .5) + fract(uTime * 7.1) * 311.) - .5;
  float lum = dot(col, vec3(.299,.587,.114));
  col += (g * .75 + g2 * .5) * uGrain * (.55 + .45 * (1. - abs(lum * 2. - 1.)));
  fragColor = vec4(clamp(col, 0., 1.), 1.);
}`;

  let bright, blur, post, bA1, bA2, bB1, bB2;
  R.post = {
    init(w, h) {
      bright = new R.Program(BRIGHT_FS, 'bright');
      blur = new R.Program(BLUR_FS, 'blur');
      post = new R.Program(POST_FS, 'post');
      this.resize(w, h);
    },
    resize(w, h) {
      for (const t of [bA1, bA2, bB1, bB2]) if (t) t.dispose();
      bA1 = new R.Target(w >> 2, h >> 2); bA2 = new R.Target(w >> 2, h >> 2);
      bB1 = new R.Target(w >> 3, h >> 3); bB2 = new R.Target(w >> 3, h >> 3);
    },
    run(sceneTarget, uiTex, p) {
      // bloom chain
      R.draw(bright, bA1, { uTex: sceneTarget.tex, uThresh: p.thresh ?? 0.92 });
      R.draw(blur, bA2, { uTex: bA1.tex, uDir: [1, 0] });
      R.draw(blur, bA1, { uTex: bA2.tex, uDir: [0, 1] });
      R.draw(blur, bB1, { uTex: bA1.tex, uDir: [1.5, 0] });
      R.draw(blur, bB2, { uTex: bB1.tex, uDir: [0, 1.5] });
      R.draw(blur, bB1, { uTex: bB2.tex, uDir: [2.5, 0] });
      R.draw(blur, bB2, { uTex: bB1.tex, uDir: [0, 2.5] });
      R.draw(post, null, {
        uScene: sceneTarget.tex, uBloomA: bA1.tex, uBloomB: bB2.tex, uUI: uiTex ? uiTex.tex : bA1.tex,
        uUIOn: uiTex ? 1 : 0, uCA: p.ca || 0, uGrain: p.grain ?? 0.045, uVig: p.vig ?? 0.25,
        uBloom: p.bloom ?? 0.6, uTime: p.t || 0, uFlash: p.flash || [0, 0, 0, 0], uInvert: p.invert || 0,
      });
    },
  };
})(window.REEL = window.REEL || {});
