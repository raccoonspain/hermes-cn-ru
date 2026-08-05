---
name: series-task-workflow
description: Use when a session runs a long sequence of 3+ similar items and may hit token limits. Three-file pattern (state table, history log, about.md) for cross-session resumability.
---

# Series-task-workflow

When a user asks for "do all of X" where X is a list of 3+ similar items (analyzing N problems, processing N records, generating N artifacts), the session WILL exceed token limits. Without state tracking, all progress is lost on cut.

## Trigger conditions

Apply this pattern when ANY of these hold:
- User asks to do N similar items ("реши все задачи 3.35–3.46", "обработай 50 записей", "сгенерируй 10 файлов")
- Each item requires 3+ tool calls (write file, run tests, screenshot, etc.)
- User explicitly mentions token limits, resumability, or "if you run out, remember where you stopped"
- Total work estimate ≥ 30 tool calls

## Three-file pattern (set up BEFORE starting item 1)

These three files together let the next session resume cold with no lost work.

### 1. `state_<scope>.md` — status table (FIRST thing to read on resume)

Markdown table with one row per item. Columns:
- **Item ID** (e.g., `3.35`)
- **Status**: `🔲 не сделана` / `✅ сделана` / `⏳ в работе` / `⛔ отсутствует` / `cancelled`
- **File path** (if artifact produced) or `—`
- **Key idea** (one line — formula or solution summary, for context when resuming)

Example:
```
| 3.35 | ✅ | solution_3_35.html | Two bikes meet via quadratic eq |
| 3.36 | 🔲 | — | — |
```

State.md is for **scanning**, not narrative. Keep rows terse.

### 2. `history.md` — append-only log (one block per completed item)

Each block: 3-5 lines.
- What was made (file path + size)
- Key result / formula
- What's next

**Critical**: append below existing content. Never edit old blocks. If `patch` would duplicate content (e.g., `replace_all=true` on a multi-line string appearing in multiple places), **rewrite the file with `write_file`** instead. See pitfall below.

End each block with an explicit `Дальше: <next-item-id> (<one-line description>)` pointer — this is what a resuming session scans first.

### 3. `about.md` — "На чём остановились" field

One short paragraph updated after each item. This is the FASTEST context restoration: a future session reads this first to know "what was happening, where to continue". Keep it to 3-6 lines.

## Workflow loop (repeat per item)

1. **Read** `state_<scope>.md` to confirm next item (or skip on cold start)
2. **Update** `todo` tool for in-session tracking (one item `in_progress`)
3. **Do the item**: write file, run tests, screenshot, whatever
4. **Verify** the result worked (screenshot, render check, OCR if relevant)
5. **Update atomically**:
   - state.md → mark ✅, add key idea
   - history.md → append new block with "Дальше: <next>"
   - about.md → update "На чём остановились"
6. **If interrupted by token limit**: state is preserved; next session reads state.md row 1, jumps to item N+1

## Pitfalls (learned the hard way)

### `patch` with `replace_all=true` on history.md

If `old_string` appears in multiple unrelated blocks (e.g., you patched "Дальше: 3.42 (при равноускоренном)" and that exact line appeared in 7 places), `replace_all=true` duplicates content 7x. Result: history.md becomes 150 KB of repeated blocks.

