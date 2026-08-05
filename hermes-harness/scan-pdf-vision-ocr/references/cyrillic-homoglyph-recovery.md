# Cyrillic homoglyph recovery from rapidocr output (added 2026-08-05)

> **Superseded 2026-08-05 (D-022).** Root cause found: the default rapidocr
> recognition model has no Cyrillic in its vocabulary at all, so it can't
> do anything but emit Latin lookalikes. Use the bundled Cyrillic model
> instead — `RapidOCR(config_path="…/scan-pdf-vision-ocr/models/rapidocr-cyrillic/config.yaml")`,
> see Step 2.5 in `SKILL.md`. It reads Cyrillic directly; none of the
> manual reconstruction below is needed on a sandbox that has it synced.
> Keep this file only as a fallback recipe for the (should-not-happen)
> case where `models/rapidocr-cyrillic/` is missing.

## Symptom

rapidocr-onnxruntime on a clean Russian printed document returns
readable-looking text, but every Cyrillic letter has been silently
replaced by its Latin lookalike. The model *places* each character on
the right pixel column, but the *decoder* emits Latin. Coordinates
are right, text is wrong.

Concretely: a Russian official letter comes back as

```
CTPOH AnbAHC         instead of  СТРОН Альянс
BeIyLIeMy 3KOHOMHCTY instead of  Ведущему экономисту
193 TK PΦ            instead of  193 ТК РФ
AApec:143421,...     instead of  Адрес: 143421,...
```

This is a recurring property of the onnxruntime build in this Hermes
sandbox — confirmed on a labor-code official letter (single page,
2409×3437, 03.08.2026). Earlier sessions may have seen similar
issues with Kirik physics books but in the form of "Кириллица
частично искажена — нужна правка для гладкого чтения" (see
`references/kirik-session.md`), which is the same root cause at lower
severity (Kirik is mostly numbers + math, where Latin/Cyrillic
ambiguity doesn't matter much; prose-heavy Russian documents expose
it hard).

## Recovery recipe (verified 2026-08-05)

### 1. Resize with care

First OCR pass: downscale so the longest side is ≤ 2000 px to avoid
the rapidocr OOM cliff. Save as PNG (not JPEG — JPEG at high
compression makes the homoglyph decoding worse). Example for a
2409×3437 full-page scan:

```python
from PIL import Image
img = Image.open('/path/to/trebovanie_p1.jpeg')
W, H = img.size
scale = min(2000 / W, 2000 / H, 1.0)
new = img.resize((int(W*scale), int(H*scale)), Image.LANCZOS)
new.save('/tmp/trebovanie_p1_ocr.png', optimize=True)
```

### 2. Split into vertical bands for layout stability

A single OCR pass on a downscaled whole-page image misses fine
detail in header/sign zones (small print, signatures). For a
single-page official document, splitting into 5–6 horizontal bands
and OCR-ing each band at **full original resolution** gives cleaner
per-region results:

```python
bands = [
    ('header',   0,   600),   # шапка / реквизиты
    ('title',    600, 1100),  # заголовок + адресат
    ('body1',   1100, 2500),  # преамбула + пункты
    ('body2',   2500, 3200),  # ссылка на ТК + адресат подписи
    ('sign',    3200, 3437),  # подпись + строка получения
]
for name, y0, y1 in bands:
    img.crop((0, y0, W, y1)).save(f'/tmp/bands/{name}.png')
```

OCR each band, then merge all results by their `(y_in_original_image)`
coordinate into one ordered list. Bands are not strictly necessary for
1-page docs but they make the sign/header zones unambiguous.

### 3. Rescue signature / tiny-text zones with high-zoom crop + re-OCR

Tiny text reads worst under rapidocr's homoglyph decoder because the
character-height signal-to-noise ratio collapses. For signatures,
dates, реквизиты, etc.:

```python
crop = img.crop((1700, 2480, 2300, 2620))   # name-signature zone
big  = crop.resize((crop.size[0]*3, crop.size[1]*3), Image.LANCZOS)
big.save('/tmp/bands/sign_name_3x.png')
result, _ = engine('/tmp/bands/sign_name_3x.png')
# result[i] = [box, text, conf] — conf > 0.85 on the homoglyph
# string is reliable enough to disambiguate "Бенин" vs "Венин"
```

Apply this *especially* to:

- The signature line itself (ФИО подписанта).
- Any "Настоящее требование получил, подпись, дата получения" hand-fill
  area (these often have small italic print).
- The "Директору управляющей организации / договор №" block (small,
  dense, often wrapped).
- Any date that OCR returned as `17.05.24` (could be `17.05.2024`).

### 4. Reconstruct Russian manually using the homoglyph map

For each line, apply the standard map. **This is not optional** — the
output is a cipher, not Russian. Use legal/professional vocabulary,
common Russian surnames and patronymics, and context (article numbers,
contract numbers, dates, party names) to anchor the reconstruction.

