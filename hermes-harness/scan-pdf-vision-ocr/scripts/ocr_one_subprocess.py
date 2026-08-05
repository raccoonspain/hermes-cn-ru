"""OCR one image, save result to JSON.

Designed to be called as a subprocess by `batch_ocr_kirik.py`. Forces single
threads to avoid the Hermes-sandbox pthread_create failure on RapidOCR.

Usage:
  python3 ocr_one_subprocess.py <input.png> <output.json>
"""
import os
import sys
import json

os.environ['OMP_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'
os.environ['OPENBLAS_NUM_THREADS'] = '1'

from rapidocr_onnxruntime import RapidOCR  # noqa: E402

img_path = sys.argv[1]
out_path = sys.argv[2]

engine = RapidOCR()
result, _ = engine(img_path)
out = []
if result:
    for bbox, text, score in result:
        y_top = min(p[1] for p in bbox)
        x_left = min(p[0] for p in bbox)
        out.append([y_top, x_left, text])

with open(out_path, 'w') as f:
    json.dump(out, f, ensure_ascii=False)
print(f'OCR {img_path}: {len(out)} tokens -> {out_path}')
