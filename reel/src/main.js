/* main.js — boot, frame orchestration (motion-blur accumulation), playback. */
(function (R) {
  'use strict';
  let accum, sceneT, blit, uiCanvas, uiTex;

  // Halton(2,3) for subpixel jitter
  const halton = (i, b) => { let f = 1, r = 0; i += 1; while (i > 0) { f /= b; r += f * (i % b); i = Math.floor(i / b); } return r; };

  R.boot = async function (canvas, scale = 1) {
    R.canvas = canvas;
    R.scale = scale;
    canvas.width = Math.round(R.W * scale);
    canvas.height = Math.round(R.H * scale);
    R.initGL(canvas);
    await R.fonts.load();
    blit = new R.Program(R.GLSL_BLIT, 'blit');
    R.blitProg = blit;
    alloc();
    R.post.init(canvas.width, canvas.height);
    for (const k of R.SCENES) R[k].init();
    R.ready = true;
  };

  function alloc() {
    const w = R.canvas.width, h = R.canvas.height;
    for (const t of [accum, sceneT, R.tmpA, R.tmpB]) if (t) t.dispose();
    accum = new R.Target(w, h);
    sceneT = new R.Target(w, h);
    R.tmpA = new R.Target(w, h);
    R.tmpB = new R.Target(w, h);
    uiCanvas = R.canvas2d(w, h);
    if (uiTex) R.gl.deleteTexture(uiTex.tex);
    uiTex = new R.CanvasTex(uiCanvas);
  }

  // change internal resolution without recompiling anything
  R.resize = function (scale) {
    R.scale = scale;
    R.canvas.width = Math.round(R.W * scale);
    R.canvas.height = Math.round(R.H * scale);
    alloc();
    R.post.resize(R.canvas.width, R.canvas.height);
    for (const k of R.SCENES) if (R[k].resize) R[k].resize();
  };

  // Render time t (seconds) to the default framebuffer.
  R.renderAt = function (t, opts = {}) {
    const N = opts.subframes || 1;
    const shutter = opts.shutter ?? 0.5;        // fraction of frame interval
    const env = { scale: R.scale, jitter: [0, 0], shake: [0, 0, 0] };
    if (N === 1) {
      env.shake = R.shakeAt(t);
      R.director(t, accum, env);
    } else {
      R.clear(accum, [0, 0, 0, 0]);
      // shutter interval, clipped so a frame never blends across a hard cut
      let a = t - 0.5 * shutter / R.FPS, z = t + 0.5 * shutter / R.FPS;
      for (const c of R.CUT_TIMES || []) {
        if (c > a && c <= t) a = c;
        if (c > t && c < z) z = c - 1e-6;
      }
      for (let i = 0; i < N; i++) {
        const ts = a + ((i + 0.5) / N) * (z - a);
        const e = { scale: R.scale, jitter: [halton(i, 2) - 0.5, halton(i, 3) - 0.5], shake: R.shakeAt(ts) };
        R.director(ts, sceneT, e);
        R.draw(blit, accum, { uTex: sceneT.tex, uAlpha: 1 / N }, 'add');
      }
    }
    const ui = R.hud ? R.hud.draw(uiCanvas, t) : false;
    if (ui) uiTex.upload();
    R.post.run(accum, ui ? uiTex : null, Object.assign({ t }, R.lensAt(t)));
  };
})(window.REEL = window.REEL || {});
