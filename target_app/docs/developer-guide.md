# Developer guide

This guide describes the code as it is. The requirements are in `agents/shared_context/requirements-login.md` (IDs such as FR-16 and NFR-1). The interfaces the tests rely on are in `agents/shared_context/test-contract.md`.

## Project layout

```
target_app/
├── backend/
│   ├── app.py            # create_app(): routes, sessions, request handling
│   ├── lockout.py        # LoginAttemptTracker, MAX_FAILED_ATTEMPTS, LOCK_SECONDS
│   └── validation.py     # email/password format rules and the field error messages
├── database/
│   ├── db.py             # SQLite access and password hashing
│   ├── seed.py           # python -m database.seed [db_path]
│   └── app.db            # created on first start (default location)
├── frontend/
│   ├── index.html        # login page, served at /
│   ├── login.css         # served at /static/login.css
│   └── login.js          # served at /static/login.js
├── tests/
│   ├── unit/             # database, validation, lockout, static HTML checks
│   ├── integration/      # HTTP tests against create_app() with FastAPI's TestClient
│   └── e2e/              # Playwright tests against a real uvicorn server
├── docs/
├── pytest.ini            # testpaths = tests, pythonpath = ., marker e2e
├── requirements.txt      # runtime: fastapi, uvicorn
└── requirements-dev.txt  # runtime + pytest, httpx, pytest-playwright
```

`target_app/` is the import root, so the modules are imported as `backend.app`, `database.db`, and so on. Run everything from this folder.

## How the parts fit together

```
Browser (frontend/index.html + login.js)
   │  GET /                    → index.html
   │  GET /static/<file>       → frontend/<file>
   │  POST /api/login  (JSON)  → backend/app.py
   │                                ├─ validation.py   format check (422)
   │                                ├─ lockout.py      lock check, failure count (423 / 401)
   │                                └─ database/db.py  authenticate() against SQLite
   │  GET /home  (cookie)      → welcome page or 303 to /
```

