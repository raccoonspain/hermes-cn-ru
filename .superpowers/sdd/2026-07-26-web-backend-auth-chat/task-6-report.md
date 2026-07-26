# Task 6 Report: Сид пользователей и entrypoint — seed_users.py, run.py

## Summary

Task 6 completed successfully. Implemented both `seed_users.py` and `run.py` following strict TDD methodology for the test-driven components. All 35 tests pass, including the 2 new seed_users tests.

## Implementation Details

### 1. TDD Implementation: seed_users.py

**Test-Driven Development Process:**

#### RED Phase
- Created `hermes-web/tests/test_seed_users.py` with 2 tests:
  - `test_seed_user_creates_user_with_hashed_password`: Verifies user creation with proper password hashing
  - `test_seed_user_duplicate_raises`: Confirms duplicate user insertion raises an exception
- Confirmed tests failed with expected error: `ModuleNotFoundError: No module named 'hermes_web.seed_users'`

#### GREEN Phase
- Created `hermes-web/hermes_web/seed_users.py` with:
  - `seed_user(conn, username, password, role, display_name)`: Core function that hashes the password and creates the user via `storage.create_user()`
  - `main()`: CLI entry point supporting interactive password input (not passed as argument for security)
  - Argument parsing for `username`, `role` (owner/participant), `display_name`, and optional `--db-path`
  - Password confirmation validation before creating user
- Confirmed both tests pass

#### Verification
- Function signatures match exactly with pre-committed modules:
  - `storage.create_user(conn, username, password_hash, role, display_name) -> None` ✓
  - `auth.hash_password(password) -> str` ✓
  - `auth.verify_password(password, password_hash) -> bool` ✓

### 2. Implementation: run.py (systemd entrypoint)

