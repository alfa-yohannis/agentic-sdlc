"""POST /api/login, GET /, GET /home against a real temporary SQLite database.

The lock clock is a fake clock, so no test waits in real time.
"""

import logging
import time

import pytest

from tests.helpers import (
    DEMO_EMAIL,
    DEMO_PASSWORD,
    EMPTY_EMAILS,
    INVALID_EMAILS,
    INVALID_PASSWORDS,
    MSG_EMAIL_EMPTY,
    MSG_EMAIL_INVALID,
    MSG_PASSWORD_EMPTY,
    MSG_PASSWORD_INVALID,
    OTHER_EMAIL,
    OTHER_PASSWORD,
    UNKNOWN_EMAIL,
    WRONG_PASSWORD,
)

SUCCESS = {"ok": True, "redirect": "/home"}


def login(client, email, password):
    return client.post("/api/login", json={"email": email, "password": password})


def fail(client, email=DEMO_EMAIL, times=1):
    responses = [login(client, email, WRONG_PASSWORD) for _ in range(times)]
    return responses[-1]


def invalid_credentials(n):
    return {"error": "invalid_credentials", "attempts_remaining": n}


def locked(seconds):
    return {"error": "locked", "retry_after": seconds}


def assert_locked(response, seconds):
    assert response.status_code == 423
    assert response.json() == locked(seconds)
    assert response.headers["retry-after"] == str(seconds)


# --- Page (FR-1) ------------------------------------------------------------


def test_fr1_get_root_returns_login_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'id="login-form"' in response.text


# --- Success (FR-14, FR-15, FR-26, AC-9) ---------------------------------------


def test_fr15_correct_credentials_return_ok_and_redirect(client):
    response = login(client, DEMO_EMAIL, DEMO_PASSWORD)
    assert response.status_code == 200
    assert response.json() == SUCCESS


def test_ac9_email_is_trimmed_and_case_insensitive(client):
    response = login(client, " USER@example.com ", DEMO_PASSWORD)
    assert response.status_code == 200
    assert response.json() == SUCCESS


def test_ac9_fr26_home_shows_welcome_with_stored_email(client):
    login(client, " USER@example.com ", DEMO_PASSWORD)
    response = client.get("/home", follow_redirects=False)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert f"Welcome, {DEMO_EMAIL}" in response.text


