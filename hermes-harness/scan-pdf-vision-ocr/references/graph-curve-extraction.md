# Graph curve extraction without vision — pure-PIL/NumPy fallback

When `vision_analyze` is fully down (timeout/`400` on every call, even
small `file://` thumbs) but you still need to read a graph from a
scan (kirik 3.34, любой физический график в PDF), this script
recovers the curve as (x, y) coordinates directly from the pixels.
Verified in 2026-08-03 kirik session — vision was dead for the whole
session; this gave correct curve data in ~5 seconds.

## When to use it

- Black-and-white textbook scan (graph is dark pixels on light
  background). **Color scans** need extra logic — see "Caveats".
- Curve is a **continuous connected line** (typical x(t), v(t), p(V)
  textbook plot). Bar charts / scatter plots need different logic.
- You need rough (t, value) data to feed a canvas animation or to
  sanity-check answers to a question like "where does the curve cross
  zero" / "where is the maximum".

Don't use it for exact pixel-perfect digitization — vision still wins
for that. This is the "good enough to build a разбор without lying
about the numbers" path.

## Recipe

```python
from PIL import Image
import numpy as np

src = '/path/to/scan.png'  # or crop to the plot region first
img = Image.open(src).convert('L')
W, H = img.size
arr = np.array(img)
print(f'image: {W}x{H}')

# 1. Threshold — black ink = dark pixels
dark = arr < 100  # adjust 100 if ink is grey (try 130 for light scans)

# 2. For each X column, find runs of consecutive dark pixels
#    Curve = longest run; text/ticks = short isolated runs.
def col_curve_y(dark_col):
    ys = np.where(dark_col)[0]
    if len(ys) == 0:
        return None
    # split into runs where gap > 3 px
    runs = []
    start = ys[0]; prev = ys[0]
    for y in ys[1:]:
        if y - prev > 3:
            runs.append((start, prev))
            start = y
        prev = y
    runs.append((start, prev))
    # longest run = curve
    longest = max(runs, key=lambda r: r[1] - r[0])
    return (longest[0] + longest[1]) / 2  # midpoint Y

# 3. Restrict to plot area — crop coordinates around the curve bounding box
#    If you don't have a known crop, first pass: find bbox of any
#    large connected dark region.
xs, ys_dark = np.where(dark)
if len(xs) == 0:
    print('NO DARK PIXELS — check threshold'); raise SystemExit
# bbox of all dark
print(f'dark bbox: x={xs.min()}..{xs.max()}, y={ys_dark.min()}..{ys_dark.max()}')

# 4. Per-X midpoint curve
curve = []
for x in range(xs.min(), xs.max() + 1):
    y = col_curve_y(dark[:, x])
    if y is not None:
        curve.append((x, y))

# 5. Smooth / downsample to N points
N = 200
idx = np.linspace(0, len(curve) - 1, N).astype(int)
smooth = [curve[i] for i in idx]

# 6. Plot-side noise removal: detect & drop outliers that jump >20 px
#    from a sliding-window median (text labels at edges, ticks).
filtered = []
window = 7
for i, (x, y) in enumerate(smooth):
    lo = max(0, i - window); hi = min(len(smooth), i + window + 1)
    med = np.median([smooth[j][1] for j in range(lo, hi)])
    if abs(y - med) < 25:  # within 25 px of local median → keep
        filtered.append((x, y))

print(f'curve points: {len(curve)} raw → {len(smooth)} downsampled → {len(filtered)} cleaned')

# 7. Map (px, py) → (t, value) using axis labels you already got from OCR:
#    axis ticks say e.g. t = 0..6 s, value = -1..4 m.
#    Find pixel coords of axis label "0" and "6" in your scan (PIL
#    locate them with rapidocr again, then crop to single digit
#    glyphs and find their centroid) — or just hardcode from the
#    axis ticks you already see in the original PDF.
```

## Caveats

- **Color scans**: replace the `arr < 100` threshold with a colour
  mask. For a single-hue curve (e.g. blue ink on white):
  `mask = (arr[:,:,2] > arr[:,:,0]) & (arr[:,:,2] > 100)`.
- **Two curves on same axes** (kirik 3.34 case — Тело 1 s(t) and
  Тело 2 v(t) on one plot): run the script twice with different
  colour thresholds, or split the plot region vertically if the
  curves don't overlap.
- **Axis label positions**: required to map (px, py) → (t, value).
  Easiest path: from the OCR JSON you already have (`kirik_ocr/
  p09_left.png.json` etc.), find the bounding box of the axis-tick
  number "0" and "6", and use those as anchors. Or eyeball it: open
  the cropped image in PIL, click the tick position visually, and
  hardcode.
- **Dashed/sparse curves**: increase the run-gap threshold (3 →
  6–8) so dashes don't get split into separate runs and discarded
  as outliers.
- **Text labels crossing the curve**: the outlier filter (step 7)
  is what handles this. If the curve legitimately has steep
  transitions (vertical asymptote, sharp kink), widen the
  threshold from 25 px to 50 px.

## Why this beats "guess from OCR fragments"

OCR sees only axis labels, scale numbers, and isolated points
labelled by hand. The (t, value) data for the curve itself is
purely visual — there are no letters in it to read. The pixel-scan
fallback recovers what's actually there. If pixel-scan also fails
(real curve hidden by heavy watermark, curve is dotted and barely
visible, etc.) the last resort is to **ask the user** — send the
crop via `MEDIA:` and ask for 5–8 (t, value) points. Do **not**
fabricate numbers "because they look about right" — that's the
30-minutes-of-confident-wrong-разборs failure mode that motivated
this file.
