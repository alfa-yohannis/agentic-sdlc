"""Logging in through the browser against the real server: success, failures, lock."""

import json
import re
import time

import pytest
from playwright.sync_api import expect

from tests.helpers import (
    DEMO_EMAIL,
    DEMO_PASSWORD,
    MSG_ONE_LEFT,
    MSG_SERVER_ERROR,
    MSG_TRY_AGAIN,
    MSG_TWO_LEFT,
    OTHER_EMAIL,
    OTHER_PASSWORD,
    UNKNOWN_EMAIL,
    WRONG_PASSWORD,
    msg_wait,
)

ANY_WAIT = re.compile(r"^Too many failed attempts\. Please wait [1-5] seconds? before trying again\.$")


def open_page(page, server):
    page.goto(server.url + "/")
    return page


def submit(page, email, password):
    page.fill("#email", email)
    page.fill("#password", password)
    page.click("#login-button")


def fail_until(page, message, email=DEMO_EMAIL):
    submit(page, email, WRONG_PASSWORD)
    expect(page.locator("#form-message")).to_have_text(message)


def lock(page):
    fail_until(page, MSG_TWO_LEFT)
    fail_until(page, MSG_ONE_LEFT)
    submit(page, DEMO_EMAIL, WRONG_PASSWORD)
    expect(page.locator("#form-message")).to_have_text(msg_wait(5))


def expect_home_page(page, server, email=DEMO_EMAIL):
    expect(page).to_have_url(server.url + "/home")
    expect(page.get_by_role("heading", name=f"Welcome, {email}")).to_be_visible()


def fake_response(page, status, body):
    page.route(
        "**/api/login",
        lambda route: route.fulfill(status=status, content_type="application/json", body=json.dumps(body)),
    )


# --- Success (AC-9, FR-12, FR-15, AC-19) ------------------------------------------------


def test_ac9_seed_account_logs_in_and_sees_welcome(page, server):
    open_page(page, server)
    submit(page, DEMO_EMAIL, DEMO_PASSWORD)
    expect_home_page(page, server)


def test_ac9_email_with_spaces_and_capitals_logs_in(page, server):
    open_page(page, server)
    submit(page, " USER@example.com ", DEMO_PASSWORD)
    expect_home_page(page, server)


def test_fr12_sends_json_post_with_typed_values(page, server):
    open_page(page, server)
    with page.expect_request("**/api/login") as info:
        submit(page, "USER@Example.com", DEMO_PASSWORD)
    request = info.value
    assert request.method == "POST"
    assert request.post_data_json == {"email": "USER@Example.com", "password": DEMO_PASSWORD}
    assert "green" not in request.url


def test_fr12_button_disabled_while_request_in_progress(page, server):
    held = []
    page.route("**/api/login", lambda route: held.append(route))
    open_page(page, server)
    submit(page, DEMO_EMAIL, DEMO_PASSWORD)
    expect(page.locator("#login-button")).to_be_disabled()
    deadline = time.monotonic() + 5
    while not held and time.monotonic() < deadline:
        page.wait_for_timeout(50)
    assert held, "no login request was sent"
    page.wait_for_timeout(300)
    expect(page.locator("#login-button")).to_be_disabled()
    held[0].continue_()
    expect_home_page(page, server)


def test_fr15_page_follows_redirect_from_response(page, server):
    fake_response(page, 200, {"ok": True, "redirect": "/home"})
    open_page(page, server)
    # the faked response sets no cookie, so /home then sends the browser back to /
    with page.expect_request(server.url + "/home"):
        submit(page, DEMO_EMAIL, DEMO_PASSWORD)


def test_nfr10_keyboard_only_login(page, server):
    open_page(page, server)
    page.locator("#email").focus()
    page.keyboard.type(DEMO_EMAIL)
    page.keyboard.press("Tab")
    page.keyboard.type(DEMO_PASSWORD)
    page.keyboard.press("Tab")
    expect(page.locator("#toggle-password")).to_be_focused()
    page.keyboard.press("Tab")
    expect(page.locator("#login-button")).to_be_focused()
    page.keyboard.press("Enter")
    expect_home_page(page, server)


