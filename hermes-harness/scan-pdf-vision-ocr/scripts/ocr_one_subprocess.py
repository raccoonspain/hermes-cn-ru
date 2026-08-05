"""OCR one image, save result to JSON.

Designed to be called as a subprocess by `batch_ocr_kirik.py`. Forces single
threads to avoid the Hermes-sandbox pthread_create failure on RapidOCR.

**Uses the bundled thread-fixed config by default (D-023, 2026-08-05)** —
`intra_op_num_threads`/`inter_op_num_threads` forced to 1 instead of the
package's own `-1`/"auto". This container is capped at 1.0 vCPU, but `-1`
makes onnxruntime spawn one thread per host-visible core (8) — 8 threads
fighting over a 1-core quota. Forcing 1 thread cut a full-page OCR call
from 71s to 17.5s, byte-identical output. For new code, prefer
`ocr_page.py` instead — this file stays for `batch_ocr_kirik.py`'s
existing call site.

Usage:
  python3 ocr_one_subprocess.py <input.png> <output.json> [--lang cyrillic|latin]
"""
import os
import sys
import json
import argparse

os.environ['OMP_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'
os.environ['OPENBLAS_NUM_THREADS'] = '1'

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIGS = {
    'cyrillic': os.path.join(SKILL_DIR, 'models', 'rapidocr-cyrillic', 'config.yaml'),
    'latin': os.path.join(SKILL_DIR, 'models', 'rapidocr-latin', 'config.yaml'),
}

ap = argparse.ArgumentParser()
ap.add_argument('img_path')
ap.add_argument('out_path')
ap.add_argument('--lang', choices=['cyrillic', 'latin'], default='latin')
args = ap.parse_args()
img_path = args.img_path
out_path = args.out_path

from rapidocr_onnxruntime import RapidOCR  # noqa: E402

config_path = CONFIGS[args.lang]
engine = RapidOCR(config_path=config_path) if os.path.exists(config_path) else RapidOCR()
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
