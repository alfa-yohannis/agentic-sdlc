"""The login page in a browser: layout, show/hide, client-side validation, accessibility."""

import json

import pytest
from playwright.sync_api import expect

from tests.helpers import (
    DEMO_EMAIL,
    DEMO_PASSWORD,
    INVALID_EMAILS,
    INVALID_PASSWORDS,
    MSG_EMAIL_EMPTY,
    MSG_EMAIL_INVALID,
    MSG_PASSWORD_EMPTY,
    MSG_PASSWORD_INVALID,
    MSG_TWO_LEFT,
    VALID_EMAILS,
    VALID_PASSWORDS,
)


def _no_newlines(values):
    # input fields strip line breaks, so those cases are covered by unit tests only
    return [v for v in values if "\n" not in v]


def open_page(page, server):
    page.goto(server.url + "/")
    return page


def submit(page, email, password):
    page.fill("#email", email)
    page.fill("#password", password)
    page.click("#login-button")


def assert_no_request(page, login_requests):
    page.wait_for_timeout(300)
    assert login_requests == []


@pytest.fixture
def fake_api(page):
    """Answer POST /api/login with a 401 so the server's state never matters."""
    page.route(
        "**/api/login",
        lambda route: route.fulfill(
            status=401,
            content_type="application/json",
            body=json.dumps({"error": "invalid_credentials", "attempts_remaining": 2}),
        ),
    )


# --- Layout (FR-1 to FR-4, NFR-17, AC-1) ------------------------------------------


def test_ac1_page_shows_fields_and_buttons(page, shared_server):
    open_page(page, shared_server)
    expect(page.get_by_label("Email", exact=True)).to_have_attribute("id", "email")
    expect(page.get_by_label("Password", exact=True)).to_have_attribute("id", "password")
    expect(page.locator("#password")).to_have_attribute("type", "password")
    expect(page.locator("#toggle-password")).to_have_text("Show")
    expect(page.locator("#login-button")).to_have_text("Login")
    expect(page.locator("#login-button")).to_be_enabled()
    expect(page.locator("#login-form")).to_be_visible()


def test_fr2_email_field_attributes(page, shared_server):
    open_page(page, shared_server)
    email = page.locator("#email")
    expect(email).to_have_attribute("type", "email")
    expect(email).to_have_attribute("autocomplete", "username")
    expect(email).to_have_attribute("placeholder", "name@example.com")
    assert email.get_attribute("required") is not None


def test_fr3_password_field_attributes(page, shared_server):
    open_page(page, shared_server)
    password = page.locator("#password")
    expect(password).to_have_attribute("type", "password")
    expect(password).to_have_attribute("autocomplete", "current-password")
    assert password.get_attribute("required") is not None


def test_fr8_form_uses_page_validation_not_browser_popups(page, shared_server):
    # "required" must not trigger the browser's own bubbles; the page shows FR-9 messages
    open_page(page, shared_server)
    assert page.locator("#login-form").get_attribute("novalidate") is not None


def test_nfr13_labels_linked_with_for(page, shared_server):
    open_page(page, shared_server)
    expect(page.locator('label[for="email"]')).to_have_text("Email")
    expect(page.locator('label[for="password"]')).to_have_text("Password")


def test_nfr17_lang_and_title(page, shared_server):
    open_page(page, shared_server)
    expect(page.locator("html")).to_have_attribute("lang", "en")
    expect(page).to_have_title("Login")


def test_fr4_no_messages_on_load(page, shared_server):
    open_page(page, shared_server)
    expect(page.locator("#email-error")).to_have_text("")
    expect(page.locator("#password-error")).to_have_text("")
    expect(page.locator("#form-message")).to_have_text("")


# --- Show/hide password (FR-5 to FR-7, AC-7, AC-8) -----------------------------------


