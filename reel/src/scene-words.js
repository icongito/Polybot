/* scene-words.js — single-word flash frames for the climax: Roboto Flex
   driven across its whole width axis (25 -> 151) inside one cut. */
(function (R) {
  'use strict';
  let canvas, ctx, tex;
  R.sceneWords = {
    init() { this.resize(); },
    resize() {
      canvas = R.canvas2d(Math.round(R.W * R.scale), Math.round(R.H * R.scale));
      ctx = canvas.getContext('2d');
      if (tex) R.gl.deleteTexture(tex.tex);
      tex = new R.CanvasTex(canvas);
    },
    // p: { bg, fg, word, wdth, wght, size, dy, fit (0..1: fraction of frame width) }
    render(target, p, env) {
      const s = env.scale;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.fillStyle = R.rgba(p.bg); ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.setTransform(s, 0, 0, s, 0, 0);
      ctx.translate(R.W / 2 + env.shake[0], R.H / 2 + env.shake[1] + (p.dy || 0));
      ctx.font = R.fonts.flex(p.size, p.wdth, p.wght);
      ctx.textAlign = 'center';
      ctx.textBaseline = 'alphabetic';
      if ('letterSpacing' in ctx) ctx.letterSpacing = (p.track || 0) + 'px';
      const m = ctx.measureText(p.word);
      // optional horizontal squeeze to a target width (keeps the word edge-to-edge)
      if (p.fit) { const k = (R.W * p.fit) / m.width; ctx.scale(k, 1); }
      const asc = m.actualBoundingBoxAscent, desc = m.actualBoundingBoxDescent;
      ctx.fillStyle = R.rgba(p.fg);
      ctx.fillText(p.word, 0, (asc - desc) / 2);
      if (p.dot) {
        ctx.setTransform(s, 0, 0, s, 0, 0);
        ctx.beginPath(); ctx.arc(p.dot[0], p.dot[1], p.dot[2], 0, Math.PI * 2);
        ctx.fillStyle = R.rgba(p.acc); ctx.fill();
      }
      if ('letterSpacing' in ctx) ctx.letterSpacing = '0px';
      tex.upload();
      R.draw(R.blitProg, target, { uTex: tex, uAlpha: 1 });
    },
  };
})(window.REEL = window.REEL || {});