**Fix**: always include unique surrounding context (e.g., the previous block's heading) so the match is unique. Or, when editing history.md which has many similar blocks, **just rewrite the whole file** with `write_file`. It's append-only by convention, but a full rewrite is safer than a corrupted append.

### Don't combine state and history

State.md is a table for scanning. History.md is a narrative log. Mixing them makes both unreadable. Keep them separate files.

### Don't update files in batches

If you do 5 items then try to update all state at once, an interruption mid-batch leaves partial state. Update **after each item**, not in batches.

### Don't skip the verify step

Writing the HTML is not the same as the HTML working. After each item:
- Screenshot or render check (puppeteer/playwright)
- File size sanity check (>5 KB usually means real content)
- Vision check at least on item 1 of a new template to catch mojibake / broken canvas

### Don't put long narrative in state.md

The "Key idea" column should be **one line** — formula or summary. Not a paragraph. State.md's job is to be scannable in 5 seconds.

## OCR verification (sub-task pattern, applied during series work)

When extracting a task/item list from OCR'd images (textbook problems, forms, inventory lists), **never trust the task list alone**. Both false positives and false negatives are common.

### Verification recipe

1. Run OCR with reasonable resolution
2. Extract item headers by pattern (e.g., `^3\.\d+` for problem numbers)
3. **For each claimed item**, dump ALL text between this item's marker and the next item's marker
4. **If the gap is empty or contains only fragmentary noise**, the item does NOT exist in the source — OCR hallucinated or merged two pages
5. **If OCR misses an item**, retry with 2x upscaled image — formulas with subscripts/superscripts often fool OCR

### Worked example (Kirik textbook, session 2026-08-04)

OCR returned headers for `3.42`, `3.43`, `3.44`. Verification:
- Text between `3.42` and `3.43`: full condition for 3.42 (ok)
- Text between `3.43` and `3.44`: **EMPTY** → 3.43 does not exist
- Re-OCR at 2x confirmed: page went directly from 3.42 to 3.44, then 3.45, 3.46, then olympiad problems О-7, О-8 on next page

### Output convention when item is missing

In state.md, mark as `⛔ отсутствует` with note "В учебнике её нет — после <prev> сразу <next> (подтверждено повторным OCR)". Don't fabricate a solution for a problem that doesn't exist.

## When to abandon the pattern

If the user only wants 1-2 items done, skip the state.md setup — it adds overhead. The pattern pays off at 3+ items with per-item work.

If the user explicitly says "don't bother with state tracking, just do it", skip the pattern. But mention briefly that resumption won't work if token limit hits.

## Unattended continuation (no one will type "continue" for you)

The three-file pattern above assumes a **human** starts the next session and
the agent resumes cold from `state.md`. That breaks down when nobody is
going to be there — the user asked for an overnight/unattended run, or you
already retried a failing call through its full backoff ladder (see
`scan-pdf-vision-ocr`'s "Provider degraded" section) and it's still down.
Sitting there waiting, or worse, silently giving up, is the actual bug this
section exists to close — it's happened for real (2026-08-05: agent hit a
credit-exhausted 429 and just stopped; the user had to notice and type
something before anything moved again).

**Trigger conditions** (any one is enough):
- The user says the task should run overnight / unattended / "while I sleep".
- A call's backoff ladder (any skill, not just vision) ran out and the
  provider is still down — this is very likely a credit-window exhaustion
  (wormsoft.ru: 4h on our plan, see `docs/wormsoft-api.md`), not a
  transient blip, if it survived a ~4h ladder.
- You can tell from scope (state.md row count × time-per-item) that the
  work won't finish in one session/credit-window even with everything
  working.

**What to do, in order:**

1. **Make sure state.md / history.md / about.md are current right now** —
   not from three items ago. A resumed session trusts these files
   completely; stale state = lost work, not saved work.
2. **Tell the user plainly, once, in chat**: what happened, that you're
   scheduling an automatic continuation, and roughly when. Don't just go
   quiet — that's indistinguishable from being stuck.
3. **Self-schedule a wake-up** with `hermes cron` via the terminal tool
   (creating the job itself does not need approval — verified live,
   2026-08-05):
   ```
   hermes cron create '4h10m' 'Continue <task name>. First read state_<scope>.md, history.md, about.md in <project path> — they have the full picture, don'\''t re-derive it. If every row is done, say so and then remove this job with: hermes cron remove <job-id>. Otherwise resume per series-task-workflow from the first unfinished row.' \
     --name '<task>-continue' --deliver origin --workdir '<project path>' --repeat 5
   ```
   - **`4h10m`, not `4h`** — a little slack past the credit-window boundary so the resumed attempt doesn't land exactly on the edge and race the reset.
   - **`--workdir`** so the resumed session gets the project's `AGENTS.md`/`about.md` context automatically, not just the bare prompt.
   - **`--repeat 5`** as a starting guess (covers ~20h / 5 credit-windows) — cheap to over-provision since a finished task just removes the job itself (next point); expensive to under-provision and silently stop short overnight.
   - **`--deliver origin`** posts the continuation back into the same conversation the user will check — not a new/separate chat.
4. **End your turn cleanly after scheduling** — don't sit in a blocked wait alongside the cron job. The whole point is that nothing needs to stay open.
5. **On each resumed run**: read the three files first (per the normal workflow loop above), keep going. **When truly done** (every state.md row ✅), say so clearly in the final message **and remove the recurring job** (`hermes cron remove <job-id>` — the ID was printed when you created it, or `hermes cron list` to find it by name) so it doesn't keep firing on a finished task.

**Don't use this as an excuse to skip the backoff ladder.** Scheduling a
cron wake-up is for "this will genuinely outlast one credit window," not
"a single call felt slow" — that's what the ladder in `scan-pdf-vision-ocr`
is for. Cron is the layer above the ladder, not a replacement for it.

## Related

- `school-task-analyzing` — covers the actual per-item analysis workflow (canvas template, CSS variables). This skill is about the **series-level** tracking that wraps it.
- `todo` tool — for in-session tracking within one item. State.md is for cross-session.
- `memory` — captures user preferences. State.md captures session work product.