@pytest.mark.parametrize("field", ["#email", "#password"])
def test_nfr10_enter_in_either_field_logs_in(page, server, field):
    open_page(page, server)
    page.fill("#email", DEMO_EMAIL)
    page.fill("#password", DEMO_PASSWORD)
    page.press(field, "Enter")
    expect_home_page(page, server)


def test_ac19_home_without_session_goes_to_login(page, server):
    page.goto(server.url + "/home")
    expect(page).to_have_url(server.url + "/")
    expect(page.locator("#login-form")).to_be_visible()


# --- Failures (AC-10 to AC-12, FR-16, FR-17) ------------------------------------------------


def test_ac10_wrong_password_shows_two_attempts_left(page, server):
    open_page(page, server)
    fail_until(page, MSG_TWO_LEFT)
    expect(page).to_have_url(server.url + "/")
    expect(page.locator("#login-button")).to_be_enabled()


def test_ac10_fr17_keeps_email_clears_password_and_focuses_it(page, server):
    open_page(page, server)
    fail_until(page, MSG_TWO_LEFT)
    expect(page.locator("#email")).to_have_value(DEMO_EMAIL)
    expect(page.locator("#password")).to_have_value("")
    expect(page.locator("#password")).to_be_focused()


def test_ac11_unknown_email_same_message(page, server):
    open_page(page, server)
    submit(page, UNKNOWN_EMAIL, DEMO_PASSWORD)
    expect(page.locator("#form-message")).to_have_text(MSG_TWO_LEFT)


def test_ac12_second_failure_shows_one_attempt_left(page, server):
    open_page(page, server)
    fail_until(page, MSG_TWO_LEFT)
    fail_until(page, MSG_ONE_LEFT)


def test_fr16_page_uses_attempts_remaining_from_server(page, server):
    fake_response(page, 401, {"error": "invalid_credentials", "attempts_remaining": 1})
    open_page(page, server)
    submit(page, DEMO_EMAIL, WRONG_PASSWORD)
    expect(page.locator("#form-message")).to_have_text(MSG_ONE_LEFT)


def test_nfr1_password_not_in_url_or_server_log(page, server):
    open_page(page, server)
    fail_until(page, MSG_TWO_LEFT)
    submit(page, DEMO_EMAIL, DEMO_PASSWORD)
    expect_home_page(page, server)
    assert "apple" not in page.url
    log = server.log_path.read_text()
    assert WRONG_PASSWORD not in log
    assert DEMO_PASSWORD not in log
    assert "apple" not in log


# --- Lock (AC-13 to AC-17, AC-20, FR-19 to FR-22) ---------------------------------------------


def test_ac13_third_failure_locks_and_counts_down(page, server):
    open_page(page, server)
    fail_until(page, MSG_TWO_LEFT)
    fail_until(page, MSG_ONE_LEFT)
    with page.expect_response("**/api/login") as info:
        submit(page, DEMO_EMAIL, WRONG_PASSWORD)
    response = info.value
    assert response.status == 423
    assert response.json()["retry_after"] == 5
    message = page.locator("#form-message")
    expect(message).to_have_text(msg_wait(5))
    seen_five = time.monotonic()
    expect(page.locator("#login-button")).to_be_disabled()
    expect(message).to_have_text(msg_wait(4), timeout=2000)
    assert 0.5 <= time.monotonic() - seen_five <= 1.8
    expect(page.locator("#login-button")).to_be_disabled()
    expect(message).to_have_text(msg_wait(1), timeout=4500)


def test_fr21_fields_editable_and_enter_does_nothing_while_locked(page, server, login_requests):
    open_page(page, server)
    lock(page)
    sent_before = len(login_requests)
    expect(page.locator("#email")).to_be_editable()
    expect(page.locator("#password")).to_be_editable()
    page.fill("#password", DEMO_PASSWORD)
    page.press("#password", "Enter")
    page.wait_for_timeout(500)
    assert len(login_requests) == sent_before
    expect(page).to_have_url(server.url + "/")


