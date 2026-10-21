# Erin status

Waiting for Charlie, Frank, and David to report before I start the docs.

## Reports received

- Charlie (2026-10-09): database passes tests/unit/test_database.py 24/24. Spec v1 renamed the demo-user constants from DEMO_EMAIL/DEMO_PASSWORD to SEED_EMAIL/SEED_PASSWORD in target_app/database/db.py and database/seed.py. The seed user is user@example.com with password "green apple house". To seed: `cd target_app && .venv/bin/python -m database.seed [db_path]`. The default path is LOGIN_DB_PATH, or database/app.db if that is unset. Hashes use the format pbkdf2_sha256$600000$salthex$hashhex.
- Frank (2026-10-09): back end passes tests/unit/test_validation.py, tests/unit/test_lockout.py, and tests/integration ("69 + 69 passed"). Files: backend/app.py, backend/validation.py, backend/lockout.py. app.py provides create_app(db_path, lock_seconds, clock) and reads the env vars LOGIN_DB_PATH and LOGIN_LOCK_SECONDS (default 5). Start it with `uvicorn --factory backend.app:create_app`. Routes: GET /, /static/*, POST /api/login, GET /welcome. The JSON follows test-contract.md §4. /welcome uses David's /static/theme.css. requirements.txt is unchanged.
- David (2026-10-09): front end passes tests/unit/test_frontend_static.py and all of tests/e2e (85 passed). Files: index.html, login.js, login.css, and theme.css (shared with /welcome). The `Error: ` prefix comes from a CSS ::before rule. The countdown number is in an aria-live="off" span inside #form-message.

## Progress

- DONE 2026-10-09: rewrote all four docs for spec v1. The full run gave 247 passed (99 unit, 69 integration, 79 e2e) and 1 httpx deprecation warning.
- Sent the code and spec differences to Frank (stale IDs, MSG_INVALID_INPUT), David (password hint, NFR-12 countdown, stale IDs), and Charlie ("demo user" wording). Reported done to the human.
- If code changes later: rerun the tests with --junitxml=../agents/erin/results.xml, summarize with trace.py, and update traceability.md and the README's latest-run line.
- check_docs.py: the documented uvicorn command and the API responses were checked against a live server and are OK.
- Code and spec differences to report: see the final messages.
