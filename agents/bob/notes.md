# Bob's notes

## Status (2026-10-09)

- Rewrote all tests and `agents/shared_context/test-contract.md` for Alice's Draft 1 spec (423 lock, `/home`, `validation_error` 422 with field messages, `invalid_credentials` 401, new labels/texts).
- `.venv` created, `requirements-dev.txt` installed, Chromium installed.
- First run against the old implementation (built for the earlier contract):
  - unit + integration: 100 failed, 68 passed. Database tests all pass. Failures are old code: no `email_error`/`password_error`, no lockout constants, old password rule, old JSON/status codes, no `/home`.
  - e2e: 56 failed, 41 passed. Failures are old page texts, title, `required`, `/home`, new JSON.
- Judgement calls made in the contract (spec silent): format check before lock check; malformed body → 422 `validation_error`; cookie name `session`; hash format pbkdf2_sha256 with >= 200000 iterations.

## Commands (from `target_app/`)

```
.venv/bin/python -m pytest -m "not e2e"
.venv/bin/python -m pytest tests/e2e
```

## Not tested automatically

- NFR-14 second half (countdown not re-announced each second).