def test_ac19_fr27_home_without_session_redirects_to_root(client):
    response = client.get("/home", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_fr27_home_with_forged_session_redirects_to_root(client):
    client.cookies.set("session", "not-a-real-token")
    response = client.get("/home", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_nfr6_session_cookie_flags(client):
    response = login(client, DEMO_EMAIL, DEMO_PASSWORD)
    set_cookie = response.headers["set-cookie"]
    assert set_cookie.startswith("session=")
    lowered = set_cookie.lower()
    assert "httponly" in lowered
    assert "samesite=lax" in lowered
    token = set_cookie.split(";", 1)[0].split("=", 1)[1]
    assert len(token) >= 22  # at least 128 bits as URL-safe base64
    assert DEMO_EMAIL not in token
    assert "green" not in token


def test_nfr6_session_cookie_secure_over_https(app):
    from fastapi.testclient import TestClient

    https_client = TestClient(app, base_url="https://testserver")
    response = login(https_client, DEMO_EMAIL, DEMO_PASSWORD)
    assert response.status_code == 200
    assert "secure" in [p.strip().lower() for p in response.headers["set-cookie"].split(";")]


def test_nfr6_session_cookie_not_secure_over_http(client):
    response = login(client, DEMO_EMAIL, DEMO_PASSWORD)
    assert "secure" not in [p.strip().lower() for p in response.headers["set-cookie"].split(";")]


def test_nfr6_session_tokens_are_random(new_client):
    first = login(new_client(), DEMO_EMAIL, DEMO_PASSWORD).cookies.get("session")
    second = login(new_client(), DEMO_EMAIL, DEMO_PASSWORD).cookies.get("session")
    assert first and second and first != second


def test_fr15_failed_login_sets_no_session(client):
    response = fail(client)
    assert "session" not in response.cookies
    assert client.get("/home", follow_redirects=False).status_code == 303


# --- Failures (FR-16, FR-18, AC-10 to AC-12) ------------------------------------


def test_ac10_first_failure_returns_two_attempts_remaining(client):
    response = fail(client)
    assert response.status_code == 401
    assert response.json() == invalid_credentials(2)


def test_ac12_second_failure_returns_one_attempt_remaining(client):
    response = fail(client, times=2)
    assert response.status_code == 401
    assert response.json() == invalid_credentials(1)


def test_ac11_unknown_email_same_response_as_wrong_password(client, new_client):
    wrong_password = fail(client)
    unknown = login(new_client(), UNKNOWN_EMAIL, DEMO_PASSWORD)
    assert unknown.status_code == wrong_password.status_code == 401
    assert unknown.json() == wrong_password.json()


def test_fr18_unknown_email_is_counted_and_locked_like_known(client):
    responses = [login(client, UNKNOWN_EMAIL, WRONG_PASSWORD) for _ in range(3)]
    assert [r.status_code for r in responses] == [401, 401, 423]
    assert_locked(responses[-1], 5)


def test_fr18_failures_counted_on_normalized_email(client):
    login(client, "USER@example.com", WRONG_PASSWORD)
    response = login(client, " user@EXAMPLE.com ", WRONG_PASSWORD)
    assert response.json() == invalid_credentials(1)


def test_fr18_failures_for_one_email_do_not_count_for_another(client):
    fail(client, times=2)
    response = fail(client, email=OTHER_EMAIL)
    assert response.json() == invalid_credentials(2)


# --- Lock (FR-19, FR-20, FR-23, FR-24, AC-13 to AC-17) ------------------------------


def test_ac13_fr19_third_failure_locks_for_five_seconds(client):
    assert_locked(fail(client, times=3), 5)


def test_ac14_correct_password_refused_during_lock(client):
    fail(client, times=3)
    response = login(client, DEMO_EMAIL, DEMO_PASSWORD)
    assert response.status_code == 423
    assert 1 <= response.json()["retry_after"] <= 5
    assert "session" not in response.cookies
    assert client.get("/home", follow_redirects=False).status_code == 303


def test_fr20_lock_applies_to_normalized_email(client):
    fail(client, times=3)
    assert login(client, "  USER@Example.COM ", DEMO_PASSWORD).status_code == 423


def test_fr20_retry_after_counts_down(client, fake_clock):
    fail(client, times=3)
    fake_clock.advance(2.5)
    assert_locked(login(client, DEMO_EMAIL, DEMO_PASSWORD), 3)
    fake_clock.advance(2.0)
    assert_locked(login(client, DEMO_EMAIL, DEMO_PASSWORD), 1)


def test_ac14_fr20_requests_during_lock_do_not_extend_it(client, fake_clock):
    fail(client, times=3)
    fake_clock.advance(3)
    assert_locked(fail(client), 2)
    assert_locked(login(client, DEMO_EMAIL, DEMO_PASSWORD), 2)
    fake_clock.advance(2)
    assert login(client, DEMO_EMAIL, DEMO_PASSWORD).status_code == 200


def test_nfr7_lock_applies_to_every_client(client, new_client):
    fail(client, times=3)
    assert login(new_client(), DEMO_EMAIL, DEMO_PASSWORD).status_code == 423


def test_ac16_login_succeeds_after_lock_expires(client, fake_clock):
    fail(client, times=3)
    fake_clock.advance(5)
    response = login(client, DEMO_EMAIL, DEMO_PASSWORD)
    assert response.status_code == 200
    assert response.json() == SUCCESS


def test_ac15_fr23_three_attempts_again_after_lock(client, fake_clock):
    fail(client, times=3)
    fake_clock.advance(5)
    assert fail(client).json() == invalid_credentials(2)
    assert fail(client).json() == invalid_credentials(1)
    assert_locked(fail(client), 5)


def test_ac17_fr24_success_resets_count(client, new_client):
    fail(client, times=2)
    assert login(client, DEMO_EMAIL, DEMO_PASSWORD).status_code == 200
    response = fail(new_client())
    assert response.status_code == 401
    assert response.json() == invalid_credentials(2)


def test_fr25_failures_do_not_expire_on_their_own(client, fake_clock):
    fail(client, times=2)
    fake_clock.advance(3600)
    assert_locked(fail(client), 5)


def test_fr18_lock_does_not_affect_other_account(client):
    fail(client, times=3)
    response = login(client, OTHER_EMAIL, OTHER_PASSWORD)
    assert response.status_code == 200
    assert response.json() == SUCCESS


# --- Validation errors (FR-13, FR-11, NFR-8, AC-18) ----------------------------------


def test_ac18_invalid_email_returns_422_with_message_and_does_not_count(client):
    response = login(client, "name@example", DEMO_PASSWORD)
    assert response.status_code == 422
    assert response.json() == {"error": "validation_error", "fields": {"email": MSG_EMAIL_INVALID}}
    assert fail(client).json() == invalid_credentials(2)


def test_ac18_invalid_password_returns_422_with_message_and_does_not_count(client):
    response = login(client, DEMO_EMAIL, "green apple")
    assert response.status_code == 422
    assert response.json() == {
        "error": "validation_error",
        "fields": {"password": MSG_PASSWORD_INVALID},
    }
    assert fail(client).json() == invalid_credentials(2)


def test_fr13_both_fields_listed_when_both_invalid(client):
    response = login(client, "", "")
    assert response.status_code == 422
    assert response.json() == {
        "error": "validation_error",
        "fields": {"email": MSG_EMAIL_EMPTY, "password": MSG_PASSWORD_EMPTY},
    }


@pytest.mark.parametrize("email", INVALID_EMAILS)
def test_fr13_server_rejects_invalid_email(client, email):
    response = login(client, email, DEMO_PASSWORD)
    assert response.status_code == 422
    assert response.json() == {"error": "validation_error", "fields": {"email": MSG_EMAIL_INVALID}}


@pytest.mark.parametrize("email", EMPTY_EMAILS)
def test_fr13_server_rejects_empty_email(client, email):
    response = login(client, email, DEMO_PASSWORD)
    assert response.status_code == 422
    assert response.json() == {"error": "validation_error", "fields": {"email": MSG_EMAIL_EMPTY}}


@pytest.mark.parametrize("password", INVALID_PASSWORDS)
def test_fr13_server_rejects_invalid_password(client, password):
    response = login(client, DEMO_EMAIL, password)
    assert response.status_code == 422
    assert response.json() == {
        "error": "validation_error",
        "fields": {"password": MSG_PASSWORD_INVALID},
    }


def test_nfr8_overlong_values_rejected(client):
    assert login(client, "a" * 250 + "@example.com", DEMO_PASSWORD).status_code == 422
    assert login(client, DEMO_EMAIL, "a" * 125 + " b c").status_code == 422


def test_fr11_validation_errors_do_not_count_as_failures(client):
    for _ in range(5):
        login(client, DEMO_EMAIL, "green apple")
    assert fail(client).json() == invalid_credentials(2)


def test_fr13_validation_is_checked_before_lock(client):
    fail(client, times=3)
    response = login(client, DEMO_EMAIL, "green apple")
    assert response.status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"email": DEMO_EMAIL},
        {"password": DEMO_PASSWORD},
        {"email": 123, "password": DEMO_PASSWORD},
        {"email": DEMO_EMAIL, "password": None},
        ["not", "an", "object"],
    ],
)
def test_fr13_malformed_body_returns_422(client, body):
    response = client.post("/api/login", json=body)
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


