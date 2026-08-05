"""Batch-OCR a Kirik-style scan PDF, page by page, column by column.

Designed for the Hermes Docker sandbox where:
- `rapidocr-onnxruntime` OOMs at >5 MB input images, so we resize to 1200 px max.
- `pthread_create` fails when >1 RapidOCR engine is alive, so we run OCR in a
  *subprocess per column* (one engine lives and dies per call).
- We also write a `progress.json` after every page so a `Ctrl-C` / OOM /
  timeout never loses work — re-run the script and it picks up where it
  stopped.

Usage:
  PYTHONPATH=/workspace/pylib python3 scripts/batch_ocr_kirik.py \
      /path/to/scan.pdf 9 18 /path/to/output_dir

Outputs:
  <output_dir>/pNN_left.png, pNN_right.png   (resized column crops)
  <output_dir>/pNN_left.png.json             (OCR tokens: list of [y, x, text])
  <output_dir>/pNN_right.png.json
  <output_dir>/progress.json                 (cumulative dict, page-by-page)
"""
import os
import sys
import json
import gc
import subprocess
import fitz
from PIL import Image

PDF = sys.argv[1]
PAGE_START = int(sys.argv[2])  # 1-indexed inclusive
PAGE_END = int(sys.argv[3])    # 1-indexed inclusive
OUT_DIR = sys.argv[4]

MAX_DIM = 1200  # pixels on longest side, per column crop

os.makedirs(OUT_DIR, exist_ok=True)
progress_path = f'{OUT_DIR}/progress.json'
if os.path.exists(progress_path):
    with open(progress_path) as f:
        pages = json.load(f)
else:
    pages = {}

# Restrict threads to avoid pthread_create failure on this sandbox.
env = os.environ.copy()
env['OMP_NUM_THREADS'] = '1'
env['MKL_NUM_THREADS'] = '1'
env['OPENBLAS_NUM_THREADS'] = '1'
env['PYTHONPATH'] = '/workspace/pylib'

OCR_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          'ocr_one_subprocess.py')


def ocr_subprocess(path, json_path):
    """Run OCR on a single image in a fresh subprocess."""
    if os.path.exists(json_path):
        with open(json_path) as f:
            return json.load(f)
    r = subprocess.run(
        ['python3', OCR_SCRIPT, path, json_path],
        env=env, capture_output=True, text=True, timeout=180
    )
    if r.returncode != 0:
        print(f'FAIL {path}: rc={r.returncode}', flush=True)
        print('STDERR:', r.stderr[-500:], flush=True)
        return None
    print(r.stdout, end='', flush=True)
    with open(json_path) as f:
        return json.load(f)


def render_and_split(page_num):
    """Render page to PNG, then split into left/right column crops."""
    img_path = f'{OUT_DIR}/p{page_num:02d}_full.png'
    if not os.path.exists(img_path):
        pdf = fitz.open(PDF)
        pix = pdf[page_num - 1].get_pixmap(dpi=200)
        pix.save(img_path)
        del pdf
    img = Image.open(img_path)
    W, H = img.size
    if max(W, H) > MAX_DIM:
        scale = MAX_DIM / max(W, H)
        img = img.resize((int(W * scale), int(H * scale)), Image.LANCZOS)
        W, H = img.size
    left = img.crop((0, 0, W // 2, H))
    right = img.crop((W // 2, 0, W, H))
    left_path = f'{OUT_DIR}/p{page_num:02d}_left.png'
    right_path = f'{OUT_DIR}/p{page_num:02d}_right.png'
    left.save(left_path, optimize=True)
    right.save(right_path, optimize=True)
    del img
    gc.collect()
    return left_path, right_path, W, H


def boxes_to_lines(boxes, y_tol=40):
    """Bucket boxes into rows by Y, then sort each row by X."""
    lines = []
    for y, x, text in boxes:
        placed = False
        for line in lines:
            if abs(line[0][0] - y) < y_tol:
                line.append((y, x, text))
                placed = True
                break
        if not placed:
            lines.append([(y, x, text)])
    out = []
    for line in lines:
        ys = sorted(b[0] for b in line)
        line_y = ys[len(ys) // 2]
        line.sort(key=lambda b: b[1])
        out.append((line_y, ' '.join(b[2] for b in line)))
    out.sort()
    return out


for page_num in range(PAGE_START, PAGE_END + 1):
    page_key = str(page_num)
    if pages.get(page_key, {}).get('done'):
        print(f'page {page_num}: already done', flush=True)
        continue
    left_path, right_path, W, H = render_and_split(page_num)
    print(f'page {page_num} LEFT...', flush=True)
    res_l = ocr_subprocess(left_path, left_path + '.json')
    if res_l is None:
        print(f'  L failed, skipping page {page_num}', flush=True)
        continue
    gc.collect()
    print(f'  L: {len(res_l)} tokens', flush=True)
    print(f'page {page_num} RIGHT...', flush=True)
    res_r = ocr_subprocess(right_path, right_path + '.json')
    if res_r is None:
        print(f'  R failed, skipping page {page_num}', flush=True)
        continue
    gc.collect()
    print(f'  R: {len(res_r)} tokens', flush=True)

    pages[page_key] = {
        'left': res_l,
        'right': res_r,
        'width': W,
        'height': H,
        'done': True,
    }
    with open(progress_path, 'w') as f:
        json.dump(pages, f, ensure_ascii=False, indent=1)
    print(f'page {page_num} saved', flush=True)

# Emit a friendly markdown summary if requested
if '--md' in sys.argv:
    md_path = f'{OUT_DIR}/ocr.md'
    out = ['# OCR results', '']
    for k in sorted(pages.keys(), key=int):
        p = pages[k]
        out.append(f'## Page {k}')
        out.append('')
        for col in ('left', 'right'):
            lines = boxes_to_lines([(b[0], b[1], b[2]) for b in p[col]])
            out.append(f'### {col}')
            for _, text in lines:
                out.append(text)
            out.append('')
    with open(md_path, 'w') as f:
        f.write('\n'.join(out))
    print(f'md: {md_path}')

print('done', flush=True)
