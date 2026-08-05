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

from PIL import Image
from rapidocr_onnxruntime import RapidOCR


def ocr_with_reading_order(page_path, left_col=True, right_col=True, y_bucket=20):
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

    engine = RapidOCR()
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
    rows = ocr_with_reading_order(sys.argv[1])
    text = rows_to_text(rows)
    for label in ('L', 'R'):
        if text[label]:
            print(f'=== {label} ===')
            for line in text[label]:
                print(line)
            print()