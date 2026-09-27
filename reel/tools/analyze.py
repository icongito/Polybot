"""Review helpers for a rendered reel (needs Pillow + numpy + an ffmpeg binary).

  python3 tools/analyze.py energy  in.mp4 out.png            # motion-energy graph vs the 128 BPM grid
  python3 tools/analyze.py strip   in.mp4 out.png  t0 n [step]  # n consecutive frames from t0 (seconds)
  python3 tools/analyze.py grid    in.mp4 out.png  [cols]       # one frame per half beat
  python3 tools/analyze.py sheet   in.mp4 out.jpg               # one frame per beat, for the README
"""
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FPS = 60
BEAT = 60 / 128


def ffmpeg():
    if os.environ.get('FFMPEG'):
        return os.environ['FFMPEG']
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return 'ffmpeg'


def frames(path, w=320, h=180):
    cmd = [ffmpeg(), '-loglevel', 'error', '-i', path, '-vf', f'scale={w}:{h}', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    n = len(raw) // (w * h * 3)
    return np.frombuffer(raw, np.uint8)[: n * w * h * 3].reshape(n, h, w, 3)


def font(sz=12):
    try:
        return ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', sz)
    except OSError:
        return None


def energy(src, out):
    fr = frames(src, 160, 90).astype(np.float32)
    d = np.abs(np.diff(fr, axis=0)).mean(axis=(1, 2, 3))
    W, H = 1800, 360
    img = Image.new('RGB', (W, H), (20, 20, 22))
    dr = ImageDraw.Draw(img)
    n = len(fr)
    x = lambda i: 40 + (W - 60) * i / max(1, n - 1)
    for bt in range(33):
        xx = x(bt * BEAT * FPS)
        dr.line([(xx, 20), (xx, H - 30)], fill=(70, 70, 80) if bt % 4 else (130, 130, 150), width=1)
        dr.text((xx + 2, H - 26), str(bt), fill=(150, 150, 160), font=font(11))
    mx = max(1e-3, float(np.percentile(d, 99.5)))
    pts = [(x(i + 1), H - 30 - (H - 60) * min(1, v / mx)) for i, v in enumerate(d)]
    dr.line(pts, fill=(255, 90, 40), width=2)
    dr.text((44, 4), f'{os.path.basename(src)}  mean |dF| per frame (clipped at p99.5={mx:.1f})', fill=(220, 220, 220), font=font(12))
    img.save(out)
    # report the largest jumps
    idx = np.argsort(d)[::-1][:24]
    for i in sorted(idx):
        print(f'frame {i + 1:4d}  t={(i + 1) / FPS:6.3f}s  beat={(i + 1) / FPS / BEAT:6.2f}  dF={d[i]:6.2f}')


def strip(src, out, t0, n, step=1):
    fr = frames(src, 480, 270)
    f0 = int(round(t0 * FPS))
    sel = [min(len(fr) - 1, f0 + k * step) for k in range(n)]
    cols = min(6, n)
    rows = (n + cols - 1) // cols
    img = Image.new('RGB', (cols * 484 + 4, rows * 292 + 4), (40, 40, 40))
    dr = ImageDraw.Draw(img)
    for k, fi in enumerate(sel):
        xx, yy = 4 + (k % cols) * 484, 4 + (k // cols) * 292
        img.paste(Image.fromarray(fr[fi]), (xx, yy + 18))
        dr.text((xx, yy + 2), f'f{fi}  t={fi / FPS:.3f}  b{fi / FPS / BEAT:.2f}', fill=(230, 230, 230), font=font(12))
    img.save(out)


def grid(src, out, cols=8):
    fr = frames(src, 320, 180)
    sel = [int(round(k * BEAT * FPS / 2)) for k in range(64)]
    sel = [min(len(fr) - 1, s) for s in sel]
    rows = (len(sel) + cols - 1) // cols
    img = Image.new('RGB', (cols * 324 + 4, rows * 200 + 4), (40, 40, 40))
    dr = ImageDraw.Draw(img)
    for k, fi in enumerate(sel):
        xx, yy = 4 + (k % cols) * 324, 4 + (k // cols) * 200
        img.paste(Image.fromarray(fr[fi]), (xx, yy + 16))
        dr.text((xx, yy + 1), f'b{k / 2:.1f}', fill=(230, 230, 230), font=font(11))
    img.save(out)


def sheet(src, out, cols=8, offset=0.4):
    """One frame per beat (sampled `offset` beats after each downbeat), labelled, as a JPEG."""
    fr = frames(src, 480, 270)
    sel = [min(len(fr) - 1, int(round((k + offset) * BEAT * FPS))) for k in range(32)]
    rows = (len(sel) + cols - 1) // cols
    pad, lab = 6, 20
    img = Image.new('RGB', (cols * (480 + pad) + pad, rows * (270 + lab + pad) + pad), (11, 11, 12))
    dr = ImageDraw.Draw(img)
    for k, fi in enumerate(sel):
        xx, yy = pad + (k % cols) * (480 + pad), pad + (k // cols) * (270 + lab + pad)
        img.paste(Image.fromarray(fr[fi]), (xx, yy + lab))
        dr.text((xx, yy + 3), f'beat {k:02d}   {fi / FPS:5.2f} s', fill=(143, 139, 130), font=font(13))
    img.save(out, quality=88)


if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'energy':
        energy(sys.argv[2], sys.argv[3])
    elif cmd == 'strip':
        strip(sys.argv[2], sys.argv[3], float(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6]) if len(sys.argv) > 6 else 1)
    elif cmd == 'sheet':
        sheet(sys.argv[2], sys.argv[3])
    elif cmd == 'grid':
        grid(sys.argv[2], sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 8)
