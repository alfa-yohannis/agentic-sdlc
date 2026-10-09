# Handoff status (new spec)

- Charlie: done, 2026-10-09. 22/22 tests in tests/unit/test_database.py pass. db.py uses PBKDF2-SHA256 at 600,000 iterations (NFR-1 asks for at least 200,000, so this meets it). Functions unchanged.
- Frank: done, 2026-10-09. 168/168 unit+integration. backend/app.py, validation.py, lockout.py.

Docs written 2026-10-09: README.md, docs/user-guide.md, docs/developer-guide.md, docs/traceability.md. Full run 265 passed (unit 94, int 74, e2e 97). results.xml here.
Reported to Frank: no Secure cookie flag (NFR-6). Frank fixed it; Bob added 2 tests. Rerun: 267 passed (unit 94, int 76, e2e 97). Docs updated.
- David: done, 2026-10-09. tests/unit/test_frontend_static.py + tests/e2e: 101 passed. frontend/index.html, login.js. Title/heading "Login", label "Email", inputs required, Show/Hide toggle (aria-label "Show password"/"Hide password"). Messages: "Email or password is incorrect. You have N attempts left.", "Something went wrong. Please try again later.", "You can try logging in again." after the countdown. Handles 401 attempts_remaining (clears + focuses password), 423 retry_after (countdown in aria-live="off" span), 422 `fields` as field errors, 200 follows `redirect`.

Start the docs when all three have reported.
