/* timeline-world.js — choreography for 2D plane, 3D volume and 4D time. */
(function (R) {
  'use strict';
  const E = R.E, b = R.b, lerp = R.lerp, inv = R.inv, clamp = R.clamp;
  const G = R.glyphs, ID = R.GLYPH_ID;
  const lin = (c) => c.map((v) => Math.pow(v, 2.2));
  const mix3 = (a, c, k) => [lerp(a[0], c[0], k), lerp(a[1], c[1], k), lerp(a[2], c[2], k)];

  const D_FLAT = 0.012, D_VOL = 0.26;
  const LAY = { plane: R.worldLayout('plane'), volume: R.worldLayout('volume'), time: R.worldLayout('time') };
  // part colour indices: 0 cream, 1 ink, 2 orange, 3 blue
  const COLS = {
    p: [1, 0], l: [0], a: [0, 0], n: [0, 0, 0], e: [0, 1],
    v: [0], o: [0], u: [0, 0, 0], m: [0, 0, 0, 0, 0], t: [0, 0], i: [0],
  };

  // keyframe interpolation: ks = [[beat, value, easeToNext?], ...]
  function kf(t, ks) {
    const B = t / R.BEAT;
    if (B <= ks[0][0]) return ks[0][1];
    for (let i = 0; i < ks.length - 1; i++) {
      const [b0, v0, e] = ks[i], [b1, v1] = ks[i + 1];
      if (B <= b1) {
        const u = (e || E.inOutCubic)((B - b0) / (b1 - b0));
        return Array.isArray(v0) ? v0.map((x, j) => lerp(x, v1[j], u)) : lerp(v0, v1, u);
      }
    }
    return ks[ks.length - 1][1];
  }
  R.kf = kf;

  function mkSlot(ch, cx) {
    const g = G.L[ch];
    return {
      g: ID[ch] || 0, ch, pos: [cx, 0, 0], rot: [0, 0, 0], scl: [1, 1, 1], adv: g ? g.adv : 1, depth: D_VOL,
      parts: (g ? g.parts : [0]).map(() => [0, 0, 0, 1]), cols: COLS[ch] || [0],
    };
  }

  // deterministic fly-in vectors for the paper parts
  function flyIn(ch, j, part, slotIdx) {
    const h = R.hash(slotIdx * 7.31 + j * 3.17);
    const tall = part.t === 'box' && part.h[1] > part.h[0];
    const wide = part.t === 'box' && part.h[0] > part.h[1];
    if (tall) return [0, (h > 0.5 ? 1 : -1) * 4.2, (h - 0.5) * 0.6, 1];
    if (wide) return [(h > 0.5 ? 1 : -1) * 6.5, 0, (h - 0.5) * 0.5, 1];
    return [(slotIdx < 2 ? -1 : 1) * 5.5, (h - 0.5) * 3, (h > 0.5 ? 1 : -1) * 2.4, 0.4];
  }

  const PAL_BASE = () => [lin(R.palette.paper), lin([0.075, 0.075, 0.085]), lin(R.palette.orange), lin(R.palette.blue), lin(R.palette.blue), lin([0.5, 0.5, 0.5])];

  function worldState(t) {
    const B = t / R.BEAT;
    const st = { slots: [], fx: {}, pal: PAL_BASE() };
    st.cast = B < 13 ? 'plane' : B < 14.35 ? 'flip' : B < 17.85 ? 'volume' : B < 19 ? 'swap' : 'time';

    // ---------------------------------------------------------------- letters
    // phase A (b9..b13): "plane" lying flat, parts fly in, then pop up
    // phase B (b13..b18): flip-swap into "volume", 3D choreography
    // phase C (b18..b23): "volume" -> "time"
    const pop = (i) => R.pb(t, 12 + i * 0.1, 13.0 + i * 0.1, E.outBack);
    const depthK = R.pb(t, 12.05, 13.1, E.inOutCubic);
    const depth = lerp(D_FLAT, D_VOL, depthK);
    const slots = [];
    for (let s = 0; s < 6; s++) {
      const from = LAY.plane[s], to = LAY.volume[s];
      // flip-swap timing (b13.0 .. b14.0)
      const f0 = 13.0 + s * 0.12, f1 = f0 + 0.55;
      const fu = clamp((B - f0) / (f1 - f0));
      const fe = E.inOutCubic(fu);
      const swapped = fu >= 0.5;
      const ch = swapped ? to.ch : (from ? from.ch : null);
      const cx = lerp(from ? from.cx : to.cx, to.cx, fe);
      let sl = ch && ch !== 'o' ? mkSlot(ch, cx) : { ch: null, pos: [cx, 0, 0], rot: [0, 0, 0], scl: [1, 1, 1], adv: 1, depth, parts: [], cols: [0] };
      sl.depth = depth;
      // flat (hinge -90deg) -> standing
      const hk = pop(s);
      sl.rot[0] = lerp(-Math.PI / 2, 0, hk);
      const standY = from && from.ch === 'p' ? 0.5 * (1 - fe) : 0;   // the p stands on its descender
      sl.pos[1] = lerp(depth + 0.035, standY, clamp(hk));
      // flip
      if (fu > 0 && fu < 1) sl.rot[1] = swapped ? lerp(-Math.PI / 2, 0, E.outBack((fu - 0.5) * 2, 1.4)) : lerp(0, Math.PI / 2, E.inCubic(fu * 2));
      // slot 5 ('e' of volume) has no plane letter: it springs up out of the floor
      if (s === 5) {
        sl = mkSlot('e', to.cx);
        sl.depth = depth;
        const u = R.pb(t, 13.7, 14.25, E.outBack);
        sl.pos[1] = lerp(-1.7, 0, u);
        if (B < 13.7) sl.ch = null;
      }
      // paper parts fly in (b9.4 .. b10)
      if (from && !swapped) {
        const g = G.L[from.ch];
        g.parts.forEach((pt, j) => {
          const land = 9.45 + (s * 0.09 + j * 0.05);
          const u = clamp((B - (land - 0.42)) / 0.42);
          const k = 1 - E.outExpo(u);
          const v = flyIn(from.ch, j, pt, s);
          sl.parts[j] = [v[0] * k, v[1] * k, v[2] * k, lerp(1, v[3], k)];
        });
      }
      slots.push(sl);
    }

    // --- b10.5 / b11 / b11.5: the flat composition breathes (tracking out, in, home)
    const trk = kf(t, [[10.45, 0], [10.72, 0.34, E.outBack], [10.95, 0.34], [11.2, -0.07, E.snap], [11.45, -0.07], [11.8, 0, E.snap]]);
    if (B < 12.2) slots.forEach((sl, s) => { if (s < 5) sl.pos[0] += (s - 2) * trk; });
    st.discK = kf(t, [[10.45, 1], [10.72, 1.16, E.outBack], [10.95, 1.16], [11.2, 0.86, E.snap], [11.45, 0.86], [11.8, 1, E.snap]]);

    // --- volume choreography: stadium wave (b16.25..b17.5)
    if (B > 16 && B < 18) {
      slots.forEach((sl, s) => {
        const u = clamp((B - 16.4 - s * 0.14) / 0.62);
        if (u <= 0 || u >= 1) return;
        const jump = Math.sin(Math.PI * u);
        const sq = u < 0.12 ? -Math.sin(Math.PI * u / 0.12) * 0.25 : (u > 0.88 ? -Math.sin(Math.PI * (u - 0.88) / 0.12) * 0.22 : jump * 0.12);
        sl.pos[1] += 0.9 * jump * jump * (u > 0.12 && u < 0.88 ? 1 : 0.4);
        sl.scl = [sl.scl[0] * (1 - sq * 0.6), sl.scl[1] * (1 + sq), sl.scl[2] * (1 - sq * 0.6)];
        sl.rot[1] += jump * 0.35 * (s % 2 ? 1 : -1);
      });
    }

    // --- volume -> time (b18 .. b19)
    if (B >= 17.9) {
      const TT = LAY.time;
      for (let s = 0; s < 6; s++) {
        const sl = slots[s];
        if (s >= 4) {                                 // m, e slide left into place
          const u = R.pb(t, 18.1, 18.8, E.snap);
          sl.pos[0] = lerp(LAY.volume[s].cx, TT[s - 2].cx, u);
        } else {                                       // v o l u drop through the floor...
          const u = R.pb(t, 17.9 + s * 0.07, 18.35 + s * 0.07, E.inBack);
          sl.pos[1] -= 2.2 * u;
          sl.rot[2] += (s - 1.5) * 0.25 * u;
          // ...and t, i rise out of it
          if (s < 2) {
            const r = R.pb(t, 18.45 + s * 0.1, 18.95 + s * 0.1, E.outBack);
            if (r > 0) {
              const ns = mkSlot(TT[s].ch, TT[s].cx);
              ns.depth = D_VOL;
              ns.pos[1] = lerp(-1.8, 0, r);
              ns.scl = [1, lerp(0.6, 1, r), 1];
              slots[s] = ns;
            }
          } else if (u >= 1) sl.ch = null;
        }
      }
    }
    st.slots = slots;

    // ---------------------------------------------------------------- the dot
    // falls into the paper world (b9..b9.3), splats into a disc, inflates to a sphere (b13..b14),
    // becomes the o of volume, then hops onto the i of time (b18.3..b19)
    const DISC = [0.35, 0, -0.55];
    const TH = 0.012;                     // paper thickness of the disc
    let c, R0, rb, scl = [1, 1, 1];
    {
      const fall = R.pb(t, 8.95, 9.3, E.inQuad);
      const splat = R.pb(t, 9.3, 9.9, (x) => E.spring(x, 2.2, 5.5));
      const flatR = lerp(0.12, 1.45, splat) * (st.discK || 1);
      const ball = 1 - R.pb(t, 9.28, 9.4);          // falls as a ball, lands as paper
      c = [DISC[0], lerp(6, TH, fall), lerp(-3.4, DISC[2], fall)];
      R0 = lerp(flatR, 0.12, ball); rb = lerp(TH, 0.12, ball);
      // the paper disc slides out from under the letters, shrinking to the o's
      // footprint, then inflates into a sphere: a plane becoming a volume
      const oc = LAY.volume[1].cx;
      const sh = R.pb(t, 12.9, 13.55, E.inOutCubic);
      const inf = R.pb(t, 13.5, 14.05, E.outBack);
      if (B > 12.9) {
        R0 = lerp(1.45, 0.5, sh);
        c = [lerp(DISC[0], oc, sh), TH, lerp(DISC[2], 0.05, sh)];
      }
      if (B > 13.5) {
        rb = lerp(TH, 0.5, Math.min(1, inf));
        R0 = Math.max(rb, 0.5);
        c = [oc, lerp(TH, 0.5, inf), lerp(0.05, 0, Math.min(1, inf))];
      }
      // stadium wave: the o jumps with its neighbours
      if (B > 16 && B < 18) {
        const u = clamp((B - 16.4 - 1 * 0.14) / 0.62);
        const jump = Math.sin(Math.PI * u);
        c[1] += 0.9 * jump * jump;
        const sq = u > 0.9 ? Math.sin(Math.PI * (u - 0.9) / 0.1) * 0.2 : (u < 0.1 ? Math.sin(Math.PI * u / 0.1) * 0.2 : -jump * 0.08);
        scl = [1 + sq, 1 - sq, 1 + sq];
      }
      // hop to the tittle of `time`
      const hp = R.pb(t, 18.25, 19.0, E.inOutSine);
      if (B > 18.25) {
        const ti = LAY.time[1];
        const tx = ti.cx, ty = G.TIT.y + 0.02;
        c = [lerp(oc, tx, hp), lerp(0.5, ty, hp) + 1.1 * R.hop(hp), 0];
        R0 = rb = lerp(0.5, G.TIT.r * 1.05, E.inOutCubic(hp));
        const land = R.kick(t, 19.0, 14);
        scl = [1 + 0.25 * land, 1 - 0.25 * land, 1 + 0.25 * land];
      }
    }
    st.dot = { c, R: R0, rb, hh: 0, scl, emit: 0, spec: 0.9 };

    // ---------------------------------------------------------------- camera
    const volTarget = [0, 0.75, 0];
    let cam;
    {
      const oc = LAY.volume[1].cx;
      const tg = kf(t, [[12.0, [0, 0, -0.5]], [13.1, volTarget, E.whip], [14.6, [0.1, 0.72, 0]], [15.0, [oc, 0.5, 0], E.inOutCubic], [16.0, [oc, 0.5, 0]], [16.2, [0, 0.9, 0], E.outExpo], [18.2, [-0.1, 0.9, 0]], [19.0, [-0.1, 0.8, 0]]]);
      const yaw = kf(t, [[12.0, 0], [13.1, -0.42, E.whip], [14.6, 0.05, E.inOutSine], [15.0, 0.18, E.inOutCubic], [16.0, 0.26], [16.2, 0.55, E.outExpo], [18.0, -0.25, E.inOutSine], [19.0, 0.0, E.inOutCubic], [23, 0.12]]);
      const pitch = kf(t, [[12.0, Math.PI / 2], [13.1, 0.22, E.whip], [14.6, 0.17], [15.0, 0.1, E.inOutCubic], [16.0, 0.06], [16.2, 0.3, E.outExpo], [18.0, 0.18], [19.0, 0.1], [23, 0.14]]);
      // log-distance: 400 (ortho-like) -> close perspective; b15..b16 is a vertigo move:
      // the camera rushes in while the lens widens, the o holds its size, the world stretches
      const ld = kf(t, [[12.0, Math.log(400)], [13.1, Math.log(9.5), E.whip], [14.6, Math.log(9.0)], [15.0, Math.log(14), E.inOutCubic], [16.0, Math.log(1.25), E.inOutSine], [16.2, Math.log(8.5), E.outExpo], [18.0, Math.log(9.5)], [19.0, Math.log(7.5)], [23, Math.log(6.2)]]);
      const vh = kf(t, [[12.0, 3.8], [13.1, 4.4, E.whip], [14.6, 4.1], [15.0, 2.6, E.inOutCubic], [16.0, 2.6], [16.2, 4.3, E.outExpo], [18.0, 4.8], [19.0, 3.4], [23, 3.1]]);
      cam = R.orbitCam(tg, yaw, pitch, Math.exp(ld), vh, 0);
      st.camDist = Math.exp(ld);
    }
    st.cam = cam;

    // ---------------------------------------------------------------- light
    const L = {};
    {
      const flatK = 1 - R.pb(t, 12.2, 13.1, E.inOutCubic);
      const sweep = R.pb(t, 13.9, 15.4, E.inOutSine);
      const az = lerp(-2.5, 0.15, sweep);
      const el = lerp(0.62, 0.3, Math.sin(Math.PI * sweep) * 0.9 + sweep * 0.1);
      const sunVol = R.norm3([Math.cos(el) * Math.sin(az), Math.sin(el), Math.cos(el) * Math.cos(az)]);
      const sunFlat = R.norm3([-0.42, 0.8, -0.3]);
      L.sun = R.norm3(mix3(sunVol, sunFlat, flatK));
      // flat: amb 0.7 + sun 0.3 == albedo exactly on the floor
      const sunI = lerp(1.9, 0.3 / sunFlat[1], flatK);
      const night = R.pb(t, 16, 16.12) * (1 - R.pb(t, 22.8, 23));
      const warm = 1 - flatK;
      L.sunCol = mix3([sunI, sunI * lerp(1, 0.88, warm), sunI * lerp(1, 0.72, warm)], [0.05, 0.06, 0.12], night);
      L.sky = mix3(mix3([0.78, 0.82, 1.0], [1, 1, 1], flatK), [0.16, 0.18, 0.4], night);
      L.amb = lerp(lerp(0.4, 0.7, flatK), 0.2, night);
      L.rim = mix3([0, 0, 0], [0.16, 0.3, 0.7], night);
      L.tone = 1 - flatK;
      L.expo = 1.15;
      L.shadowK = lerp(9, 14, flatK);
      L.spec = lerp(0.35, 0.0, flatK);
      L.gloss = lerp(0.16, 0, flatK);
      L.fog = lerp(0.07, 0, flatK);
      L.fogStart = st.camDist + 3.5;
      const blueBg = lin(R.palette.blue);
      L.bgTop = mix3(mix3(blueBg, [0.35, 0.42, 1.0], 0.35), [0.004, 0.005, 0.02], night);
      L.bgBot = mix3(blueBg, [0.012, 0.014, 0.05], night);
      L.round = lerp(0.004, 0.035, 1 - flatK);
      st.dot.emit = night * lerp(0.2, 1.3, R.pb(t, 16.0, 16.4, E.outCubic));
      st.dot.glow = 0.12 + 0.25 * (1 - flatK) * (1 - night);
      if (night > 0) st.pal[4] = mix3(st.pal[4], lin([0.2, 0.21, 0.42]), night);
    }
    st.light = L;

    // ---------------------------------------------------------------- 4D time fx
    {
      // scene time: runs, freezes (b21), rewinds (b21.5), fast-forwards (b22)
      const tr = (x) => {
        const f = b(21), r0 = b(21.5), r1 = b(22), ff = b(23);
        if (x < f) return x - b(19);
        if (x < r0) return f - b(19);
        if (x < r1) return (f - b(19)) - (x - r0) * 2.6;
        return (f - b(19)) - (r1 - r0) * 2.6 + (x - r1) * 3.2;
      };
      st.fx.tau = B >= 19 ? tr(t) : 0;
      const on = R.pb(t, 19, 19.6, E.inOutCubic);
      st.fx.spin = on * 0.9;
      st.fx.bob = R.pb(t, 19.0, 19.3) * 0.62;
      const frozen = B >= 21 && B < 21.5;
      st.fx.slit = frozen ? 0 : R.pb(t, 19.3, 20.0, E.inOutCubic) * 1.05;
      st.fx.rgb = !frozen && B >= 20 ? 0.055 * R.pb(t, 20, 20.25) : 0;
      st.fx.ghostDt = 0.034;
    }
    return st;
  }
  R.worldState = worldState;
})(window.REEL = window.REEL || {});
