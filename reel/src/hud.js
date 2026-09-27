/* hud.js — a quiet frame around the piece: dimension counter, timecode and a
   4-step beat sequencer that makes the (silent) tempo visible. */
(function (R) {
  'use strict';
  const CH = [
    [0, '0D', 'point'], [5, '1D', 'line'], [9, '2D', 'plane'], [12, '3D', 'volume'], [19, '4D', 'time'],
  ];
  const pad = (n, w = 2) => String(Math.floor(n)).padStart(w, '0');

  R.hud = {
    // state from the director: { on, color, chapter override, alpha }
    draw(canvas, t) {
      const st = R.hudState ? R.hudState(t) : null;
      const ctx = canvas.getContext('2d');
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      if (!st || st.alpha <= 0) return true;
      const s = R.scale;
      ctx.setTransform(s, 0, 0, s, 0, 0);
      ctx.globalAlpha = st.alpha;
      ctx.fillStyle = R.rgba(st.color);
      ctx.strokeStyle = R.rgba(st.color);
      ctx.font = R.fonts.mono(15, 500);
      ctx.textBaseline = 'alphabetic';
      if ('letterSpacing' in ctx) ctx.letterSpacing = '1.5px';
      const M = 54, top = 62, bot = R.H - 50;
      const B = t / R.BEAT;

      // top-left: title
      ctx.textAlign = 'left';
      ctx.fillText('MOTION REEL — 2026', M, top);
      // top-right: dimension
      let ch = CH[0];
      for (const c of CH) if (B >= c[0]) ch = c;
      if (st.chapter) ch = st.chapter;
      ctx.textAlign = 'right';
      ctx.fillText(`${ch[1]} / ${ch[2].toUpperCase()}`, R.W - M, top);
      // bottom-left: timecode
      const f = Math.round(t * R.FPS);
      ctx.textAlign = 'left';
      const tc = st.tc != null ? st.tc : t;
      const ff = Math.floor(tc * R.FPS + 1e-6);
      ctx.fillText(`${pad(tc / 60)}:${pad(tc % 60)}:${pad(ff % R.FPS)}`, M, bot);
      // bottom-right: tempo + sequencer
      const beat = Math.floor(B + 1e-6);
      const inBar = beat % 4;
      const sx = R.W - M, sq = 9, gap = 7;
      for (let i = 0; i < 4; i++) {
        const x = sx - (4 - i) * (sq + gap) + gap;
        const y = bot - sq + 1;
        if (i === inBar) {
          const k = 1 - R.clamp((B - beat) * 2.2);
          ctx.globalAlpha = st.alpha * (0.55 + 0.45 * k);
          ctx.fillRect(x, y, sq, sq);
          ctx.globalAlpha = st.alpha;
        } else {
          ctx.lineWidth = 1.2;
          ctx.strokeRect(x + 0.6, y + 0.6, sq - 1.2, sq - 1.2);
        }
      }
      ctx.textAlign = 'right';
      ctx.fillText(`128 BPM   ${pad(Math.floor(beat / 4) + 1)}.${inBar + 1}`, sx - 4 * (sq + gap) - 10, bot);
      ctx.globalAlpha = 1;
      void f;
      return true;
    },
  };
})(window.REEL = window.REEL || {});
