# kirik-kinematika session — concrete OCR pipeline lessons

Concrete steps, fixes, and pitfalls hit while OCR-ing
`2026-07-28_Кинематика задачи.pdf` (Кирик, школьный задачник по физике,
глава 3 «Прямолинейное равноускоренное движение», задачи 3.23–3.46) and
producing per-task HTML breakdowns.

## Pipeline that worked

1. **Render only the pages you need.** A 24-page scan rendering at DPI 120
   produces ~1.5 MB base64 per page — too big to inline. Render at DPI 120
   on the first pass and only bump to 150–180 for figures you re-OCR.
2. **When the user names a specific task number (e.g. "3.27"), narrow
   before re-OCRing.** OCR one page at a time, asking "which task numbers
   are on this page?" — usually 4–8 tasks per scan page. When you find
   the target page, crop a tall vertical band around the task number and
   ask for the verbatim condition. This caps the search at ~5 vision
   calls per task instead of OCRing the entire chapter (which took 9+
   calls when hunting for 3.27 by full-chapter OCR).
3. **OCR with whole-context question first**, then a focused question.
   First vision call: "which task numbers are on this page?". Second:
   "give the verbatim conditions of tasks N, N+1, ...". The first call is
   cheap and unfocused; the second costs more but produces the artifact.
4. **For graphs: re-crop before re-OCR.** Once you know the rough region,
   crop at higher DPI and ask again with "Это ПРЯМАЯ линия или
   ступенчатая, или синусоида? Если ломаная — где изломы?". Vision can
   blur smooth lines into sinusoids on small crops; a tighter crop fixes it.
5. **When OCR disagrees with the textbook's physics, trust the textbook.**
   In this session, vision read the (a) graph of task 3.34 as a damped
   oscillation — wrong, since chapter 3 is about uniform acceleration.
   Fall back on a qualitative breakdown ("when is vₓ positive, when zero,
   when negative") instead of fabricating exact numerical coordinates.
6. **When the scan OCR is genuinely too fuzzy for a specific task, search
   the web for that problem number** (see `scanned-document-recovery`).
   Russian physics problem-bank mirrors I used successfully:
   - `djvu.online` — has the whole book indexed, often with a text snippet
     of the problem in the description.
   - `gdz.moda`, `gdz.cloud` — Kirik / Genendenshteyn task pages with
     plain-HTML conditions (solutions sometimes paywalled, conditions not).
   - `soloby.ru`, `resheba-na5.ru` — alternate sources for the same book.
   - Search pattern that worked: `"кирик" "3.27" "30 см" "1 с" "2 с"`.
   - **Always cross-check recovered conditions against the source PDF**
     (different editions renumber problems). A unique numeric value from
     the source ("30 см", "1 с") confirms you're looking at the right
     problem.

## Pitfalls hit (and fixes)

- **`pip install pymupdf` silently fails.** Used
  `pip install --target=/workspace/pylib pymupdf pillow` + `PYTHONPATH=` to
  make imports actually work. See skill Pitfalls section.
- **`file://` URL accepted by `vision_analyze` only with the working
  directory set.** When blocked, fall back to the per-URL signs of the image
  directly as part of the call. `file:///workspace/kirik_pages/page_09.png`
  worked without an HTTP server in this sandbox.
- **`http.server` runs but localhost from `vision_analyze` refused to
  connect in another sandbox.** `browser_navigate` also blocks
  `localhost` URLs as "unsafe or private". Try `file://` first; reach for
  HTTP only as last resort.
- **vision_analyze image input is path-mode by default as of v1.2.0
  (2026-08-03).** The "500 KB cap, thumbnail to 640×640" recipe below this
  line is stale — see the corrected "Passing an image to vision_analyze"
  section in SKILL.md. Default to a plain path or `file://` URI; only fall
  back to manual base64 (with a generous 1600×1600 cap, not 640×640) if a
  path-mode call genuinely errors with a specific message.
- **rapidocr-onnxruntime crashes with `pthread_create failed, error code:
  11` in this Hermes Docker sandbox.** `cat /sys/fs/cgroup/pids.max`
  returns `256` — below what onnxruntime's intra-op thread pool wants.
  Symptom: a call that worked minutes ago throws
  `EP Error … pthread_create failed … Resource temporarily unavailable`.
  Fix: do not instantiate multiple `RapidOCR()` engines in one process and
  do not run several OCR scripts in parallel against the same sandbox —
  serialize. For N pages, run them in a single Python loop with one
  engine and `OMP_NUM_THREADS=1` / `MKL_NUM_THREADS=1` exported. If it
  still fails, wait 30–60 s — the leaked threads are GC'd and a fresh
  engine works. This is a recurring container-level limitation.
- **Container resets wiped the rendered PNGs.** Re-render at start of any
  new session that resumes the OCR work.
- **Vision is bad at reading low-res smooth lines.** Multiple fresh
  crops of task 3.34's graph kept returning "затухающие колебания" /
  "синусоида" — wrong for a chapter on uniform acceleration. Treat
  physics implausibility as a stop signal and either re-crop tighter or
  deliver a qualitative answer.

## Output format for per-task HTML

Each task produced a standalone HTML file with:
- Verbatim task condition in a yellow callout (`<blockquote class="condition">`).
- "Дано" table with all parameter values, units, and SI conversions
  (`72 км/ч = 20 м/с` always explicit).
- "Идея" in a blue callout — the mental model or the formula the rest of
  the solution hangs on.
- Step-by-step solution with `<p class="formula">` for each equation.
- Green-bordered "Ответ" block with the final numeric answer and units.
- Inline `<svg>` graphs (not screenshots) for v(t), x(t), a(t). At least
  one diagram per task — viewers skim, and SVG density is the difference
  between "professional" and "draft".
- "Замечание" with a generalization or a physical intuition.

No JavaScript. CSS inline in `<style>` block per file. Single file per task,
no shared `style.css` — keeps each artifact portable and reviewable in
isolation, at the cost of duplication across N files. Switch to a shared
`style.css` only when N exceeds ~20 and folder diff becomes the main
review bottleneck.

If the user says "нет схемы" / "I don't see the diagram" after you wrote
inline SVG, do **not** rewrite the file. Render the HTML to PDF via
`weasyprint` (no browser required) and deliver the PDF alongside the
HTML — `weasyprint` reliably renders inline SVG and resolves most
"missing diagram" complaints without code changes:

```python
from weasyprint import HTML
HTML(filename='/path/to/solution.html').write_pdf('/path/to/solution.pdf')
```

## Path conventions the user expects

For this project (`/workspace/dem/fizika-kinematika/physics-tasks/`):

- **Output goes to `result/kirik/...`**, not the project root.
- The convention is recorded in a project-level `prompt_instructions.md`
  that the harness injects at session start. Look for it before writing
  anything.
- The `/home/hermes/workspace/misc-testX/...` style folders (from prior
  Hermes test sessions) are unrelated noise — ignore.
- `stat -c %i` is **not** reliable for "is this the same folder?" — the
  sandbox can bind-mount `project/x` and `project/result/x` as different
  inodes that the dashboard still shows as one logical location. After
  writing an artifact to the canonical folder, `ls -la` it to confirm
  visibility rather than asserting identity by inode.