1. `login.js` checks both fields with the same rules as the server. If one is invalid, it shows the field errors and sends nothing.
2. Otherwise it sends `POST /api/login` with `{"email": ..., "password": ...}` exactly as typed, and disables the Login button until the response arrives.
3. `app.py` checks, in this order: **format** (422), then **lock** (423), then **credentials** (200, 401, or 423 on the 3rd failure).
4. The page reacts to the JSON body (it doesn't read headers):

   | Status | What the page does |
   |---|---|
   | 200 | `window.location.assign(body.redirect)`, which goes to `/home` |
   | 401 | Shows `Email or password is incorrect. You have N attempts left.` using `attempts_remaining`, clears the password, and focuses it |
   | 423 | Disables Login and counts down from `retry_after`. At 0 it shows `You can try logging in again.` and enables Login again |
   | 422 with `fields` | Shows each message under its field |
   | anything else, or a network error | `Something went wrong. Please try again later.` |

The server always enforces the lock. Disabling the button in the browser only helps the user.

## Login endpoint

`POST /api/login` with a JSON body:

```json
{"email": "user@example.com", "password": "green apple house"}
```

The handler reads the body itself. A missing field, a field that isn't a string, a body that isn't a JSON object, and a body that isn't JSON are all treated as empty strings, so they get a 422. The response never repeats the input. Credentials in the query string are ignored, and `GET /api/login` returns 405.

| Case | Status | Body | Headers |
|---|---|---|---|
| Format invalid | 422 | `{"error": "validation_error", "fields": {"email": "...", "password": "..."}}` (only the invalid fields) | |
| Email currently locked (any password) | 423 | `{"error": "locked", "retry_after": S}`, where S is 1–5 | `Retry-After: S` |
| Wrong email or password, 1st or 2nd failure | 401 | `{"error": "invalid_credentials", "attempts_remaining": 2}` (then `1`) | |
| Wrong email or password, 3rd failure | 423 | `{"error": "locked", "retry_after": 5}` | `Retry-After: 5` |
| Correct | 200 | `{"ok": true, "redirect": "/home"}` | `Set-Cookie: session=...; HttpOnly; Path=/; SameSite=lax`, plus `; Secure` over HTTPS |

Notes:

- The lock check runs before the password check. While a lock is active, the password isn't checked, the count doesn't change, and the lock isn't extended.
- An unknown email and a wrong password get the same response. Both count as failures, and both are counted per normalized email (trimmed and lowercased).
- A 422 never counts as a failure.
- The `422` messages are the constants in `backend/validation.py` (`MSG_EMAIL_EMPTY`, `MSG_EMAIL_INVALID`, `MSG_PASSWORD_EMPTY`, `MSG_PASSWORD_INVALID`). `frontend/login.js` has the same texts.

Other routes:

| Route | Response |
|---|---|
| `GET /` | `frontend/index.html` |
| `GET /static/<file>` | Files from `frontend/` |
| `GET /home` with a valid `session` cookie | 200 HTML page with `<h1>Welcome, <email></h1>` (the stored email, HTML-escaped) |
| `GET /home` without a valid cookie | 303 to `/` |

FastAPI's `/docs`, `/redoc`, and `/openapi.json` are turned off.

### Sessions

On success, the server makes a token with `secrets.token_urlsafe(32)` (256 bits). It stores the token and the user's email in a dict in memory and sends the token in the `session` cookie with `HttpOnly`, `SameSite=Lax`, and `Path=/`. It adds `Secure` when the request scheme is `https` and leaves it off over plain `http`, so `http://127.0.0.1` still works. If a reverse proxy handles HTTPS, uvicorn takes the scheme from the proxy's `X-Forwarded-Proto` header, but by default it trusts that header only from `127.0.0.1`. For a proxy on another address, add `--forwarded-allow-ips <proxy address>`. There is no logout, and sessions last until the server restarts.

## Validation (`backend/validation.py`)

- **Email**: trimmed, then it must be non-empty, at most 254 characters, have a local part of at most 64 characters, and match `EMAIL_PATTERN` with `re.fullmatch`:
  `^[A-Za-z0-9_%+-]+(\.[A-Za-z0-9_%+-]+)*@([A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,}$`
- **Password**: never trimmed. It must be non-empty, at most 128 characters, contain at least 2 U+0020 spaces, and have at least 3 non-empty words when split on `" "`.
- `normalize_email(email)` returns `email.strip().lower()`. This form is the key for lookups and attempt counts.

`frontend/login.js` uses the same regex, limits, and messages.

## Lock (`backend/lockout.py`)

```python
MAX_FAILED_ATTEMPTS = 3
LOCK_SECONDS = 5
```

`LoginAttemptTracker(max_failures, lockout_seconds, clock=time.monotonic)` keeps two dicts in memory, keyed by normalized email: the failure counts and the lock end times.

- `record_failure(email)` adds 1 and returns the attempts left (2, 1, 0). Returning 0 starts a lock that lasts until `clock() + 5`.
- `retry_after(email)` returns 0 when the email isn't locked. Otherwise it returns `ceil(lock_end - clock())`, from 1 to 5.
- `record_success(email)` clears the count and any lock.
- `failures(email)` returns the current count.
- Each method first checks whether the lock has ended, and if so clears the lock and the count. Failures don't expire with time alone.

Each `create_app()` call gets its own tracker. The tests pass a fake clock to `create_app(clock=...)` so they don't have to wait.

## Database (`database/db.py`)

Schema:

```sql
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,        -- stored normalized (trimmed, lowercase)
    password_hash TEXT NOT NULL
)
```

Each function takes the database file path first and opens its own connection. All SQL uses `?` placeholders.

| Function | Returns | Behaviour |
|---|---|---|
| `init_db(db_path)` | `None` | Creates the table if needed and adds `user@example.com` / `green apple house` if that account doesn't exist. Safe to run more than once. |
| `create_user(db_path, email, password)` | new id | Normalizes the email and stores the hash. Raises `ValueError` if the email already exists. Doesn't check the password format. |
| `get_user_by_email(db_path, email)` | `{"id", "email", "password_hash"}` or `None` | Normalizes the email before the lookup. |
| `authenticate(db_path, email, password)` | user dict or `None` | Returns `None` for both an unknown email and a wrong password. For an unknown email, it still hashes the password against a dummy hash, so both cases take about the same time. |
| `hash_password(password)` | string | Uses a new random 16-byte salt every time. |
| `verify_password(password, stored_hash)` | `bool` | Compares with `hmac.compare_digest`. |

Hash format, stored in `password_hash`:

```
pbkdf2_sha256$600000$<salt_hex, 32 chars>$<hash_hex>
```

The hash is `hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 600000)`. The iteration count is stored in each hash, so `verify_password` still works if `HASH_ITERATIONS` changes later.

There is no way to register in the app. To add an account, call `create_user` from Python, for example:

```sh
.venv/bin/python -c "from database.db import init_db, create_user; init_db('database/app.db'); create_user('database/app.db', 'other@example.com', 'blue river stone')"
```

## Configuration

| Setting | Where | Default |
|---|---|---|
| Database file | env var `LOGIN_DB_PATH`, or `create_app(db_path=...)` | `database/app.db` |
| Clock for the lock | `create_app(clock=...)` | `time.monotonic` |
| Attempts and lock length | `backend/lockout.py` constants | 3 attempts, 5 seconds |
| Host and port | uvicorn `--host` / `--port` | `127.0.0.1:8000` |

`create_app()` calls `init_db()` right away, so `TestClient(create_app(...))` works without a `with` block. Importing `backend.app` doesn't create a database.

## Tests

See the [README](../README.md#run-the-tests) for the commands. In short:

- `tests/conftest.py` provides temporary databases (`db_path`, `seeded_db`) and a `FakeClock`.
- `tests/integration/conftest.py` builds `create_app(db_path=seeded_db, clock=fake_clock)` and a `TestClient`.
- `tests/e2e/conftest.py` initializes a temporary database and starts `python -m uvicorn --factory backend.app:create_app` on a free port with `LOGIN_DB_PATH` set. Most tests get their own server, so lock state never carries over from one test to the next. Tests in `tests/e2e/` get the `e2e` marker automatically, so `-m "not e2e"` skips them.

[traceability.md](traceability.md) maps each requirement to its tests.
