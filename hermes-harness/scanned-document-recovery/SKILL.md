---
name: scanned-document-recovery
description: "Use when a PDF/image is a scan (no text layer) AND local OCR fails or is unavailable — find an online mirror or problem-bank that already has the text."
version: 1.2.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [PDF, OCR, recovery, fallback, research, problem-banks]
    related_skills: [ocr-and-documents, pdf]
---

# Scanned Document Recovery (OCR-fail Fallback)

Use this when the standard `ocr-and-documents` ladder — `web_extract` → pymupdf → rapidocr-onnxruntime → marker-pdf — has fallen through and you still need the text. The classic signal: `pymupdf` opens a 1-page PDF, `get_text()` returns `''`, `rapidocr_onnxruntime` returns empty/garbled text on a clean-looking render (not just a hard page), and `get_images()` returns a single embedded JPEG. Or `vision_analyze` times out, and there's no `tesseract`/no sudo to install it, and `pip install easyocr/marker-pdf` fails (no disk, or torch wheel won't fit in tmpfs).

This skill is **not** a substitute for the `ocr-and-documents` skill. It's a fallback to try before giving up and asking the user to type the text by hand. As of 2026-08-03, `rapidocr-onnxruntime` is installed and working in this sandbox (see `ocr-and-documents`) — if you haven't tried it yet, that's Step 2.5 in `scan-pdf-vision-ocr`, not this skill. Only land here once rapidocr's actual output (not just its presence) has failed you on this specific document.

## When to trigger

- A local file is a scan (or low-quality scan with no OCR layer).
- You have **no working local OCR that actually produced usable text**: rapidocr-onnxruntime returned empty/garbled output for this document (not merely "untried"), no tesseract in PATH, no sudo, easyocr/marker-pdf won't install, `vision_analyze` is timing out.
- The user has asked for the content, not the file itself.

## Vision-based OCR (fast path, often better than marker)

When marker-pdf is unavailable but `vision_analyze` works, you can OCR a scanned PDF much faster than installing models:

1. Render the PDF to per-page PNGs with `pymupdf` (`page.get_pixmap(dpi=150).save(...)`).
2. Send the relevant page(s) to `vision_analyze` with a targeted question asking for the exact text/numbers you need.
3. Iterate per page — vision has rate limits and per-image token costs; don't dump a 50-page scan in one call.

**Narrowing trick**: when the user gives a chapter / task number / section name, don't OCR the whole book. Map it to a narrow page range first (use the table of contents, the chapter heading you found on a sampled page, or the visible page numbers). With a 18-page scan and a "task 3.20" query, vision only needs 2–3 pages and finishes in seconds.

This is the right default for **structured lookups** ("find problem N.M in this scanned book"). marker-pdf only wins for **full-document OCR** when you need every word on every page.

## The fallback ladder

1. **Search for the same content in a public mirror** before assuming you can't get it.
   - Russian-language problem books: FIZMATBANK, test-uz.ru, sd-rt.ru, djvu.online, author faculty pages, **gdz.moda**, **gdz.cloud**, **soloby.ru**, **resheba-na5.ru**, **thenewschool.ru**.
   - Western textbooks: archive.org, libgen mirrors, OpenStax, the publisher's preview chapter, university course pages.
   - Search pattern: `"<author> <book title> problem <number> <topic>"` (or Russian equivalent).
   - For Russian physics problem books, the **djvu.online** page for the whole book often contains a text snippet of the problem in the description or preview — useful when you need the condition but don't want to scrape an entire PDF. Search like: `"кирик" "<book title>" "3.27"`.

2. **Inspect the mirror's link pattern in one shot, don't click one-by-one.**
   - Problem-bank sites usually have a visible list of problem numbers that link to separate task pages. The visible URL is `…/book/85`; the per-task URL is hidden in HTML.
   - In the browser, run:
     ```js
     document.querySelector('.book_taskslist, [class*="task"]').innerHTML
     ```
     You get every link at once (e.g. `href="/tasks/id/46331"` for `1.1`, `/tasks/id/46332` for `1.2`).

3. **Navigate directly to the per-task URL.** Don't try to "click" the list — `browser_click` on link-text nodes often doesn't fire navigation. Use `browser_navigate` to the absolute URL.

