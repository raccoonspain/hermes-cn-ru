# Galanz Air-Fryer Manual — Spanish scan → Russian .docx (2026-08-05)

Session-specific lessons that don't belong in the main SKILL.md but are
useful when the next similar task arrives (short 3-page product
instruction scan, mixed-language machine-translated text, build a Word
doc from the result).

## Source

- PDF: `source/2026-08-05_CCF05082026.pdf` (1.3 MB, 3 pages, 1649×1157 px
  rendered at scale 2.0 via pypdfium2).
- Contents: "Lightwave horno" (Galanz air-fryer / lightwave convection
  oven) instruction manual. Originally Chinese, machine-translated to
  English, then to Spanish — the OCR text shows the typical artefacts
  ("onda del luz cocina estufa", "ciclon convection", numbered list
  jumping from 1 to 10 because two columns are interleaved).

## Outcome

- vision_analyze returned 400 Bad Request on the rendered page 1 — fell
  back to local rapidocr per the SKILL.md "vision is opportunistic"
  rule.
- rapidocr installed in two passes into `/workspace/<project>/.pylibs`
  because the single-shot install hit `OSError 28 No space left on device`
  despite 64 GB free on `/workspace`. See SKILL.md Pitfalls for the
  verbatim recipe.
- Two-column reading order broken on pages 2 and 3: rapidocr returned
  51 lines (page 2) and 39 lines (page 3) interleaved between left and
  right columns. Did NOT auto-split — manually reconstructed the
  structure from context (which is OK for a 3-page manual; for longer
  scans, run `scripts/batch_ocr_kirik.py` which has the column split
  built in).
- Built `result/instrukciya_aerogril_RU.docx` via python-docx with
  6 sections (Назначение / Характеристики / Конструкция / Принцип и
  преимущества (22 пункта) / Рецепты / Недостатки традиционной
  варки и фритюра) plus footer note about the machine-translation
  chain.

## What went wrong (so the next session doesn't repeat)

- Started the OCR section by reaching for `vision_analyze` first —
  wasted one tool call returning 400. The right move is "try rapidocr
  *before* vision" per SKILL.md Step 2.5.
- Tried `pip install --target=/tmp/pylibs …` first — `/tmp` is a tmpfs
  (512 MB on this VPS), the install failed with
  `failed to map segment from shared object` because the SO files
  couldn't be loaded back from tmpfs. Switched to
  `/workspace/<project>/.pylibs` and it worked.
- Did not verify that python-docx was in the .pylibs before running
  build_docx.py — module not found, lost one turn re-installing.
  Always `ls .pylibs | grep -i docx` before launching a docx-builder
  script on a fresh install.
- Did not update `about.md` ("На чём остановились") or append to
  `history.md` after producing the result — these are project
  convention files per the project's AGENTS.md. Always do both at the
  end of a successful run.

## Reusable artifacts left in this project

- `outer/extract.py` — pdfplumber text extraction (returned empty here,
  but a useful first probe; 3 lines, run before reaching for OCR).
- `outer/render_pages.py` — pypdfium2 page-to-PNG render.
- `outer/check_rapid.py` — sanity check that `RapidOCR()` instantiates
  cleanly (catches missing-dep errors early without trying a real OCR
  call).
- `outer/ocr.py` — the actual OCR loop (no column split; see warning
  above).
- `outer/build_docx.py` — the python-docx builder. Reusable as a
  template for "translate OCR'd product manual into Russian .docx" —
  structure (sections, kv-pairs, footer note) is the right shape for
  this class of task.
