# point made.

A 15-second motion-design résumé reel, built entirely in code (WebGL2 + Canvas2D), rendered deterministically frame by frame.

> "A line is a dot that went for a walk." — Paul Klee

The reel is one idea carried through every frame: **motion creates dimension**. A point moves and becomes a line; a line sweeps and becomes a plane; a plane is extruded into a volume; a volume moves through time. Each chapter word is set in the dimension it names, using one custom constructed alphabet:

| | chapter | the word is made of | the dot becomes |
|---|---|---|---|
| 0D | `point` | thousands of halftone points | the detonator, then the tittle of the i |
| 1D | `line` | one continuous 5-strand line | the pen nib, then the i's tittle, then a note bouncing down a stave |
| 2D | `plane` | paper cut-out planes, top-down | a flat paper disc behind the type |
| 3D | `volume` | lit, extruded solids | the sphere that is the o |
| 4D | `time` | the same solids, slit-scanned through time | a chronophotographed tittle tracing figure-eights |

Then everything plays back at once, faster and faster, cuts to silence, and the sentence arrives and parks against the dot: **point made.** The dot is the full stop. The last frame is the first frame, so the reel loops seamlessly.

## The score

There is no audio, so the rhythm is designed into the picture. 128 BPM × 32 beats = exactly **15.000 s**; every cut, hit and hold lands on the grid (the HUD's four-step sequencer makes the silent tempo visible).

| beat | time | event |
|---:|---:|---|
| 0 | 0.00 | the dot, alone; squash |
| 0.25 | 0.12 | detonation: two inverted impact frames, shock front develops `point` in halftone |
| 2 | 0.94 | inversion wave sweeps the field |
| 3 | 1.41 | zoom punch with dutch tilt |
| 4 | 1.88 | field implodes into the dot; the dot hops to its start mark |
| 5 | 2.34 | cut to paper; the dot writes `line` |
| 7 | 3.28 | the dot dots its own i; the line is pulled taut, the i vanishes underneath |
| 8–8.75 | 3.75 | the dot bounces down the stave on sixteenths; the lines rush up dragging the blue plane |
| 9 | 4.22 | the dot drops into a paper world, splats into a disc; cut-out planes fly in |
| 10.5 / 11 | 4.92 | the composition breathes: tracking out, in, home |
| 12 | 5.63 | pop-up: the camera falls from orthographic infinity into perspective, planes stand up and thicken |
| 13 | 6.09 | flip-swap `plane` → `volume`; the disc inflates into the o |
| 14–15 | 6.56 | orbit; the sun sweeps; dolly zoom into the o |
| 16 | 7.50 | lights out: the dot becomes the only light source |
| 16.4 | 7.69 | stadium wave with squash & stretch |
| 18 | 8.44 | `volume` drops through the floor, `ti` rises, the o hops onto the i |
| 19 | 8.91 | slit-scan, Harris-shutter RGB split, chronophotography |
| 21 | 9.84 | time freezes; 21.5 rewinds; 22 fast-forwards (the HUD timecode obeys) |
| 23–27 | 10.78 | montage: eighths → sixteenths → thirty-seconds, stitched by dot-irises and variable-font flash words |
| 27 | 12.66 | silence: the dot, alone |
| 27.6–28 | 12.94 | `point` glides in; `made` is thrown in and slams into the full stop |
| 31.5 | 14.77 | text cuts; the dot's single heartbeat hands over to frame 0 |

## Range on show

Generative halftone fields · shockwave refraction · impact frames · character animation (anticipation, squash & stretch, arcs, follow-through) · line animation and string physics · Bauhaus paper cut-out composition · kinetic tracking · orthographic-to-perspective camera reveal · raymarched 3D with soft shadows, AO, tone mapping · material and lighting changes · dolly zoom · emissive key light · slit-scan time displacement · Harris-shutter colour · chronophotography · speed ramps, freeze, rewind · accelerating montage editing · variable-font width animation (Roboto Flex 25 → 151) · a custom constructed alphabet shared by every chapter · post pipeline (bloom, chromatic aberration, grain, vignette) · 6-sample motion blur.

## Run it

- **Watch live:** open `dist/index.html` in a browser (single self-contained file, works offline). Space plays/pauses, ←/→ steps a frame, `[`/`]` steps a beat, drag the timeline to scrub.
- **Develop:** serve this folder (`npx serve .`) and open `index.html`; the page loads `src/*.js` directly.
- **Rebuild the single file:** `node tools/build.mjs`

## Render the video

Frames are rendered in headless Chromium (software WebGL is fine), read back raw and piped to ffmpeg:

```sh
npm install                      # playwright (uses a system Chromium if PLAYWRIGHT_BROWSERS_PATH is set)
node tools/render.mjs --scale 1 --sub 6 --subWorld 2 --out out/point-made.mp4
```

`--sub` is the number of motion-blur / anti-aliasing subframes per frame (180° shutter, Halton-jittered); `--subWorld` overrides it for the raymarched chapters, which are the expensive ones. Review helpers: `tools/shoot.mjs` (stills and contact sheets at chosen beats) and `tools/analyze.py` (motion-energy graph against the beat grid, filmstrips).

## Code map

| file | role |
|---|---|
| `src/core.js` | beat grid, easing (incl. CSS-style béziers), WebGL2 toolkit |
| `src/glyphs.js` | the constructed alphabet as SDF parts → GLSL and Canvas2D |
| `src/scene-point.js` | 0D halftone field (two passes: cell field → dots) |
| `src/scene-line.js` | 1D ribbon writing, pull-taut, stave |
| `src/scene-world.js` | 2D/3D/4D raymarched world, generated per letter cast |
| `src/scene-words.js`, `src/scene-finale.js` | flash words, the full stop |
| `src/timeline*.js` | the choreography, expressed in beats |
| `src/post.js`, `src/hud.js`, `src/main.js` | lens, frame, subframe accumulation |

Fonts: Roboto Flex and Geist Mono, both SIL Open Font License (see `fonts/`).
