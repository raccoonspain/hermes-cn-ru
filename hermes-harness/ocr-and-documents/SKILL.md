---
name: ocr-and-documents
description: "Extract text from PDFs/scans (pymupdf, marker-pdf)."
version: 2.6.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [PDF, Documents, Research, Arxiv, Text-Extraction, OCR]
    related_skills: [pdf, docx, powerpoint]
---

# PDF & Document Extraction

For DOCX: see the `docx` skill (create/edit) or use `python-docx` for structured reads.
For PPTX: see the `powerpoint` skill (full create/read/edit support).
For PDF manipulation (merge, split, forms, watermarks, creation): see the `pdf` skill.
This skill covers **text extraction from PDFs and scanned documents**.

## Step 1: Remote URL Available?

If the document has a URL, **always try `web_extract` first**:

```
web_extract(urls=["https://arxiv.org/pdf/2402.03300"])
web_extract(urls=["https://example.com/report.pdf"])
```

This handles PDF-to-markdown conversion via Firecrawl with no local dependencies.

Only use local extraction when: the file is local, web_extract fails, or you need batch processing.

## Step 2: Choose Local Extractor

| Feature | pymupdf (~25MB) | rapidocr-onnxruntime (~30MB) | marker-pdf (~3-5GB) |
|---------|-----------------|-------------------------------|---------------------|
| **Text-based PDF** | ✅ | n/a (image input only) | ✅ |
| **Scanned PDF (OCR)** | ❌ | ✅ (plain text only) | ✅ (90+ languages) |
| **Cyrillic** | n/a | ⚠️ default model can't (see below) — ✅ with bundled Cyrillic model | ✅ |
| **Tables** | ✅ (basic) | ❌ | ✅ (high accuracy) |
| **Equations / LaTeX** | ❌ | ❌ | ✅ |
| **Code blocks** | ❌ | ❌ | ✅ |
| **Forms** | ❌ | ❌ | ✅ |
| **Headers/footers removal** | ❌ | ❌ | ✅ |
| **Reading order detection** | ❌ | ❌ (per-region text only, no structure) | ✅ |
| **Images extraction** | ✅ (embedded) | n/a | ✅ (with context) |
| **Images → text (OCR)** | ❌ | ✅ | ✅ |
| **EPUB** | ✅ | n/a | ✅ |
| **Markdown output** | ✅ (via pymupdf4llm) | ❌ (plain text) | ✅ (native, higher quality) |
| **Install size** | ~25MB | ~30MB, pure Python | ~3-5GB (PyTorch + models) |
| **Needs root/sudo** | No | No | No, but often blocked by disk/tmpfs limits in this sandbox (see Pitfalls) |
| **Speed** | Instant | ~1-3s/page (CPU) | ~1-14s/page (CPU), ~0.2s/page (GPU) |

**Decision**: pymupdf for text-based PDFs (instant, no OCR needed). For **scanned pages, photographed
worksheets, or screenshots where you only need the text** (no tables/equations/layout) — use
**rapidocr-onnxruntime first**, not marker-pdf and not `vision_analyze`: a ~30MB pure-Python install
(no PyTorch, no multi-GB download, no LLM round-trip), already installed in
this sandbox as of 2026-08-03 (part of the `local-browser-rendering` skill's toolchain — if
`import rapidocr_onnxruntime` fails, self-heal with `pip install rapidocr-onnxruntime`, no root
needed). **On Cyrillic (Russian) text, the default model does not work** — it has no Cyrillic in
its vocabulary and silently emits Latin lookalikes instead (`С`→`C`, `Н`→`H`...) rather than failing
loudly. Use `scan-pdf-vision-ocr`'s bundled `models/rapidocr-cyrillic/config.yaml` via
`RapidOCR(config_path=...)` for any Cyrillic document — see that skill's Step 2.5 (root cause and fix:
D-022, 2026-08-05). Reach for `marker-pdf` only when you actually need tables, equations, or reading-order-aware
markdown from a scan — those are real gaps in rapidocr, not marker-pdf being generally "better OCR".
Reach for `vision_analyze` on a scanned page only when rapidocr's output looks wrong/garbled on
inspection, or the task needs genuine visual understanding (a diagram, a graph, handwriting rapidocr
mangled) rather than transcription — see `scan-pdf-vision-ocr` for that workflow, but try rapidocr
before it, not instead of it.