def test_ac14_api_refuses_correct_password_while_locked(page, server):
    open_page(page, server)
    lock(page)
    response = page.request.post(
        server.url + "/api/login", data={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )
    assert response.status == 423
    assert 1 <= response.json()["retry_after"] <= 5
    page.goto(server.url + "/home")
    expect(page).to_have_url(server.url + "/")


def test_ac15_lock_ends_with_try_again_message_and_three_attempts(page, server):
    open_page(page, server)
    lock(page)
    expect(page.locator("#form-message")).to_have_text(MSG_TRY_AGAIN, timeout=7000)
    expect(page.locator("#login-button")).to_be_enabled()
    fail_until(page, MSG_TWO_LEFT)


def test_ac16_login_succeeds_after_lock_expires(page, server):
    open_page(page, server)
    lock(page)
    expect(page.locator("#login-button")).to_be_enabled(timeout=7000)
    submit(page, DEMO_EMAIL, DEMO_PASSWORD)
    expect_home_page(page, server)


def test_ac17_success_resets_count(page, server, browser):
    open_page(page, server)
    fail_until(page, MSG_TWO_LEFT)
    fail_until(page, MSG_ONE_LEFT)
    submit(page, DEMO_EMAIL, DEMO_PASSWORD)
    expect_home_page(page, server)

    context = browser.new_context()
    try:
        fresh = context.new_page()
        open_page(fresh, server)
        fail_until(fresh, MSG_TWO_LEFT)
    finally:
        context.close()


def test_ac20_count_survives_reload(page, server):
    open_page(page, server)
    fail_until(page, MSG_TWO_LEFT)
    fail_until(page, MSG_ONE_LEFT)
    page.reload()
    submit(page, DEMO_EMAIL, WRONG_PASSWORD)
    expect(page.locator("#form-message")).to_have_text(msg_wait(5))


def test_nfr7_reload_does_not_bypass_lock(page, server):
    open_page(page, server)
    lock(page)
    page.reload()
    submit(page, DEMO_EMAIL, DEMO_PASSWORD)
    expect(page.locator("#form-message")).to_have_text(ANY_WAIT)
    expect(page).to_have_url(server.url + "/")


def test_fr18_lock_does_not_affect_other_account(page, server, browser):
    open_page(page, server)
    lock(page)

    context = browser.new_context()
    try:
        other = context.new_page()
        open_page(other, server)
        submit(other, OTHER_EMAIL, OTHER_PASSWORD)
        expect_home_page(other, server, email=OTHER_EMAIL)
    finally:
        context.close()


def test_fr21_fr22_page_counts_down_from_server_retry_after(page, server):
    fake_response(page, 423, {"error": "locked", "retry_after": 2})
    open_page(page, server)
    submit(page, DEMO_EMAIL, DEMO_PASSWORD)
    expect(page.locator("#form-message")).to_have_text(msg_wait(2))
    expect(page.locator("#login-button")).to_be_disabled()
    expect(page.locator("#form-message")).to_have_text(msg_wait(1), timeout=2000)
    expect(page.locator("#login-button")).to_be_disabled()
    expect(page.locator("#form-message")).to_have_text(MSG_TRY_AGAIN, timeout=2000)
    expect(page.locator("#login-button")).to_be_enabled()


# --- Other errors (FR-28, AC-21) ----------------------------------------------------------


@pytest.mark.parametrize("failure", ["500", "403", "network"])
def test_ac21_server_or_network_error_message(page, server, failure):
    if failure == "network":
        page.route("**/api/login", lambda route: route.abort())
    else:
        page.route(
            "**/api/login",
            lambda route: route.fulfill(status=int(failure), body="Error"),
        )
    open_page(page, server)
    submit(page, DEMO_EMAIL, DEMO_PASSWORD)
    expect(page.locator("#form-message")).to_have_text(MSG_SERVER_ERROR)
    expect(page.locator("#login-button")).to_be_enabled()
