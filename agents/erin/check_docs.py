"""Check the commands and responses described in target_app/README.md and docs/.

Run from target_app/: .venv/bin/python ../agents/erin/check_docs.py
Starts the documented uvicorn command on a temporary database and prints what it returns.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

PORT = 8765
URL = f"http://127.0.0.1:{PORT}"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


opener = urllib.request.build_opener(NoRedirect)


def call(method, path, body=None, cookie=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(URL + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        resp = opener.open(req, timeout=10)
    except urllib.error.HTTPError as err:
        resp = err
    text = resp.read().decode()
    return resp.status, dict(resp.headers), text


def show(label, result):
    status, headers, text = result
    extra = {k: v for k, v in headers.items() if k in ("Retry-After", "set-cookie", "Set-Cookie", "location", "Location", "content-type")}
    print(f"{label}: {status} {extra}\n    {text[:200]}")


def main():
    tmp = tempfile.mkdtemp()
    env = {**os.environ, "LOGIN_DB_PATH": os.path.join(tmp, "login.db"), "LOGIN_LOCK_SECONDS": "3"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "--factory", "backend.app:create_app", "--port", str(PORT)],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        for _ in range(200):
            try:
                urllib.request.urlopen(URL + "/", timeout=1)
                break
            except OSError:
                time.sleep(0.1)
        show("GET /", call("GET", "/"))
        show("GET /static/theme.css", call("GET", "/static/theme.css"))
        show("GET /welcome (no cookie)", call("GET", "/welcome"))
        show("422 email", call("POST", "/api/login", {"email": "name@example", "password": "green apple house"}))
        show("422 both", call("POST", "/api/login", {"email": "", "password": "green apple"}))
        show("422 missing", call("POST", "/api/login", {}))
        show("422 not json", call("POST", "/api/login", raw=b"hello"))
        show("GET /api/login", call("GET", "/api/login"))
        bad = {"email": "user@example.com", "password": "wrong apple house"}
        show("401 #1", call("POST", "/api/login", bad))
        show("401 #2", call("POST", "/api/login", bad))
        show("429 #3", call("POST", "/api/login", bad))
        good = {"email": " User@Example.com ", "password": "green apple house"}
        show("429 correct pw while locked", call("POST", "/api/login", good))
        time.sleep(3.1)
        status, headers, text = call("POST", "/api/login", good)
        show("200 after lock", (status, headers, text))
        cookie = headers.get("set-cookie", "").split(";")[0]
        show("GET /welcome (cookie)", call("GET", "/welcome", cookie=cookie))
        show("401 after success (count reset)", call("POST", "/api/login", bad))
        show("GET /docs", call("GET", "/docs"))
    finally:
        proc.terminate()
        out, _ = proc.communicate(timeout=10)
        print("--- server log ---")
        print(out)


if __name__ == "__main__":
    main()