**If `vision_analyze` itself times out or errors (429/500)** — don't retry
once and move on, and don't proceed on a guess. Follow the backoff ladder in
`scan-pdf-vision-ocr`'s "Provider degraded" section (write to chat, sleep
30s→1m→5m→15m→30m→1h→2h, retry) — same rule here, not repeated in full.

```python
from rapidocr_onnxruntime import RapidOCR
engine = RapidOCR()
result, _ = engine("/path/to/page.png")   # or a numpy array / raw bytes
text = "\n".join(line[1] for line in result)  # result: [[box, text, confidence], ...]
print(text)
```

For a PDF page rather than a standalone image, render it first with pymupdf
(`page.get_pixmap(dpi=150).save('page.png')`, see the marker-pdf section below for the pattern), then
run it through the snippet above.

If the user needs marker capabilities but the system lacks ~5GB free disk:
> "This document needs OCR/advanced extraction (marker-pdf), which requires ~5GB for PyTorch and models. Your system has [X]GB free. Options: free up space, provide a URL so I can use web_extract, rapidocr-onnxruntime for plain-text OCR (works today, no extra install), or pymupdf which works for text-based PDFs but not scanned documents or equations."

---

## pymupdf (lightweight)

```bash
pip install pymupdf pymupdf4llm
```

**Via helper script**:
```bash
python scripts/extract_pymupdf.py document.pdf              # Plain text
python scripts/extract_pymupdf.py document.pdf --markdown    # Markdown
python scripts/extract_pymupdf.py document.pdf --tables      # Tables
python scripts/extract_pymupdf.py document.pdf --images out/ # Extract images
python scripts/extract_pymupdf.py document.pdf --metadata    # Title, author, pages
python scripts/extract_pymupdf.py document.pdf --pages 0-4   # Specific pages
```

**Inline**:
```bash
python3 -c "
import pymupdf
doc = pymupdf.open('document.pdf')
for page in doc:
    print(page.get_text())
"
```

---

## marker-pdf (high-quality OCR)

```bash
# Check disk space first
python scripts/extract_marker.py --check

pip install marker-pdf
```

**Via helper script**:
```bash
python scripts/extract_marker.py document.pdf                # Markdown
python scripts/extract_marker.py document.pdf --json         # JSON with metadata
python scripts/extract_marker.py document.pdf --output_dir out/  # Save images
python scripts/extract_marker.py scanned.pdf                 # Scanned PDF (OCR)
python scripts/extract_marker.py document.pdf --use_llm      # LLM-boosted accuracy
```

**CLI** (installed with marker-pdf):
```bash
marker_single document.pdf --output_dir ./output
marker /path/to/folder --workers 4    # Batch
```

---

## Arxiv Papers

```
# Abstract only (fast)
web_extract(urls=["https://arxiv.org/abs/2402.03300"])

# Full paper
web_extract(urls=["https://arxiv.org/pdf/2402.03300"])

# Search
web_search(query="arxiv GRPO reinforcement learning 2026")
```

## Split, Merge & Search

pymupdf handles these natively — use `execute_code` or inline Python:

```python
# Split: extract pages 1-5 to a new PDF
import pymupdf
doc = pymupdf.open("report.pdf")
new = pymupdf.open()
for i in range(5):
    new.insert_pdf(doc, from_page=i, to_page=i)
new.save("pages_1-5.pdf")
```

```python
# Merge multiple PDFs
import pymupdf
result = pymupdf.open()
for path in ["a.pdf", "b.pdf", "c.pdf"]:
    result.insert_pdf(pymupdf.open(path))
result.save("merged.pdf")
```

```python
# Search for text across all pages
import pymupdf
doc = pymupdf.open("report.pdf")
for i, page in enumerate(doc):
    results = page.search_for("revenue")
    if results:
        print(f"Page {i+1}: {len(results)} match(es)")
        print(page.get_text("text"))
```

No extra dependencies needed — pymupdf covers split, merge, search, and text extraction in one package.

---

## Notes

- `web_extract` is always first choice for URLs
- pymupdf is the safe default — instant, no models, works everywhere
- rapidocr-onnxruntime is the default for scanned/photographed **text** (2026-08-03) — try it before
  marker-pdf or `vision_analyze`, it's already installed and far cheaper/faster than either
- marker-pdf is for tables, equations, complex layouts on scans — install only when rapidocr's plain
  text genuinely isn't enough
- Both helper scripts accept `--help` for full usage
- marker-pdf downloads ~2.5GB of models to `~/.cache/huggingface/` on first use
- For Word docs: `pip install python-docx` (better than OCR — parses actual structure)
- For PowerPoint: see the `powerpoint` skill (uses python-pptx)