def test_fr13_non_json_body_returns_422(client):
    response = client.post(
        "/api/login", content="email=a&password=b", headers={"content-type": "text/plain"}
    )
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


# --- Passwords never leak (NFR-1, NFR-4) -------------------------------------------


@pytest.mark.parametrize(
    "password",
    # "secret phrase" is too short (422); not a substring of the FR-9 message
    ["secret phrase", "secret  double space", DEMO_PASSWORD, WRONG_PASSWORD],
)
def test_nfr1_password_never_in_response_or_log(client, caplog, password):
    caplog.set_level(logging.DEBUG)
    for _ in range(4):
        response = login(client, DEMO_EMAIL, password)
        assert password not in response.text
        assert all(password not in value for value in response.headers.values())
    assert password not in caplog.text


def test_nfr1_password_not_echoed_in_malformed_422(client):
    secret = "my very secret phrase"
    response = client.post("/api/login", json={"email": 5, "password": secret})
    assert response.status_code == 422
    assert secret not in response.text


def test_nfr4_credentials_in_query_string_are_not_accepted(client):
    response = client.post(f"/api/login?email={DEMO_EMAIL}&password=green+apple+house")
    assert response.status_code == 422
    assert "session" not in response.cookies


def test_nfr4_get_login_is_not_allowed(client):
    response = client.get(f"/api/login?email={DEMO_EMAIL}&password=green+apple+house")
    assert response.status_code == 405


# --- Speed (NFR-11) ------------------------------------------------------------


@pytest.mark.parametrize("password", [DEMO_PASSWORD, WRONG_PASSWORD])
def test_nfr11_login_responds_within_one_second(client, password):
    start = time.perf_counter()
    login(client, DEMO_EMAIL, password)
    assert time.perf_counter() - start < 1.0
