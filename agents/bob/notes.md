# Bob's notes

## Status (2026-10-21)

- `target_app/` was empty (reset). Wrote a fresh suite from Alice's Draft 1 spec (unchanged since 2026-10-09 apart from the status line).
- Setup: `target_app/.venv`, `requirements-dev.txt`, `pytest.ini` (`pythonpath = .`, marker `e2e`). Chromium installed.
- Contract additions: page handles 422 by showing `fields` in the field errors; e2e creates per-test accounts in the live server's temp DB; Windows run commands.
- First run, before any code:
  - unit + integration: 224 tests, all fail. 162 `No module named 'backend'`, 35 `No module named 'database'`, 27 `missing frontend/index.html`. No test errors of other kinds.
  - e2e: 68 tests, all error because uvicorn cannot import `backend.app`.
  - Raw output: `run-unit.txt`, `run-e2e.txt` in this folder.
- The e2e tests have not run against a real page yet. Recheck them when David's page exists.

## Commands (from `target_app/`, Windows)

```
.venv/Scripts/python -m pytest -m "not e2e"
.venv/Scripts/python -m pytest tests/e2e
```

## Not tested automatically

- NFR-14 second half (countdown not re-announced each second).
