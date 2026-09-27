/* fonts.js — loads the type system into FontFace objects.
   Canvas2D can't animate a variable font's width axis, so Roboto Flex is
   registered once per width step ("Flex-w<N>", pinned by the stretch
   descriptor). Weight stays continuous through the numeric font-weight. */
(function (R) {
  'use strict';
  const SRC = {
    flex: 'fonts/RobotoFlex.woff2',
    mono: 'fonts/GeistMono.woff2',
  };
  const WSTEP = 2, WMIN = 25, WMAX = 151;

  async function buf(key) {
    if (R.FONT_DATA && R.FONT_DATA[key]) { // single-file build: base64 payloads
      const bin = atob(R.FONT_DATA[key]);
      const u8 = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
      return u8.buffer;
    }
    const r = await fetch(SRC[key]);
    if (!r.ok) throw new Error('font fetch failed: ' + SRC[key]);
    return r.arrayBuffer();
  }

  async function add(family, data, desc) {
    const f = new FontFace(family, data, desc);
    await f.load();
    document.fonts.add(f);
  }

  R.fonts = {
    async load() {
      const [flex, mono] = await Promise.all(['flex', 'mono'].map(buf));
      const jobs = [];
      for (let w = WMIN; w <= WMAX; w += WSTEP) jobs.push(add('Flex-w' + w, flex, { stretch: w + '%', weight: '100 1000' }));
      jobs.push(add('Mono', mono, { weight: '100 900' }));
      await Promise.all(jobs);
    },
    // CSS font string for Roboto Flex at an arbitrary width/weight
    flex(px, wdth = 100, wght = 400) {
      const w = Math.max(WMIN, Math.min(WMAX, WMIN + Math.round((wdth - WMIN) / WSTEP) * WSTEP));
      return `${Math.round(Math.max(100, Math.min(1000, wght)))} ${px}px 'Flex-w${w}'`;
    },
    mono(px, wght = 450) { return `${wght} ${px}px 'Mono'`; },
  };
})(window.REEL = window.REEL || {});
