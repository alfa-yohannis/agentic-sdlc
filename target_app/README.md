# Login app

A small web app with one login page. A registered user signs in with an email address and a password of at least three words, such as `green apple house`. After three failed attempts in a row, login is locked for 5 seconds. A successful login opens a personal page that says `Welcome, <email>`.

- Back end: Python 3 and FastAPI. It also serves the page.
- Database: SQLite, through Python's `sqlite3` module.
- Front end: plain HTML, CSS, and JavaScript, with no build step.
- Tests: pytest for unit and integration tests, and Playwright for Python for browser (end-to-end) tests.

More documentation:

- [User guide](docs/user-guide.md): how to log in, the password rule, and the lock.
- [Developer guide](docs/developer-guide.md): the project layout, the login endpoint, the database schema, and how the parts fit together.
- [Traceability](docs/traceability.md): which tests cover each requirement, and the latest results.

## Install

Run every command from the `target_app/` folder.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m playwright install chromium
```

`requirements.txt` lists what the app needs to run (FastAPI, Uvicorn). `requirements-dev.txt` adds the test tools (pytest, httpx, pytest-playwright). You need the last command only for the browser tests.

## Start the app

```sh
.venv/bin/python -m uvicorn --factory backend.app:create_app
```

Then open <http://127.0.0.1:8000/> and log in with the demo account:

- Email: `user@example.com`
- Password: `green apple house`

When the app starts, it creates the SQLite database if it doesn't exist and adds the demo account. By default the database file is `database/app.db`. To use a different file, set `LOGIN_DB_PATH`:

```sh
LOGIN_DB_PATH=/tmp/login.db .venv/bin/python -m uvicorn --factory backend.app:create_app
```

Add `--host` and `--port` to change the address, for example `--port 8765`. Stop the server with Ctrl+C.

The failed-attempt counts and the login sessions live in the server's memory, so restarting the server clears them. Accounts stay in the database.

To create the database without starting the server:

```sh
.venv/bin/python -m database.seed            # LOGIN_DB_PATH, or database/app.db if it isn't set
.venv/bin/python -m database.seed /tmp/login.db
```

## Run the tests

```sh
.venv/bin/python -m pytest -m "not e2e"   # unit and integration tests, about 1 minute
.venv/bin/python -m pytest tests/e2e      # browser tests; needs Chromium (see Install)
.venv/bin/python -m pytest                # all tests, about 2.5 minutes
```

The tests always use temporary databases and never touch `database/app.db`. Each browser test starts its own server on a free port. Some tests wait for the real 5-second lock, which is why the full run takes a few minutes.

Latest run (2026-10-09): 267 passed, 0 failed (170 unit and integration tests, 97 browser tests).
