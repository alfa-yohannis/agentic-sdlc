"""FastAPI app: serves the login page and the login endpoint.

Start with: python -m uvicorn --factory backend.app:create_app
"""

import html
import os
import secrets
import time
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.lockout import LoginAttemptTracker
from backend.validation import email_error, normalize_email, password_error
from database.db import authenticate, init_db

APP_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = APP_ROOT / "frontend"
DEFAULT_DB_PATH = APP_ROOT / "database" / "app.db"

SESSION_COOKIE = "session"

HOME_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Home</title>
</head>
<body>
<main>
<h1>Welcome, {email}</h1>
</main>
</body>
</html>
"""


def _validation_error(email: str, password: str) -> JSONResponse | None:
    # Only the invalid fields, with the FR-9 messages. Never echo the input.
    fields = {}
    if (message := email_error(email)) is not None:
        fields["email"] = message
    if (message := password_error(password)) is not None:
        fields["password"] = message
    if not fields:
        return None
    return JSONResponse({"error": "validation_error", "fields": fields}, status_code=422)


def _locked(retry_after: int) -> JSONResponse:
    return JSONResponse(
        {"error": "locked", "retry_after": retry_after},
        status_code=423,
        headers={"Retry-After": str(retry_after)},
    )


def create_app(db_path: str | None = None,
               clock: Callable[[], float] | None = None) -> FastAPI:
    if db_path is None:
        db_path = os.environ.get("LOGIN_DB_PATH") or str(DEFAULT_DB_PATH)
    init_db(db_path)

    tracker = LoginAttemptTracker(clock=clock or time.monotonic)
    sessions: dict[str, str] = {}  # token -> stored email

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR, check_dir=False), name="static")

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's default 422 echoes the input, which may contain the password.
        return JSONResponse({"error": "validation_error"}, status_code=422)

    @app.get("/")
    def login_page() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html", media_type="text/html")

    @app.post("/api/login")
    async def login(request: Request) -> JSONResponse:
        # 1. Format. Read the body ourselves; anything missing or not a string is "".
        try:
            body = await request.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        email = body.get("email")
        password = body.get("password")
        email = email if isinstance(email, str) else ""
        password = password if isinstance(password, str) else ""
        invalid = _validation_error(email, password)
        if invalid is not None:
            return invalid

        key = normalize_email(email)

        # 2. Lock: refuse without checking the password or touching the count.
        wait = tracker.retry_after(key)
        if wait:
            return _locked(wait)

        # 3. Credentials. Unknown email and wrong password look the same.
        user = authenticate(db_path, key, password)
        if user is None:
            left = tracker.record_failure(key)
            if left == 0:
                return _locked(tracker.retry_after(key))
            return JSONResponse(
                {"error": "invalid_credentials", "attempts_remaining": left}, status_code=401
            )

        tracker.record_success(key)
        token = secrets.token_urlsafe(32)
        sessions[token] = user["email"]
        response = JSONResponse({"ok": True, "redirect": "/home"})
        # NFR-6: Secure only over HTTPS, so the cookie still works on plain http://localhost.
        response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", path="/",
                            secure=request.url.scheme == "https")
        return response

    @app.get("/home", response_model=None)
    def home(request: Request) -> HTMLResponse | RedirectResponse:
        email = sessions.get(request.cookies.get(SESSION_COOKIE, ""))
        if email is None:
            return RedirectResponse("/", status_code=303)
        return HTMLResponse(HOME_PAGE.format(email=html.escape(email)))

    return app
