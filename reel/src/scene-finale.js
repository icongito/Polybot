/* scene-finale.js — the full stop. Everything collapses back to the dot; the
   sentence, set in the reel's own constructed alphabet, arrives and parks
   against it: "point made."  The last frame is the first frame, so the reel
   loops seamlessly. */
(function (R) {
  'use strict';
  const G = R.glyphs;
  const EM = 145;                       // the period (r = 0.16 em) is the dot of frame 0
  const DOT_R = R.DOT0;
  const BASE2 = R.H / 2 + DOT_R;        // "made." sits so its full stop is the frame centre
  const BASE1 = BASE2 - 1.85 * EM;
  const W2 = G.layout('made').width * EM;
  const X0 = R.W / 2 - DOT_R - G.TRACK * EM - W2;
  let canvas, ctx, tex;

  R.sceneFinale = {
    EM, DOT_R, X0, BASE1, BASE2,
    init() { this.resize(); },
    resize() {
      canvas = R.canvas2d(Math.round(R.W * R.scale), Math.round(R.H * R.scale));
      ctx = canvas.getContext('2d');
      if (tex) R.gl.deleteTexture(tex.tex);
      tex = new R.CanvasTex(canvas);
    },
    // p: { bg, fg, acc, dot:[x,y,r], squash, x1, x2 (line offsets), textA, caption (0..1), captionLines }
    render(target, p, env) {
      const s = env.scale;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.fillStyle = R.rgba(p.bg); ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.setTransform(s, 0, 0, s, 0, 0);
      ctx.translate(env.shake[0], env.shake[1]);
      if (p.textA > 0) {
        const fill = R.rgba(p.fg, p.textA);
        G.drawWord(ctx, 'point', X0 + p.x1, BASE1, EM, fill);
        G.drawWord(ctx, 'made', X0 + p.x2, BASE2, EM, fill);
      }
      if (p.caption > 0) {
        ctx.font = R.fonts.mono(17, 500);
        if ('letterSpacing' in ctx) ctx.letterSpacing = '1.7px';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'alphabetic';
        const lines = p.captionLines || [];
        const x0 = R.W / 2 + 64;
        lines.forEach((ln, i) => {
          const k = R.clamp(p.caption * lines.length - i);
          if (k <= 0) return;
          ctx.fillStyle = R.rgba(i === 0 ? p.acc : p.fg, i === 0 ? 1 : 0.62);
          ctx.fillText(ln.slice(0, Math.ceil(ln.length * k)), x0, BASE2 + i * 29);
        });
        if ('letterSpacing' in ctx) ctx.letterSpacing = '0px';
      }
      if (p.dot) {
        const [x, y, rr] = p.dot;
        ctx.save(); ctx.translate(x, y); ctx.scale(p.squash[0], p.squash[1]);
        ctx.beginPath(); ctx.arc(0, 0, rr, 0, Math.PI * 2);
        ctx.fillStyle = R.rgba(p.acc); ctx.fill();
        ctx.restore();
      }
      tex.upload();
      R.draw(R.blitProg, target, { uTex: tex, uAlpha: 1 });
    },
  };
})(window.REEL = window.REEL || {});