| Latin homoglyph | Cyrillic letter | Notes |
|-----------------|------------------|-------|
| C | С | always |
| H | Н | uppercase; lowercase usually also H |
| O | О | uppercase; lowercase o |
| E | Е | uppercase; lowercase e |
| A | А | uppercase; lowercase a |
| T | Т | uppercase; lowercase T |
| K | К | uppercase; lowercase k |
| M | М | uppercase; lowercase m |
| p | р | lowercase Cyrillic р (uppercase usually Latin P) |
| y | у | lowercase Cyrillic у |
| B | В | uppercase; lowercase B (also визуально = В) |
| x | х | lowercase Cyrillic х |
| J | (latin J) → no Cyrillic equivalent; rapidocr uses it as Cyrillic **Л** | case-by-case |
| Y | (latin Y) → often paired with `l`/`I` to make **Ы** (`Yl`) | check context |
| 3 | **Э** or **З** | "3KOHOMHCTY" = "экономисту" (Э), "OT4ETHbIX" = "отчётных" (З) |
| IO / NO | **Ю** / **ИО** | "IpocHT" = "просит" — but "IpOCHT BaC" actually decodes as "просит вас" where "Ip" maps to "Пр" |
| R | **Я** | "R" in the decoder = Cyrillic я |
| ) | **Ж** | yes, a literal closing paren renders Cyrillic Ж |
| Φ | **Ф** | Greek capital phi = Cyrillic Ф |
| W + l/I | **Ш** / **Щ** | two-char sequence; context disambiguates Ш vs Щ |
| 6 | **Б** | "6IOIIKeTHBIX" = "бюджетных" |
| II | **П** | "IpocHT" → "просит" — the "p" maps to "р", but the "II" cluster maps to "п" or "П" |

Common word-level reconstructions:

- `Tpe6oBaHne` → `Требование` (rare letter **б** → 6)
- `o IIpeIOCTaBJIeHHH IHCbMeHHOrO O6bACHeHHA` → `о предоставлении письменного объяснения`
- `BeIyLIeMy 3KOHOMHCTY` → `Ведущему экономисту`
- `IpocHT BaC B IByXIHeBHbIY cpok` → `просит вас в двухдневный срок`
- `cJIyKeOHOY 3a1UCKH` → `служебной записки`
- `pyKOBOIHTeJIA 06ocO6JIeHHOrO 1IOIpa3IeJIeHHA` → `руководителя обособленного подразделения`
- `yaCTb 2 cT. 193 TK PΦ` → `часть 2 ст. 193 ТК РФ`

### 5. Always save the original scan as an attachment

Path: `result/attachments/<doc_name>_p1.jpeg`. The user MUST be able
to pull it up and check any ⚠-marked spot against the source. For
legal documents this isn't optional.

```python
import shutil
shutil.copy('/tmp/trebovanie_p1.jpeg',
            '/workspace/<project>/result/attachments/trebovanie_p1.jpeg')
```

### 6. Mark every uncertain reconstruction with ⚠

In the final md, build a "⚠ сомнительные места" table with columns:
# / what is uncertain / what was assumed / where in scan. Examples
from the 2026-08-05 letter:

- "Фамилия «Могарыбичев А.А.»" — rare; could be Могарыбичев /
  Могарычев / Могорычев; OCR didn't pin it down.
- "Аббревиатура «РОП»" в п. 1 — OCR `POII`; could be РОП, РоП,
  or something else; mark, ask user.
- "Полная формулировка договора" — OCR gave обрывок between
  "договора" and "№"; mark, ask user.

The user explicitly chose this approach over my guessing; they
flagged it as the safer path. Don't be overconfident in
reconstructions of rare surnames, org names, contract numbers, or
dates.

### 7. Don't loop on vision_analyze retry

When vision returns 400 on a Russian document (which it did in this
session), the rapidocr-via-homoglyph path is your friend, not your
enemy. Vision's value here is in **layout questions**
("which task numbers are on this page"), not in **transcription** of a
document rapidocr can already read (in homoglyph form). Save the
vision call for the fallback when rapidocr truly fails (handwriting,
very low-DPI), and even then prefer user-screenshot escalation.

## Output format recommendation

A clean final md for a 1-page Russian official document:

```
# <Title> (OCR-расшифровка)

> **Источник:** <path>
> **Метод OCR:** rapidocr_onnxruntime (vision вернул 400; см. pitfalls)
> **Ограничения:** Cyrillic → Latin homoglyph, ручная реконструкция
> по контексту, сомнительные места помечены ⚠.

---

## Дословный текст (восстановленная кириллица)

<verbatim Russian, in the original layout (left/right headers,
centered title, justified body)>

---

## ⚠ Сомнительные места (требуют сверки со сканом)

| # | Что вызывает сомнение | Что предположено | Где в скане |
|---|------------------------|------------------|-------------|

## Что точно считано уверенно

- <list of confidently-read fields>

## Структура документа (для ответа)

<numbered structural breakdown of sections>

## Сырые OCR-данные (для отладки)

- <paths to raw OCR output>
- <path to original scan>
```

The "Что точно считано уверенно" section is for the next agent /
session — it tells them what's safe to use directly without
re-OCR-ing, and what's still in doubt. Future разборы or ответы can
grep for that section first.