4. **Read the condition from the snapshot.** The condition is usually in plain HTML even when solutions are paywalled. Search the snapshot for a cell that contains the problem text; paywalled sections will say "Cost: 15 rub" / "Login required" and you can ignore them.

5. **Verify the recovered condition matches your source.** If the recovered text describes a different problem (different book edition, different numbering), keep searching — different editions renumber problems. Cross-check any unique numeric value (e.g. "30 cm", "1 с", "2 с") against your source to confirm you're looking at the right one.

6. **If no mirror exists**, escalate to the user with a clear shortlist:
   - paste the text
   - drop a photo of the page
   - give a URL to the book online

## Concrete worked example: Черноуцан, "Физика. Задачи с ответами и решениями"

PDF is a single-page scan of one problem set; local OCR dead; `vision_analyze` timed out. Recovery path that worked:

- `web_search("Черноуцан физика задача 1.1 1.2 условие текст")` → FIZMATBANK book page found.
- `browser_navigate("https://fizmatbank.ru/tasks/book/85")` → page lists `1.1 … 4.119` as a grid of links.
- `browser_console(expression="document.querySelector('.book_taskslist').innerHTML")` → reveals URL pattern `/tasks/id/<id>`.
- `browser_navigate("https://fizmatbank.ru/tasks/id/46331")` and `…/id/46332` → conditions are in plain HTML in the snapshot. Paywall only blocks the full solution, not the problem statement.

## Pitfalls

- **Don't try to install marker-pdf in a no-disk / no-sudo environment.** It'll fail and waste 5–10 minutes. Spot-check with `df -h` and `which tesseract` first.
- **`browser_click` on a plain link-text node often doesn't navigate** in headless mode. Inspect the `href` and `browser_navigate` directly. (When in doubt, use `browser_console` to extract all links in one go.)
- **`vision_analyze` can silently time out** on large scans (>1MB PNG) with no error to the agent. A single call hanging >60s is a signal to check on it, **not** a signal to give up on vision entirely — see the backoff ladder below before jumping to the mirror-search fallback. This skill's actual trigger is "vision has been down for a while AND a public mirror plausibly exists", not "one call felt slow".
- **`vision_analyze` on parallel batches has rate limits**. If you spam 10 calls at once, some will fail with `Request timed out` or `Connection error`. Retry the failed ones individually with a brief gap.
- **If `vision_analyze` is genuinely down (timeout/429/500), don't retry once and move on — follow the backoff ladder** from `scan-pdf-vision-ocr`'s "Provider degraded" section: write to chat, sleep `30s → 1m → 5m → 15m → 30m → 1h → 2h`, retry (≈3h51m total, just under the 4h wormsoft.ru credit window). **This skill (mirror search) is a legitimate parallel/first move if a mirror plausibly exists** — no reason to block on vision if the same text is one search away — but don't reach for it as a shortcut past the ladder just because a vision call felt slow. If the ladder exhausts and no mirror exists either, that's genuinely stuck — follow `series-task-workflow`'s unattended-continuation section instead of idling.
- **Don't OCR the whole book for one task**. If the user asks for "task 3.20", find which page chapter 3 starts on first, then vision only that page-range.
- **`web_extract` cannot fetch JS-rendered pages.** If the mirror renders problem text only after JS, use the browser, not `web_extract`.
- **Watch the disk**. `pip install easyocr` pulls `torch` ~526 MB, which may exceed the tmpfs `/tmp` (often 512 MB) even when overlayfs has 70 GB free. Set `TMPDIR=/workspace/tmp` and `PIP_NO_CACHE_DIR=1` if you must try, but prefer the mirror approach first.
- **Don't pollute memory with "tool X is broken"** when the issue was just an environment constraint. Capture the *fallback* (mirror search or vision-OCR), not the failure.

## Verification

After recovering the text, sanity-check it against the source PDF by re-reading the rendered page with `pymupdf` and looking for a unique phrase from the problem statement — confirms you're solving the right problem.

## Related

- `ocr-and-documents` — the normal extraction ladder; this skill is invoked only when that ladder ends in OCR-fail.
- `pdf` — for PDF manipulation once you have the text.
- `web_search` and `browser_navigate` — the actual tools that do the recovery.
