"""OCR one image, save result to JSON.

Designed to be called as a subprocess by `batch_ocr_kirik.py` — one process,
one `RapidOCR()` engine, then exit. That serialization is what actually
avoids the Hermes-sandbox `pthread_create failed` crash (`pids.max=256`,
see SKILL.md pitfalls): it's triggered by **multiple engines/OCR processes
alive at once over a session**, not by the thread count of a single engine.
Keep calling this one-subprocess-per-page, don't parallelize call sites.

**Uses the bundled thread-fixed config by default (superseded 2026-08-07,
D-035 — was 1, D-023 2026-08-05)** — `intra_op_num_threads`/
`inter_op_num_threads` forced to `4`, matching the sandbox container's real
CPU quota (D-034 fixed a stale 1.0 vCPU reading the container had been
stuck on; config said 4 all along). Re-measured on the real 4-vCPU
container: 1 thread 27.3s, 4 threads 11.6s, -1/auto 19.8s (still worse than
4 — spawns one thread per host-visible core, 8, oversubscribing 4 real
cores) — byte-identical output at every setting. For new code, prefer
`ocr_page.py` instead — this file stays for `batch_ocr_kirik.py`'s
existing call site.

Usage:
  python3 ocr_one_subprocess.py <input.png> <output.json> [--lang cyrillic|latin]
"""
import os
import sys
import json
import argparse

os.environ['OMP_NUM_THREADS'] = '4'
os.environ['MKL_NUM_THREADS'] = '4'
os.environ['OPENBLAS_NUM_THREADS'] = '4'

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