def test_fr6_toggle_button_initial_state(page, shared_server):
    open_page(page, shared_server)
    toggle = page.locator("#toggle-password")
    expect(toggle).to_have_attribute("type", "button")
    expect(toggle).to_have_text("Show")
    expect(toggle).to_have_attribute("aria-label", "Show password")
    expect(toggle).to_have_attribute("aria-pressed", "false")


def test_ac7_fr5_show_password(page, shared_server):
    open_page(page, shared_server)
    password = page.locator("#password")
    toggle = page.locator("#toggle-password")
    password.fill(DEMO_PASSWORD)
    toggle.click()
    expect(password).to_have_attribute("type", "text")
    expect(toggle).to_have_text("Hide")
    expect(toggle).to_have_attribute("aria-label", "Hide password")
    expect(toggle).to_have_attribute("aria-pressed", "true")
    expect(password).to_have_value(DEMO_PASSWORD)


def test_ac8_fr6_hide_password_again(page, shared_server, login_requests):
    open_page(page, shared_server)
    page.fill("#email", DEMO_EMAIL)
    password = page.locator("#password")
    toggle = page.locator("#toggle-password")
    password.fill(DEMO_PASSWORD)
    toggle.click()
    toggle.click()
    expect(password).to_have_attribute("type", "password")
    expect(toggle).to_have_text("Show")
    expect(toggle).to_have_attribute("aria-label", "Show password")
    expect(toggle).to_have_attribute("aria-pressed", "false")
    expect(password).to_have_value(DEMO_PASSWORD)
    assert_no_request(page, login_requests)
    expect(page).to_have_url(shared_server.url + "/")


@pytest.mark.parametrize("key", ["Enter", " "])
def test_fr7_toggle_works_with_keyboard(page, shared_server, login_requests, key):
    open_page(page, shared_server)
    page.fill("#email", DEMO_EMAIL)
    page.fill("#password", DEMO_PASSWORD)
    toggle = page.locator("#toggle-password")
    toggle.focus()
    page.keyboard.press(key)
    expect(page.locator("#password")).to_have_attribute("type", "text")
    expect(toggle).to_have_attribute("aria-pressed", "true")
    page.keyboard.press(key)
    expect(page.locator("#password")).to_have_attribute("type", "password")
    expect(page.locator("#password")).to_have_value(DEMO_PASSWORD)
    assert_no_request(page, login_requests)


# --- Client-side validation (FR-8 to FR-11, AC-2 to AC-6) -------------------------------


def test_ac2_empty_email_shows_message_and_sends_nothing(page, shared_server, login_requests):
    open_page(page, shared_server)
    submit(page, "", DEMO_PASSWORD)
    expect(page.locator("#email-error")).to_have_text(MSG_EMAIL_EMPTY, timeout=1000)
    expect(page.locator("#password-error")).to_have_text("")
    assert_no_request(page, login_requests)


def test_vr_e1_whitespace_only_email_is_empty(page, shared_server, login_requests):
    open_page(page, shared_server)
    submit(page, "   ", DEMO_PASSWORD)
    expect(page.locator("#email-error")).to_have_text(MSG_EMAIL_EMPTY)
    assert_no_request(page, login_requests)


def test_ac3_invalid_email_shows_message_and_sends_nothing(page, shared_server, login_requests):
    open_page(page, shared_server)
    submit(page, "name@example", DEMO_PASSWORD)
    expect(page.locator("#email-error")).to_have_text(MSG_EMAIL_INVALID, timeout=1000)
    expect(page.locator("#password-error")).to_have_text("")
    assert_no_request(page, login_requests)


def test_ac4_empty_password_shows_message_and_sends_nothing(page, shared_server, login_requests):
    open_page(page, shared_server)
    submit(page, DEMO_EMAIL, "")
    expect(page.locator("#password-error")).to_have_text(MSG_PASSWORD_EMPTY, timeout=1000)
    expect(page.locator("#email-error")).to_have_text("")
    assert_no_request(page, login_requests)


