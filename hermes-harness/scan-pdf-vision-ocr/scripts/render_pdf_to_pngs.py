#!/usr/bin/env python3
"""Render every page of a PDF into PNGs at two DPI levels.

Usage:
    python3 render_pdf_to_pngs.py <input.pdf> <out_dir>

Outputs:
    <out_dir>/low/p01.png, p02.png, ...   (150 dpi — for vision_analyze OCR)
    <out_dir>/high/p01.png, p02.png, ...  (216 dpi via fitz.Matrix(3,3) — for cropping)
"""
import os, sys
import fitz


def main(pdf_path: str, out_dir: str) -> None:
    pdf = fitz.open(pdf_path)
    low_dir = os.path.join(out_dir, "low")
    high_dir = os.path.join(out_dir, "high")
    os.makedirs(low_dir, exist_ok=True)
    os.makedirs(high_dir, exist_ok=True)

    for i, page in enumerate(pdf):
        name = f"p{i+1:02d}.png"
        page.get_pixmap(dpi=150).save(os.path.join(low_dir, name))
        page.get_pixmap(matrix=fitz.Matrix(3, 3)).save(os.path.join(high_dir, name))

    print(f"Rendered {len(pdf)} pages to {low_dir} and {high_dir}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    main(sys.argv[1], sys.argv[2])