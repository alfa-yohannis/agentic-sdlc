# Test Contract: Login Page

Author: Bob (test engineer)
Source: `agents/shared_context/requirements-login.md` (Alice, Draft 1). Where the spec leaves a detail open, this file decides it.

The tests in `target_app/tests/` call exactly the names below. All paths are relative to `target_app/`, which is the import root (`pytest.ini` sets `pythonpath = .`). `database/` and `backend/` must be Python packages (each needs an `__init__.py`).

## 1. Database: `database/db.py` (Charlie)

Every function takes the path to the SQLite file as its first argument and opens its own connection. Tests always pass a temporary path.

| Function | Returns | Behaviour |
|---|---|---|
| `init_db(db_path: str) -> None` | `None` | Creates the file and the `users` table if missing, then seeds `user@example.com` / `green apple house` if no user has that email (FR-29). Safe to call any number of times (still one seed user). |
| `create_user(db_path: str, email: str, password: str) -> int` | new user id | Trims and lowercases the email, stores `hash_password(password)`. Raises `ValueError` if the normalized email already exists. Does not validate the password format. |
| `get_user_by_email(db_path: str, email: str) -> dict \| None` | `{"id": int, "email": str, "password_hash": str}` or `None` | Normalizes the email (trim + lowercase) before the lookup. |
| `authenticate(db_path: str, email: str, password: str) -> dict \| None` | same dict as above, or `None` | Normalizes the email; returns the user only if the password matches exactly (FR-14). Same `None` for an unknown email and a wrong password. |
| `hash_password(password: str) -> str` | encoded hash | New random 16-byte salt every call. |
| `verify_password(password: str, stored_hash: str) -> bool` | `bool` | Compares with `hmac.compare_digest` (NFR-2). |

Table `users`: at least `id INTEGER PRIMARY KEY`, `email TEXT UNIQUE NOT NULL` (stored normalized), `password_hash TEXT NOT NULL`. No column may contain the plain password (AC-22).

Hash format (NFR-1), so the tests can recompute it:

```
pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>
```

`hash_hex = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), iterations).hex()`, `iterations >= 200000`, salt 16 bytes (32 hex characters). All SQL uses `?` placeholders (NFR-3).

## 2. Back end (Frank)

### `backend/validation.py` (section 3, FR-9)