def test_ac5_two_word_password_shows_format_message(page, shared_server, login_requests):
    open_page(page, shared_server)
    submit(page, DEMO_EMAIL, "green apple")
    expect(page.locator("#password-error")).to_have_text(MSG_PASSWORD_INVALID, timeout=1000)
    assert_no_request(page, login_requests)


def test_ac6_both_empty_shows_both_errors_and_focuses_email(page, shared_server, login_requests):
    open_page(page, shared_server)
    submit(page, "", "")
    expect(page.locator("#email-error")).to_have_text(MSG_EMAIL_EMPTY)
    expect(page.locator("#password-error")).to_have_text(MSG_PASSWORD_EMPTY)
    expect(page.locator("#email")).to_be_focused()
    expect(page.locator("#email")).to_have_attribute("aria-invalid", "true")
    expect(page.locator("#password")).to_have_attribute("aria-invalid", "true")
    assert_no_request(page, login_requests)


def test_fr8_both_fields_invalid_shows_both_messages(page, shared_server, login_requests):
    open_page(page, shared_server)
    submit(page, "name@example", "green apple")
    expect(page.locator("#email-error")).to_have_text(MSG_EMAIL_INVALID)
    expect(page.locator("#password-error")).to_have_text(MSG_PASSWORD_INVALID)
    assert_no_request(page, login_requests)


def test_fr10_focus_moves_to_first_invalid_field(page, shared_server):
    open_page(page, shared_server)
    submit(page, DEMO_EMAIL, "green apple")
    expect(page.locator("#password")).to_be_focused()
    expect(page.locator("#password")).to_have_attribute("aria-invalid", "true")


def test_fr10_field_error_clears_when_value_changes(page, shared_server):
    open_page(page, shared_server)
    submit(page, "", "")
    page.locator("#email").press_sequentially("u")
    expect(page.locator("#email-error")).to_have_text("")
    assert page.locator("#email").get_attribute("aria-invalid") in (None, "false")
    expect(page.locator("#password-error")).to_have_text(MSG_PASSWORD_EMPTY)
    page.locator("#password").press_sequentially("g")
    expect(page.locator("#password-error")).to_have_text("")
    assert page.locator("#password").get_attribute("aria-invalid") in (None, "false")


def test_fr8_enter_in_field_submits_and_validates(page, shared_server, login_requests):
    open_page(page, shared_server)
    page.fill("#email", "bad")
    page.fill("#password", DEMO_PASSWORD)
    page.press("#password", "Enter")
    expect(page.locator("#email-error")).to_have_text(MSG_EMAIL_INVALID)
    assert_no_request(page, login_requests)


def test_nfr13_fields_point_to_their_error_text(page, shared_server):
    open_page(page, shared_server)
    submit(page, "", "")
    for field, error_id in [("#email", "email-error"), ("#password", "password-error")]:
        described = page.locator(field).get_attribute("aria-describedby") or ""
        assert error_id in described.split()


@pytest.mark.parametrize("email", _no_newlines(VALID_EMAILS))
def test_vr_e_page_accepts_valid_email(page, shared_server, fake_api, login_requests, email):
    open_page(page, shared_server)
    submit(page, email, DEMO_PASSWORD)
    expect(page.locator("#form-message")).to_have_text(MSG_TWO_LEFT)
    expect(page.locator("#email-error")).to_have_text("")
    assert len(login_requests) == 1


@pytest.mark.parametrize("email", _no_newlines(INVALID_EMAILS))
def test_vr_e_page_rejects_invalid_email(page, shared_server, login_requests, email):
    open_page(page, shared_server)
    submit(page, email, DEMO_PASSWORD)
    expect(page.locator("#email-error")).to_have_text(MSG_EMAIL_INVALID)
    assert_no_request(page, login_requests)