Created `hermes-web/run.py` with:
- Environment variable parsing for all configurable settings:
  - `API_SERVER_KEY` (required): Hermes API bearer token
  - `HERMES_API_BASE_URL` (optional, default: http://127.0.0.1:8642)
  - `WORMSOFT_API_KEY` (optional)
  - `PROJECT_INDEX_PLUGIN_DIR` (optional)
  - `HERMES_WEB_DB_PATH` (optional, default: alongside run.py)
  - `HERMES_WEB_HOST` (optional, default: 127.0.0.1)
  - `HERMES_WEB_PORT` (optional, default: 8643)
  - `HERMES_WEB_COOKIE_SECURE` (optional, default: true)
- `_bool_env()` helper for parsing boolean environment variables
- Proper `Config` object construction for quickchat
- `create_app()` call with all required parameters
- `web.run_app()` start with host/port configuration

### 3. Code Quality Verification

All function signatures verified against committed implementations:

**storage.py:**
- ✓ `get_connection(db_path: str) -> sqlite3.Connection`
- ✓ `create_user(conn, username, password_hash, role, display_name) -> None`
- ✓ `get_user(conn, username) -> Optional[dict]`

**auth.py:**
- ✓ `hash_password(password: str) -> str`
- ✓ `verify_password(password, password_hash) -> bool`

**quickchat.py:**
- ✓ `Config` dataclass with expected fields and defaults

**app.py:**
- ✓ `create_app(*, db_path, quickchat_config, cookie_secure=True, static_dir)`

## Test Results

### Full Test Suite Run
```
hermes-web/tests/test_seed_users.py::test_seed_user_creates_user_with_hashed_password PASSED
hermes-web/tests/test_seed_users.py::test_seed_user_duplicate_raises PASSED

Overall: 35 passed, 1 warning in 6.86s
```

### Key Test Coverage
- Seed function properly hashes passwords (not stored in plaintext)
- Password verification works via `auth.verify_password()`
- Duplicate user insertion raises appropriate exception (SQLite integrity constraint)
- All existing tests (app, auth, hermes_client, quickchat, storage) continue to pass

## Files Changed

1. **hermes-web/hermes_web/seed_users.py** (46 lines)
   - Core `seed_user()` function
   - CLI interface with `main()` entry point
   - Interactive password input with confirmation

2. **hermes-web/run.py** (56 lines)
   - systemd entrypoint
   - Environment variable configuration
   - Application startup wiring

3. **hermes-web/tests/test_seed_users.py** (22 lines)
   - 2 comprehensive tests for seed_user functionality
   - Validates password hashing
   - Validates duplicate rejection

## Self-Review Findings

### Strengths
1. Exact transcription of brief specification — no deviations
2. Proper TDD workflow: RED → GREEN phases confirmed
3. Function signatures precisely match existing committed modules
4. Security best practices implemented (password confirmation, no CLI argument transmission)
5. Comprehensive environment variable handling in run.py with sensible defaults
6. Full test suite passes (35/35) with no regressions

### Concerns
- None. Implementation is complete and correct per specification.

## Commit Details

```
Commit SHA: 3489155
Message: feat(hermes-web): сид пользователей + entrypoint для systemd
Files changed: 3
Lines added: 124
```

## Integration Notes

- `seed_users.py` ready for systemd service manual invocation (Task 8 will wire this)
- `run.py` is the systemd entrypoint that will be called by hermes-web.service unit
- Both modules follow the architecture specification exactly
- No external dependencies beyond already-installed packages (argon2, aiohttp, etc.)

---

## Post-Review Fix Report

### Issue Flagged by Reviewer

Reviewer found a spec gap in the docstrings, not a functional bug:

1. **run.py's docstring** (original lines 8-9) listed `PROJECT_INDEX_PLUGIN_DIR` as if run.py reads it directly, but the code never calls `os.environ.get("PROJECT_INDEX_PLUGIN_DIR")`.

2. **quickchat.py's docstring** (original lines 8-11) incorrectly claimed "PROJECT_INDEX_PLUGIN_DIR добавляется на sys.path тем, кто собирает Config (см. run.py...)", implying run.py was responsible for this. However, the actual code (lines 25-27 of quickchat.py) shows quickchat.py reads this variable itself at module import time.

### Root Cause Analysis

**Import chain:** `run.py` imports → `hermes_web.app` → `hermes_web.quickchat`

When `run.py` imports `create_app` from `hermes_web.app` (which in turn imports `quickchat`), Python executes quickchat.py's module-level code:
```python
_PROJECT_INDEX_DIR = os.environ.get("PROJECT_INDEX_PLUGIN_DIR")
if _PROJECT_INDEX_DIR and _PROJECT_INDEX_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_INDEX_DIR)
from project_index import core as project_index_core
```

This happens automatically as a side effect of the import, BEFORE `run.py`'s `main()` function even runs. So `run.py` does NOT need to explicitly read this variable — it works correctly via transitive import initialization.

**Conclusion:** NOT a functional bug — the sys.path setup happens correctly. This was purely a documentation issue: stale/misleading docstrings that didn't match the actual code flow.

### Fix Applied

**Commit:** 057e590 — `docs: fix stale docstrings in quickchat.py and run.py regarding PROJECT_INDEX_PLUGIN_DIR`

1. **quickchat.py docstring (lines 1-11):** Updated to correctly state:
   - "При импорте этого модуля мы сами читаем PROJECT_INDEX_PLUGIN_DIR из окружения и добавляем его на sys.path, если он задан — это происходит на уровне импорта, ещё до создания Config."
   - Accurately reflects that quickchat.py itself reads the variable at import time

2. **run.py docstring (lines 8-9):** Added clarification:
   - Added note: "Потребляется на уровне импорта hermes_web.quickchat, не прочитывается прямо этим скриптом."
   - Explains that PROJECT_INDEX_PLUGIN_DIR is consumed transitively by quickchat's import-time initialization, not by run.py's own code

### Test Results After Fix

```
35 passed, 1 warning in 21.90s
```

All tests pass with no regressions — this was purely documentation cleanup.

### Files Changed in Fix

- `hermes-web/hermes_web/quickchat.py` — docstring updated (1 change)
- `hermes-web/run.py` — docstring updated (1 change)
