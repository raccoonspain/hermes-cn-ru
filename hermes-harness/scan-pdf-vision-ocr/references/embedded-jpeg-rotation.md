# Embedded JPEG rotation in scanned PDFs

When a scanned book page is converted to PDF, the embedded JPEG may be
stored rotated relative to the page. PyMuPDF applies the rotation
transparently when rendering, but `extract_image()` returns the raw
bytes in their *native* orientation — so a JPEG that visually represents
a horizontal spread may be stored as a tall vertical file.

User-feedback trigger (verbatim from 2026-08-05): *"Вставлять целиком
страницу скана с английским языком — это бред. Особенно, если картинка
повёрнута на 90 градусов."* The cure is detecting this case before
cropping, not after.

## Detection

```python
import fitz

src = '/path/to/scan.pdf'
doc = fitz.open(src)

for i, page in enumerate(doc):
    rect = page.rect
    for img in page.get_images(full=True):
        xref = img[0]
        bboxes = page.get_image_rects(xref)
        if not bboxes:
            continue
        bb = bboxes[0]
        page_is_landscape = rect.width > rect.height
        img_is_landscape   = bb.width   > bb.height
        if page_is_landscape != img_is_landscape:
            print(f'page {i+1}: ROTATED 90° on page '
                  f'(page {int(page_is_landscape)+1}={rect.width:.0f}x{rect.height:.0f}, '
                  f'image bbox {bb.width:.0f}x{bb.height:.0f})')
```

## Correct crop pipeline

Once rotation is detected, apply `img.transpose(Image.ROTATE_270)`
(= 90° CCW) to restore natural orientation, then crop in those
coordinates. If the rotation is the opposite direction, use
`ROTATE_90` instead.

```python
from PIL import Image
img = Image.open('page.jpeg')            # native orientation in bytes
if rotated:
    img = img.transpose(Image.ROTATE_270)
crop = img.crop((x0, y0, x1, y1))         # now in natural-orientation coords
```

After cropping, the figure can be embedded in any deliverable
(`.docx`, markdown) with correct orientation.

## Verification — one vision call catches three failure modes

After every crop pass, run:

```
vision_analyze(
    image_url=<path-to-cropped-figure>,
    question="Does this image contain any visible English or Russian text? "
             "If yes, list any text fragments. Describe the illustration "
             "briefly. Is anything cut off at the edges?",
)
```

This catches:

- **Mis-crop** (text included or illustration cut off).
- **Wrong rotation** (asking "is anything cut off" reveals it).
- **Wrong crop region** (empty whitespace or wrong subject).

The first crop almost never lands on the right coordinates. Plan for
2–3 iteration rounds, each ~1 vision call.

## Why this matters — the 2026-08-05 failure mode

A children's book PDF arrived as 6 pages, each containing one embedded
JPEG of 2409×3437 (portrait). The page rect was 824×578 (landscape).
The image bbox was 0,0,578,824 — the image was rotated 90° CCW on the
page. First crop pass took JPEG-native (vertical) coordinates, computed
crop boxes as `(0, 0%, 50%, 100%)` thinking it was the left page of the
spread — instead got the right page + caption text. The deliverable
contained full English text strips inside the figures, the user
responded with "получилось плохо, нужно переделать", and the second
crop pass had to be done after a `transpose(ROTATE_270)` + re-derive
new crop boxes.

## Related

- The end-to-end curriculum of OCR → translate → bilingual `.docx` (the
  full assembly leg, including docx table layout) lives in
  `references/bilingual-parallel-text-book.md`.
- High-DPI rendering + page-by-page PIL crop recipes are in
  `references/render-and-crop.md`.