@pytest.mark.parametrize("password", _no_newlines(VALID_PASSWORDS))
def test_vr_p_page_accepts_valid_password(page, shared_server, fake_api, login_requests, password):
    open_page(page, shared_server)
    submit(page, DEMO_EMAIL, password)
    expect(page.locator("#form-message")).to_have_text(MSG_TWO_LEFT)
    expect(page.locator("#password-error")).to_have_text("")
    assert len(login_requests) == 1


@pytest.mark.parametrize("password", _no_newlines(INVALID_PASSWORDS))
def test_vr_p_page_rejects_invalid_password(page, shared_server, login_requests, password):
    open_page(page, shared_server)
    submit(page, DEMO_EMAIL, password)
    expect(page.locator("#password-error")).to_have_text(MSG_PASSWORD_INVALID)
    assert_no_request(page, login_requests)


# --- Accessibility and layout (NFR-10, NFR-12 to NFR-16, AC-23) ---------------------------


def test_nfr14_form_message_is_announced(page, shared_server):
    open_page(page, shared_server)
    message = page.locator("#form-message")
    role = message.get_attribute("role")
    live = message.get_attribute("aria-live")
    assert role == "alert" or live == "assertive"


def test_ac23_tab_order_and_visible_focus(page, shared_server):
    open_page(page, shared_server)
    page.locator("#email").focus()
    order = ["email", "password", "toggle-password", "login-button"]
    for index, element_id in enumerate(order):
        if index:
            page.keyboard.press("Tab")
        expect(page.locator(f"#{element_id}")).to_be_focused()
        has_indicator = page.evaluate(
            """() => {
                const s = getComputedStyle(document.activeElement);
                const outline = s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0;
                return outline || s.boxShadow !== 'none';
            }"""
        )
        assert has_indicator, f"#{element_id} has no visible focus indicator"


@pytest.mark.parametrize("width", [320, 1920])
def test_nfr12_no_horizontal_scroll(page, shared_server, width):
    page.set_viewport_size({"width": width, "height": 800})
    open_page(page, shared_server)
    submit(page, "", "")
    expect(page.locator("#email-error")).to_have_text(MSG_EMAIL_EMPTY)
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow <= 0
    expect(page.locator("#login-button")).to_be_in_viewport()


CONTRAST_JS = """(selector) => {
    const parse = (c) => {
        const m = c.match(/rgba?\\(([^)]+)\\)/);
        if (!m) return null;
        const p = m[1].split(/[ ,\\/]+/).filter(Boolean).map(Number);
        return {r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1};
    };
    const lum = ({r, g, b}) => {
        const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
    };
    const el = document.querySelector(selector);
    const fg = parse(getComputedStyle(el).color);
    let bg = null;
    for (let n = el; n; n = n.parentElement) {
        const c = parse(getComputedStyle(n).backgroundColor);
        if (c && c.a > 0) { bg = c; break; }
    }
    bg = bg || {r: 255, g: 255, b: 255, a: 1};
    const [hi, lo] = [lum(fg), lum(bg)].sort((x, y) => y - x);
    return (hi + 0.05) / (lo + 0.05);
}"""


@pytest.mark.parametrize(
    "selector",
    ['label[for="email"]', 'label[for="password"]', "#email-error", "#password-error",
     "#toggle-password", "#login-button"],
)
def test_nfr15_text_contrast_at_least_4_5(page, shared_server, selector):
    open_page(page, shared_server)
    submit(page, "", "")
    expect(page.locator("#email-error")).to_have_text(MSG_EMAIL_EMPTY)
    assert page.evaluate(CONTRAST_JS, selector) >= 4.5


def test_nfr15_form_message_contrast_at_least_4_5(page, shared_server, fake_api):
    open_page(page, shared_server)
    submit(page, DEMO_EMAIL, DEMO_PASSWORD)
    expect(page.locator("#form-message")).to_have_text(MSG_TWO_LEFT)
    assert page.evaluate(CONTRAST_JS, "#form-message") >= 4.5