| Name | Behaviour |
|---|---|
| `EMAIL_PATTERN: str` | The reference regex from section 3.1, character for character. Apply it with `re.fullmatch` (Python's `$` also matches before a trailing `\n`). |
| `normalize_email(email: str) -> str` | `email.strip().lower()` |
| `is_valid_email(email: str) -> bool` | Trims, then VR-E1 to VR-E6 (max 254 total, local part max 64). |
| `is_valid_password(password: str) -> bool` | No trimming. VR-P1 to VR-P4: not empty, max 128 characters, `len([w for w in password.split(" ") if w]) >= 3`, at least 2 `" "`. Only U+0020 counts as a space. |
| `email_error(email: str) -> str \| None` | `None` if valid; `"Please enter your email address."` if empty after trimming; otherwise `"Please enter a valid email address, for example name@example.com."` |
| `password_error(password: str) -> str \| None` | `None` if valid; `"Please enter your password."` if `""`; otherwise `"Your password must have at least 3 words separated by spaces, for example: green apple house."` |

### `backend/lockout.py` (FR-16, FR-18 to FR-20, FR-23 to FR-25, NFR-19)

```python
MAX_FAILED_ATTEMPTS = 3
LOCK_SECONDS = 5

class LoginAttemptTracker:
    def __init__(self, max_failures: int = MAX_FAILED_ATTEMPTS,
                 lockout_seconds: float = LOCK_SECONDS,
                 clock: Callable[[], float] = time.monotonic): ...
    def retry_after(self, email: str) -> int: ...
    def record_failure(self, email: str) -> int: ...
    def record_success(self, email: str) -> None: ...
    def failures(self, email: str) -> int: ...
```

- Keys are used exactly as given; the caller passes the normalized email.
- `clock()` returns seconds as a float. Tests pass a fake clock; never call `time` directly.
- `record_failure` adds 1 and returns the attempts remaining: 2, then 1, then 0. The call that returns 0 starts the lock at `clock()`.
- `retry_after` returns 0 when not locked, otherwise `ceil(lock_end - clock())` (1 to 5). Locked while `clock() < start + 5`; at exactly `start + 5` the lock is over.
- When a lock has ended, the count is 0 again (FR-23). Every method must see this, even if `retry_after` was not called first.
- Failures never expire by time alone (FR-25). `record_success` sets the count to 0 (FR-24).

### `backend/app.py`

```python
def create_app(db_path: str | None = None,
               clock: Callable[[], float] | None = None) -> FastAPI: ...
```

- `db_path=None`: use env var `LOGIN_DB_PATH`, else `database/app.db` inside `target_app/`.
- `clock=None` means `time.monotonic`; the clock is passed to the `LoginAttemptTracker`.
- `create_app` calls `init_db(db_path)` immediately (not in a startup event), so `TestClient(create_app(...))` works without a `with` block.
- Each app instance has its own tracker and sessions (in memory, A-9).
- E2E tests start the server from `target_app/` with `LOGIN_DB_PATH` set to a temp file:
  `python -m uvicorn --factory backend.app:create_app --host 127.0.0.1 --port <port>`
- Do not create the real database at import time.

### HTTP interface

| Request | Response |
|---|---|
| `GET /` | 200, `text/html`, `frontend/index.html`. |
| `GET /static/<file>` | Files from `frontend/` (CSS, JS). |
| `POST /api/login`, format valid, not locked, correct credentials | 200, `{"ok": true, "redirect": "/home"}`, sets cookie `session`. Resets the count. |
| ... wrong credentials, 1st or 2nd failure | 401, `{"error": "invalid_credentials", "attempts_remaining": 2}` (then `1`). Identical for unknown email and wrong password. |
| ... wrong credentials, 3rd failure | 423, `{"error": "locked", "retry_after": 5}`, header `Retry-After: 5`. |
| ... any request for a locked email (right or wrong password) | 423, `{"error": "locked", "retry_after": S}`, header `Retry-After: S`, 1 ≤ S ≤ 5. Password not checked, count unchanged, lock not extended. |
| ... format invalid | 422, `{"error": "validation_error", "fields": {...}}` with only the invalid fields, messages from `email_error` / `password_error`. Not a failed attempt. |
| ... missing field, non-string value, body not a JSON object, or not JSON | 422, `{"error": "validation_error", ...}`. Treat a missing or non-string field as `""`. Must not echo the input (FastAPI's default 422 echoes it, leaking the password). |
| `GET /api/login` | 405 (NFR-4). Credentials in the query string are ignored, so `POST /api/login?email=..&password=..` with no body is 422. |
| `GET /home` with a valid `session` cookie | 200, `text/html`, `<h1>Welcome, user@example.com</h1>` (stored email, HTML-escaped). |
| `GET /home` without a valid cookie | 303, `Location: /`. |

Order of checks in `POST /api/login`: format (422) → lock (423) → credentials (200 / 401 / 423).

Cookie `session`: value from `secrets.token_urlsafe(32)`; flags `HttpOnly`, `SameSite=Lax`, path `/`; `Secure` only when the request scheme is `https` (tests use `TestClient(app, base_url="https://testserver")`). Must not contain the email or the password. Logs must never contain the password. A login must answer within 1 s (NFR-11).

## 3. Front end: `frontend/` (David)

`frontend/index.html` is served at `/`. Other files are linked as `/static/<file>` (e.g. `/static/login.js`). Plain `.js` files or inline scripts, no build step.

| Element | ID / selector | Requirements |
|---|---|---|
| Document | `html[lang="en"]`, `<title>Login</title>` | NFR-17 |
| Form | `#login-form` | has `novalidate` (the page shows FR-9 messages, not browser bubbles) |
| Email input | `#email` | `type="email"`, `autocomplete="username"`, `placeholder="name@example.com"`, `required`, `<label for="email">Email</label>` |
| Email error | `#email-error` | empty text when there is no error |
| Password input | `#password` | `type="password"` on load, `autocomplete="current-password"`, `required`, `<label for="password">Password</label>` |
| Password error | `#password-error` | empty text when there is no error |
| Show/hide button | `#toggle-password` | `type="button"`. Hidden: text `Show`, `aria-label="Show password"`, `aria-pressed="false"`. Shown: text `Hide`, `aria-label="Hide password"`, `aria-pressed="true"`. Enter and Space toggle it. |
| Login button | `#login-button` | text `Login` |
| Form message | `#form-message` | `role="alert"` or `aria-live="assertive"`; empty on load. Tests read its full text content (a nested countdown span is fine). |

- Each ID appears exactly once in `index.html` (a static test checks this).
- Tab order: `#email` → `#password` → `#toggle-password` → `#login-button`, each with a visible focus indicator (`outline` or `box-shadow`).
- Invalid field: `aria-invalid="true"` and `aria-describedby` containing its error ID. After the user edits the field: error text empty and `aria-invalid` removed (or `"false"`).
- Contrast ≥ 4.5:1 for labels, field errors, `#form-message`, `#toggle-password`, `#login-button` (NFR-15).
- No horizontal scrolling at 320 px and 1920 px wide (NFR-12).
- Responses the page must handle (it reads the JSON body, not the header):
  - 200: navigate to `redirect` from the body.
  - 401: `#form-message` = `Email or password is incorrect. You have N attempts left.` (`1 attempt left`), using `attempts_remaining`. Keep the email, clear the password, focus `#password`.
  - 423: disable `#login-button`; `#form-message` = `Too many failed attempts. Please wait S seconds before trying again.` (`1 second`), S from `retry_after`, minus 1 each second. Fields stay editable; Enter does not submit. At 0: enable the button, message `You can try logging in again.`
  - Any other status or a network error: `Something went wrong. Please try again later.`, button enabled.
- `#login-button` is disabled while a request is in progress.
- Tests compare full texts after trimming.

## 4. Test data and how to run

- Seed account: `user@example.com` / `green apple house`. Second account created by the tests: `other@example.com` / `blue river stone`. Wrong password used: `red apple house`. Unknown email: `nobody@example.com`.
- Run from `target_app/`: `.venv/bin/python -m pytest -m "not e2e"` (fast), `.venv/bin/python -m pytest tests/e2e` (browser; needs `.venv/bin/python -m playwright install chromium`), `.venv/bin/python -m pytest` (all).
- Not tested automatically: NFR-14 second half (countdown not re-announced each second).
