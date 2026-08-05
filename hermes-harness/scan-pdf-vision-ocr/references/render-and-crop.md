# Render & crop — reference recipes

Concrete snippets tested in the kirik-kinematika session. Adapt to your
scan.

## Render pages at two DPI levels (low for OCR, high for cropping)

```python
import fitz, os

pdf = fitz.open('/path/to/scan.pdf')
os.makedirs('/tmp/scan_low', exist_ok=True)
os.makedirs('/tmp/scan_high', exist_ok=True)

for i, p in enumerate(pdf):
    # 150 dpi — token-friendly for vision_analyze
    p.get_pixmap(dpi=150).save(f'/tmp/scan_low/p{i+1:02d}.png')
    # 3x zoom ≈ 216 dpi — keep for cropping
    p.get_pixmap(matrix=fitz.Matrix(3, 3)).save(f'/tmp/scan_high/p{i+1:02d}.png')
```

## Detect image-only PDFs

```python
import fitz
doc = fitz.open('/path/to/scan.pdf')
chars_per_page = [len(p.get_text()) for p in doc]
print('chars/page:', chars_per_page)
# image-only: typically every page < 50 chars
```

## Split a two-page spread

```python
from PIL import Image
img = Image.open('/tmp/scan_high/p07.png')
W, H = img.size
left  = img.crop((0,    0, W//2, H))
right = img.crop((W//2, 0, W,   H))
left.save('/tmp/scan_high/p07_left.png')
right.save('/tmp/scan_high/p07_right.png')
```

## Find the page number printed at the bottom of the page

Useful when the scan is a multi-page book spread and you need to map
scan-page ↔ textbook-page.

vision prompt:
> "Какие номера страниц указаны внизу этих двух страниц? Только коротко."

The model's answer (e.g. "20 и 21") is reliable for clean printed scans.

## Crop a single graph from a page (iterative)

```python
from PIL import Image
img = Image.open('/tmp/scan_high/p08_left.png')
LW, LH = img.size
# start with rough guess — refine after vision_analyze
graph = img.crop((int(LW*0.45), int(LH*0.32), LW, int(LH*0.72)))
graph.save('graph.png')
```

Verify:
```
vision_analyze(image_url='graph.png',
               question='Что здесь изображено?')
```

If the crop is off, expand left/right/up/down by 5–10 % and retry.

## Pipeline outputs

A typical run produces:

```
/tmp/scan_low/                 # 18 small PNGs for OCR (≈1–2 MB each)
  p01.png … p18.png
/tmp/scan_high/                # 18 larger PNGs for cropping
  p01.png … p18.png
/tmp/scan_high/p07_left.png    # cropped to single textbook-page
/tmp/figure_3_26.png           # extracted graph
```

Time budget: ~5–10 s per vision call + 1–2 s per render. A 20-page scan
typically takes 4–6 minutes end-to-end.