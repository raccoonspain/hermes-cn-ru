"""OCR a page with rapidocr_onnxruntime and group blocks into reading order.

rapidocr returns boxes as a flat list `[bbox, text, score]`. Raw output is
unordered. For Кирик-style double-column scans you want left-column blocks
top-to-bottom, then right-column blocks top-to-bottom.

Strategy:
  1. Crop each column separately (left/right).
  2. OCR each crop.
  3. Sort by (y_top, x_left) within the column.
  4. Group blocks into "rows" by y-bucket (delta <= ~20 px on DPI 200).
  5. Yield text as lines: join same-row boxes left-to-right with a space.

This recovers reading order much better than sorting all blocks together,
because rapidocr does not know about columns.
"""

import os
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

# Thread-fixed bundled config (D-023, 2026-08-05) — package default
# `intra_op_num_threads: -1` spawns one thread per host-visible core (8)
# on a container capped at 1.0 vCPU, ~4x slower than forcing 1 thread for
# identical output. `lang='cyrillic'` for Russian scans (D-022 — default
# rec model has no Cyrillic in its vocabulary, not just "worse" on it).
_SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _config_path(lang='latin'):
    path = os.path.join(_SKILL_DIR, 'models', f'rapidocr-{lang}', 'config.yaml')
    return path if os.path.exists(path) else None


def ocr_with_reading_order(page_path, left_col=True, right_col=True, y_bucket=20,
                            lang='latin'):
    """OCR a page (or both columns of a spread), grouped into rows.

    Returns: list of rows, each row is a list of strings (left→right).
    """
    img = Image.open(page_path)
    W, H = img.size
    crops = []
    if left_col:
        crops.append(('L', img.crop((0, 0, W // 2, H))))
    if right_col:
        crops.append(('R', img.crop((W // 2, 0, W, H))))

    config_path = _config_path(lang)
    engine = RapidOCR(config_path=config_path) if config_path else RapidOCR()
    all_rows = []
    for label, crop in crops:
        path = f'/tmp/__ocr_{label}.png'
        crop.save(path)
        result, _ = engine(path)
        if not result:
            continue
        # group by y-bucket
        rows: dict[int, list[tuple[int, str]]] = {}
        for bbox, text, _score in result:
            y_top = min(p[1] for p in bbox)
            x_left = min(p[0] for p in bbox)
            bucket = int(y_top // y_bucket) * y_bucket
            rows.setdefault(bucket, []).append((x_left, text))
        for bucket in sorted(rows):
            row = sorted(rows[bucket])  # x_left ascending
            all_rows.append([label, bucket] + [t for _, t in row])
    return all_rows


def rows_to_text(rows, join=' '):
    """Convert grouped rows to plain text per column."""
    out = {'L': [], 'R': []}
    for row in rows:
        label = row[0]
        line = join.join(row[2:])
        out[label].append(line)
    return out


if __name__ == '__main__':
    import sys
    lang = 'cyrillic' if '--cyrillic' in sys.argv else 'latin'
    path = [a for a in sys.argv[1:] if not a.startswith('--')][0]
    rows = ocr_with_reading_order(path, lang=lang)
    text = rows_to_text(rows)
    for label in ('L', 'R'):
        if text[label]:
            print(f'=== {label} ===')
            for line in text[label]:
                print(line)
            print()