/* core.js — beat grid, easing, and a tiny WebGL2 toolkit.
   Everything in the reel is a pure function of time, so any frame can be
   rendered in any order (scrubbing, offline capture, motion-blur subframes). */
(function (R) {
  'use strict';

  // ---------------------------------------------------------------- grid
  R.W = 1920; R.H = 1080; R.FPS = 60;
  R.BPM = 128;
  R.BEAT = 60 / R.BPM;            // 0.46875 s
  R.BEATS = 32;                   // 8 bars of 4/4
  R.DURATION = R.BEATS * R.BEAT;  // exactly 15.000 s
  R.b = (n) => n * R.BEAT;        // beat -> seconds
  R.DOT0 = 23;                    // radius of the dot on the first and last frame (the loop point)

  // ---------------------------------------------------------------- math
  const clamp = (x, a = 0, b = 1) => (x < a ? a : x > b ? b : x);
  const lerp = (a, b, t) => a + (b - a) * t;
  const inv = (a, b, x) => clamp((x - a) / (b - a));
  const smooth = (a, b, x) => { const t = inv(a, b, x); return t * t * (3 - 2 * t); };
  const fract = (x) => x - Math.floor(x);
  const hash = (n) => fract(Math.sin(n * 127.1 + 311.7) * 43758.5453123);
  R.clamp = clamp; R.lerp = lerp; R.inv = inv; R.smooth = smooth; R.fract = fract; R.hash = hash;
  R.mixv = (a, b, t) => a.map((v, i) => lerp(v, b[i], t));

  R.hex = (h) => {
    const n = parseInt(h.slice(1), 16);
    return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
  };
  R.rgba = (c, a = 1) => `rgba(${Math.round(c[0] * 255)},${Math.round(c[1] * 255)},${Math.round(c[2] * 255)},${a})`;

  // ---------------------------------------------------------------- easing
  // CSS-style cubic-bezier, solved with Newton + bisection fallback.
  function bezier(x1, y1, x2, y2) {
    const cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx;
    const cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
    const sx = (t) => ((ax * t + bx) * t + cx) * t;
    const sy = (t) => ((ay * t + by) * t + cy) * t;
    const dx = (t) => (3 * ax * t + 2 * bx) * t + cx;
    return (x) => {
      if (x <= 0) return 0; if (x >= 1) return 1;
      let t = x;
      for (let i = 0; i < 8; i++) {
        const e = sx(t) - x; if (Math.abs(e) < 1e-6) return sy(t);
        const d = dx(t); if (Math.abs(d) < 1e-6) break; t -= e / d;
      }
      let lo = 0, hi = 1; t = x;
      for (let i = 0; i < 30; i++) { const v = sx(t); if (Math.abs(v - x) < 1e-6) break; if (v < x) lo = t; else hi = t; t = (lo + hi) / 2; }
      return sy(t);
    };
  }
  const E = {
    linear: (t) => t,
    inQuad: (t) => t * t,
    outQuad: (t) => 1 - (1 - t) * (1 - t),
    inCubic: (t) => t * t * t,
    outCubic: (t) => 1 - Math.pow(1 - t, 3),
    inOutCubic: (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2),
    outQuart: (t) => 1 - Math.pow(1 - t, 4),
    outQuint: (t) => 1 - Math.pow(1 - t, 5),
    inQuint: (t) => t * t * t * t * t,
    inOutQuint: (t) => (t < 0.5 ? 16 * t * t * t * t * t : 1 - Math.pow(-2 * t + 2, 5) / 2),
    outExpo: (t) => (t >= 1 ? 1 : 1 - Math.pow(2, -10 * t)),
    inExpo: (t) => (t <= 0 ? 0 : Math.pow(2, 10 * t - 10)),
    inOutExpo: (t) => (t <= 0 ? 0 : t >= 1 ? 1 : t < 0.5 ? Math.pow(2, 20 * t - 10) / 2 : (2 - Math.pow(2, -20 * t + 10)) / 2),
    outBack: (t, s = 1.70158) => 1 + (s + 1) * Math.pow(t - 1, 3) + s * Math.pow(t - 1, 2),
    inBack: (t, s = 1.70158) => (s + 1) * t * t * t - s * t * t,
    outSine: (t) => Math.sin((t * Math.PI) / 2),
    inOutSine: (t) => -(Math.cos(Math.PI * t) - 1) / 2,
    // damped spring settling on 1 (critically-underdamped look)
    spring: (t, f = 4.5, d = 6) => (t <= 0 ? 0 : 1 - Math.exp(-d * t) * Math.cos(f * Math.PI * 2 * t * 0.5)),
    bezier,
  };
  // House curves — the "signature" feel of the piece.
  E.snap = bezier(0.75, 0, 0.1, 1);      // hard in, glassy out
  E.whip = bezier(0.85, 0, 0.15, 1);     // extreme in-out for camera whips
  E.glide = bezier(0.3, 0, 0, 1);        // soft settle
  E.drop = bezier(0.6, 0, 1, 0.6);       // gravity-ish acceleration
  R.E = E;

  // progress helpers on the beat grid
  R.pb = (t, b0, b1, ease = E.linear) => ease(inv(R.b(b0), R.b(b1), t));
  R.ps = (t, s0, s1, ease = E.linear) => ease(inv(s0, s1, t));
  // decaying impulse after a hit (0 before, 1 at hit, decays)
  R.kick = (t, bHit, decay = 10) => { const d = t - R.b(bHit); return d < 0 ? 0 : Math.exp(-d * decay); };
  // damped oscillation after a hit
  R.ring = (t, bHit, freq = 9, decay = 7) => { const d = t - R.b(bHit); return d < 0 ? 0 : Math.exp(-d * decay) * Math.sin(d * freq * Math.PI * 2); };
  // bouncing-ball arc between two beats: returns {x:0..1, y:0..1(height)} parabolic
  R.hop = (u) => 4 * u * (1 - u);

  // ---------------------------------------------------------------- WebGL2
  const VS = `#version 300 es
layout(location=0) in vec2 aPos;
out vec2 vUv;
void main(){ vUv = aPos*0.5+0.5; gl_Position = vec4(aPos,0.,1.); }`;

  R.initGL = function (canvas) {
    const gl = canvas.getContext('webgl2', {
      antialias: false, alpha: false, depth: false, stencil: false,
      preserveDrawingBuffer: true, premultipliedAlpha: false, powerPreference: 'high-performance',
    });
    if (!gl) throw new Error('WebGL2 not available');
    R.floatOK = !!gl.getExtension('EXT_color_buffer_float');
    R.parallel = gl.getExtension('KHR_parallel_shader_compile');
    gl.getExtension('OES_texture_float_linear');
    const vao = gl.createVertexArray();
    gl.bindVertexArray(vao);
    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    R.gl = gl;
    return gl;
  };

  function compile(gl, type, src) {
    const s = gl.createShader(type);
    gl.shaderSource(s, src);
    gl.compileShader(s);          // status is checked lazily so drivers can compile in parallel
    return s;
  }
  function explain(gl, sh, src) {
    if (gl.getShaderParameter(sh, gl.COMPILE_STATUS)) return;
    const log = gl.getShaderInfoLog(sh);
    console.error(src.split('\n').map((l, i) => `${String(i + 1).padStart(4)}: ${l}`).join('\n'));
    throw new Error('Shader compile error: ' + log);
  }

  R.programs = [];
  R.Program = class Program {
    constructor(fs, name = 'prog') {
      const gl = R.gl;
      this.name = name;
      const p = gl.createProgram();
      this.vs = compile(gl, gl.VERTEX_SHADER, VS);
      this.fs = compile(gl, gl.FRAGMENT_SHADER, fs);
      this.src = fs;
      gl.attachShader(p, this.vs);
      gl.attachShader(p, this.fs);
      gl.bindAttribLocation(p, 0, 'aPos');
      gl.linkProgram(p);
      this.p = p;
      this.ready = false;
      R.programs.push(this);
    }
    // true once the driver has finished (never blocks when KHR_parallel_shader_compile exists)
    isReady() {
      if (this.ready) return true;
      if (R.parallel && !R.gl.getProgramParameter(this.p, R.parallel.COMPLETION_STATUS_KHR)) return false;
      this.finish();
      return true;
    }
    finish() {
      if (this.ready) return;
      const gl = R.gl, p = this.p;
      if (!gl.getProgramParameter(p, gl.LINK_STATUS)) {
        explain(gl, this.vs, VS); explain(gl, this.fs, this.src);
        throw new Error(this.name + ' link error: ' + gl.getProgramInfoLog(p));
      }
      this.ready = true;
      this.u = {};
      const n = gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS);
      let unit = 0;
      for (let i = 0; i < n; i++) {
        const info = gl.getActiveUniform(p, i);
        const nm = info.name.replace(/\[0\]$/, '');
        const loc = gl.getUniformLocation(p, info.name);
        const u = { loc, type: info.type, size: info.size };
        if (info.type === gl.SAMPLER_2D) u.unit = unit++;
        this.u[nm] = u;
      }
    }
    set(name, v) {
      if (!this.ready) this.finish();
      const gl = R.gl, u = this.u[name];
      if (!u) return;
      switch (u.type) {
        case gl.FLOAT: u.size > 1 ? gl.uniform1fv(u.loc, v) : gl.uniform1f(u.loc, v); break;
        case gl.FLOAT_VEC2: gl.uniform2fv(u.loc, v); break;
        case gl.FLOAT_VEC3: gl.uniform3fv(u.loc, v); break;
        case gl.FLOAT_VEC4: gl.uniform4fv(u.loc, v); break;
        case gl.INT: case gl.BOOL: gl.uniform1i(u.loc, v); break;
        case gl.FLOAT_MAT3: gl.uniformMatrix3fv(u.loc, false, v); break;
        case gl.FLOAT_MAT4: gl.uniformMatrix4fv(u.loc, false, v); break;
        case gl.SAMPLER_2D:
          gl.activeTexture(gl.TEXTURE0 + u.unit);
          gl.bindTexture(gl.TEXTURE_2D, v && v.tex ? v.tex : v);
          gl.uniform1i(u.loc, u.unit);
          break;
        default: throw new Error('uniform type not handled: ' + name);
      }
    }
  };

  // Render target (texture-backed framebuffer)
  R.Target = class Target {
    constructor(w, h, opts = {}) {
      const gl = R.gl;
      this.w = w; this.h = h;
      const float = opts.float !== false && R.floatOK;
      this.tex = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, this.tex);
      gl.texImage2D(gl.TEXTURE_2D, 0, float ? gl.RGBA16F : gl.RGBA8, w, h, 0, gl.RGBA, float ? gl.HALF_FLOAT : gl.UNSIGNED_BYTE, null);
      const f = opts.nearest ? gl.NEAREST : gl.LINEAR;
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, f);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, f);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      this.fb = gl.createFramebuffer();
      gl.bindFramebuffer(gl.FRAMEBUFFER, this.fb);
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, this.tex, 0);
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    }
    dispose() { const gl = R.gl; gl.deleteFramebuffer(this.fb); gl.deleteTexture(this.tex); }
  };

  // Texture fed from a 2D canvas each frame
  R.CanvasTex = class CanvasTex {
    constructor(canvas) {
      const gl = R.gl;
      this.canvas = canvas;
      this.tex = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, this.tex);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    }
    upload() {
      const gl = R.gl;
      gl.bindTexture(gl.TEXTURE_2D, this.tex);
      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
      gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, this.canvas);
      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
      gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
      return this;
    }
  };

  // Draw a program into a target (null = default framebuffer)
  R.draw = function (prog, target, uniforms = {}, blend = null) {
    const gl = R.gl;
    gl.bindFramebuffer(gl.FRAMEBUFFER, target ? target.fb : null);
    const w = target ? target.w : gl.drawingBufferWidth, h = target ? target.h : gl.drawingBufferHeight;
    gl.viewport(0, 0, w, h);
    if (!prog.ready) prog.finish();
    gl.useProgram(prog.p);
    prog.set('uRes', [w, h]);
    for (const k in uniforms) prog.set(k, uniforms[k]);
    if (blend === 'add') { gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE); }
    else if (blend === 'over') { gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA); }
    else gl.disable(gl.BLEND);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    gl.disable(gl.BLEND);
  };

  R.clear = function (target, c = [0, 0, 0, 0]) {
    const gl = R.gl;
    gl.bindFramebuffer(gl.FRAMEBUFFER, target ? target.fb : null);
    gl.viewport(0, 0, target ? target.w : gl.drawingBufferWidth, target ? target.h : gl.drawingBufferHeight);
    gl.clearColor(c[0], c[1], c[2], c[3]);
    gl.clear(gl.COLOR_BUFFER_BIT);
  };

  R.allReady = () => R.programs.every((p) => p.isReady());
  // Draw every program once into a 1x1 target so drivers build their pipelines now,
  // not in the middle of the reel. Yields between programs so the page stays responsive.
  R.warmup = async function (onProgress) {
    const gl = R.gl, tiny = new R.Target(1, 1, { float: false }), px = new Uint8Array(4);
    // a separate dummy texture on every unit, so no sampler reads the target being drawn
    const dummy = new R.Target(1, 1, { float: false });
    for (let i = 0; i < R.programs.length; i++) {
      while (!R.programs[i].isReady()) await new Promise((r) => setTimeout(r, 16));
      const U = {};
      for (const k in R.programs[i].u) if (R.programs[i].u[k].type === gl.SAMPLER_2D) U[k] = dummy.tex;
      R.draw(R.programs[i], tiny, U);
      gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);
      if (onProgress) onProgress((i + 1) / R.programs.length);
      await new Promise((r) => setTimeout(r, 0));
    }
    tiny.dispose(); dummy.dispose();
  };
  R.readyFraction = () => R.programs.filter((p) => p.isReady()).length / Math.max(1, R.programs.length);

  R.canvas2d = function (w, h) {
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    return c;
  };

  // ---------------------------------------------------------------- GLSL shared
  R.GLSL = `#version 300 es
precision highp float;
precision highp int;
out vec4 fragColor;
uniform vec2 uRes;
uniform float uScale;      // device px per design px (1 at 1920x1080)
uniform vec2 uJitter;      // subpixel AA jitter (device px)
#define PI 3.14159265359
#define TAU 6.28318530718
// design-space pixel (1920x1080, y down)
vec2 designPx(){ vec2 f = gl_FragCoord.xy + uJitter; return vec2(f.x, uRes.y - f.y) / uScale; }
float hash11(float p){ p = fract(p*.1031); p *= p+33.33; p *= p+p; return fract(p); }
float hash12(vec2 p){ vec3 p3 = fract(vec3(p.xyx)*.1031); p3 += dot(p3, p3.yzx+33.33); return fract((p3.x+p3.y)*p3.z); }
vec2 hash22(vec2 p){ vec3 p3 = fract(vec3(p.xyx)*vec3(.1031,.1030,.0973)); p3 += dot(p3, p3.yzx+33.33); return fract((p3.xx+p3.yz)*p3.zy); }
float vnoise(vec2 p){ vec2 i=floor(p), f=fract(p); vec2 u=f*f*(3.-2.*f);
  return mix(mix(hash12(i),hash12(i+vec2(1,0)),u.x), mix(hash12(i+vec2(0,1)),hash12(i+vec2(1,1)),u.x), u.y); }
float fbm(vec2 p){ float a=.5, s=0.; for(int i=0;i<4;i++){ s+=a*vnoise(p); p=p*2.03+17.1; a*=.5; } return s; }
mat2 rot(float a){ float c=cos(a), s=sin(a); return mat2(c,-s,s,c); }
float sat(float x){ return clamp(x,0.,1.); }
vec3 srgb2lin(vec3 c){ return pow(c, vec3(2.2)); }
vec3 lin2srgb(vec3 c){ return pow(max(c,0.), vec3(1./2.2)); }
`;

  // Blit / composite helpers
  R.GLSL_BLIT = R.GLSL + `
in vec2 vUv;
uniform sampler2D uTex;
uniform float uAlpha;
void main(){ vec4 c = texture(uTex, vUv); fragColor = c * uAlpha; }`;
})(window.REEL = window.REEL || {});
