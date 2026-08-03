---
name: local-browser-rendering
description: "Screenshot local HTML/canvas via headless Chromium; PDF render/OCR."
version: 1.0.0
author: raccoonspain (installed 2026-08-03)
platforms: [linux]
metadata:
  hermes:
    tags: [chromium, playwright, screenshot, canvas, pdf, ocr, cyrillic, weasyprint, pymupdf, rapidocr]
    related_skills: [dogfood]
---

# Local browser rendering, PDF and OCR tools

## When to use this

You need to **verify your own local work** — an HTML page or canvas
animation you just wrote, a PDF you just generated — by actually looking
at it. This is different from `browser_navigate`/`browser_snapshot`
(the built-in browser toolset): that one goes through a managed cloud
gateway and cannot reach files in your own sandbox. Use *this* toolchain
whenever the thing you need to render lives on disk (`file://...`, a path
under `/workspace`) rather than on the public internet.

Typical triggers: "проверь, что анимация на canvas работает", "сделай
скриншот HTML в обеих темах", "прочитай текст с этого PDF/скриншота
задачи", "собери печатную версию в PDF".

## Why this needs care — read before improvising

This sandbox is a hardened container (all Linux capabilities dropped
except `CHOWN`/`DAC_OVERRIDE`/`FOWNER`, `no-new-privileges` set). Two
consequences that will bite you if you skip this file and try to
"figure it out" from scratch:

1. **You have no `apt`/root.** `libnspr4`, `libnss3`, `chromium`,
   `fonts-dejavu` etc. are already installed system-wide (2026-08-03) —
   do not attempt `apt-get install`, it will fail (no root, and even
   root inside this container needs `apt-get -o APT::Sandbox::User=root`
   to work at all, which you cannot invoke anyway).
2. **`$HOME` is `/` and unwritable.** Chromium's crash handler
   (`crashpad`) derives its database path from `$HOME` and dies with a
   cryptic `Trace/breakpoint trap` if you don't override it. **Always
   run browser/PDF code with `HOME=/root`** — that path is bind-mounted
   from a durable per-profile directory outside this container's
   writable layer, so pip packages and anything else you put there
   survive container recreation. `/workspace` is your project's files,
   not a place for tool config — don't put caches there.

## What's installed (2026-08-03)

System (apt, both sandbox containers):
- `chromium` (Debian package — pulls in every runtime lib Chromium
  needs; do not chase a hand-typed lib list, the package already has it)
- `fonts-dejavu`, `fonts-liberation`, `fonts-noto-color-emoji` — DejaVu
  and Liberation both cover Cyrillic fully; no more mojibake/tofu boxes
  in screenshots or PDFs

Python (pip, installed as your own uid with `HOME=/root`, so
`~/.local/lib/...` — already on your import path, nothing to activate):
- `playwright` — drives the system Chromium (see snippet below)
- `weasyprint` — HTML/CSS → PDF (server-side, no JS/canvas execution —
  use Chromium instead if the page needs JS to render)
- `pymupdf` (`import fitz`) — fast PDF → PNG, and PDF text extraction
- `pdfplumber` — PDF → text/tables when you need the underlying content,
  not just an image
- `rapidocr-onnxruntime` (`import rapidocr_onnxruntime`) — pure-Python
  OCR, Cyrillic out of the box, no system `tesseract` needed. Prefer
  this over `vision_analyze` for extracting exact text/formulas from a
  user's uploaded photo of a problem — OCR the text, then use vision
  only for the diagram/figure part.
- `pillow`, `markdownify`

## Minimal working example

```python
import os
os.environ["HOME"] = "/root"  # do this before importing playwright

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(
        executable_path="/usr/bin/chromium",
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    for theme in ("light", "dark"):
        page = browser.new_page(viewport={"width": 900, "height": 700})
        page.emulate_media(color_scheme=theme)
        page.goto("file:///workspace/your_project/scene.html")
        page.wait_for_timeout(500)  # let canvas animation settle
        page.screenshot(path=f"/workspace/your_project/out-{theme}.png")
        page.close()
    browser.close()
```

Every flag above is load-bearing: no `executable_path` → Playwright
tries to download its own browser (will fail, no network policy
guarantee and it's redundant — the apt one already works); no
`--no-sandbox` → Chromium's own setuid sandbox needs capabilities this
container doesn't have; no `HOME=/root` → the crashpad crash described
above.

For a quick one-off from the shell instead of Python:

```
HOME=/root chromium --headless --no-sandbox --disable-gpu \
  --disable-dev-shm-usage --screenshot=/workspace/out.png \
  --window-size=900,700 file:///workspace/scene.html
```

## If this ever stops working

If a task requiring this fails again with a **missing-library** error
(chromium not found, apt-installed fonts gone), the sandbox container was
recreated since 2026-08-03 (image update, not just a restart) — apt/
system-level installs live in the container's own writable layer, not a
host mount, and don't survive that. Fix: repeat the `apt-get` step from
"What's installed" above (needs root — ask the user, you can't do this
yourself). Your `pip` packages under `/root/.local` are NOT affected by
this — `/root` is a host bind-mount (see "Why this needs care" above), so
they survive container recreation same as `/workspace` does. If you hit a
**crashpad crash** instead (`Trace/breakpoint trap`) with `chromium` still
present, you likely just forgot `HOME=/root` on this particular call —
check that before assuming the container was recreated. Either way, tell
the user plainly what happened rather than silently falling back to
`weasyprint`-only (no JS/canvas) or giving up.
