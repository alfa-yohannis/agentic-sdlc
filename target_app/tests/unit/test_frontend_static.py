"""FR-1 to FR-4, FR-7, NFR-17, NFR-18: checks on frontend/index.html that need no browser."""

import re

from tests.helpers import APP_ROOT

INDEX = APP_ROOT / "frontend" / "index.html"

FR4_IDS = [
    "login-form",
    "email",
    "email-error",
    "password",
    "password-error",
    "toggle-password",
    "login-button",
    "form-message",
]


def _html():
    assert INDEX.is_file(), "frontend/index.html is missing"
    return INDEX.read_text(encoding="utf-8")


def test_fr1_index_html_exists():
    assert INDEX.is_file()


def test_fr4_every_element_id_appears_once():
    html = _html()
    for element_id in FR4_IDS:
        found = re.findall(rf"""\bid\s*=\s*["']{re.escape(element_id)}["']""", html)
        assert len(found) == 1, f"id={element_id!r} found {len(found)} times"


def test_nfr17_html_lang_en():
    assert re.search(r"""<html[^>]*\blang\s*=\s*["']en["']""", _html(), re.IGNORECASE)


def test_nfr18_no_build_step_scripts_are_plain_files():
    # scripts are referenced as plain .js files or inline, never as modules needing a bundler
    html = _html()
    for src in re.findall(r"""<script[^>]*\bsrc\s*=\s*["']([^"']+)["']""", html, re.IGNORECASE):
        assert src.endswith(".js"), src
        assert (APP_ROOT / "frontend" / src.rsplit("/", 1)[-1]).is_file(), src
